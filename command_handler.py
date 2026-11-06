"""
command_handler.py
Central command router. Takes free-text (from voice or phone) and maps
it to real actions: opening apps/files, system reports, code analysis,
web searches, notifications, etc.

Add your own app shortcuts in APP_PATHS below.
"""

import os
import subprocess
import webbrowser
import ctypes
import datetime
import psutil
import pyautogui
import system_monitor
import code_analyzer
import agent
import event_log

# Direct Windows Core Audio control (more reliable than simulated media
# keys, which some drivers/focused apps silently ignore).
from pycaw.pycaw import AudioUtilities


def _get_volume_interface():
    device = AudioUtilities.GetSpeakers()
    return device.EndpointVolume

# Map spoken app names -> real executables / paths on YOUR machine.
# Edit these to match what's actually installed.
APP_PATHS = {
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "firefox": r"C:\Program Files\Mozilla Firefox\firefox.exe",
    "browser": r"C:\Program Files\Google\Chrome\Application\chrome.exe",  # generic "open browser" -> your default pick
    "vscode": r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    "notepad": "notepad.exe",
    "explorer": "explorer.exe",
    "calculator": "calc.exe",
    "spotify": r"C:\Users\%USERNAME%\AppData\Roaming\Spotify\Spotify.exe",
    "terminal": "wt.exe",
    # WhatsApp/Telegram Desktop: if installed from the Microsoft Store rather
    # than a direct installer, there's no plain .exe path — instead this
    # launches it via its URI protocol, which Windows resolves automatically.
    "whatsapp": "whatsapp:",
    "telegram": r"C:\Users\%USERNAME%\AppData\Roaming\Telegram Desktop\Telegram.exe",
}

# Maps the same spoken app names -> their actual running process name,
# used only for the "close <app>" command (via psutil, not APP_PATHS).
PROCESS_NAMES = {
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
    "browser": "chrome.exe",
    "vscode": "Code.exe",
    "notepad": "notepad.exe",
    "calculator": "CalculatorApp.exe",
    "spotify": "Spotify.exe",
    "whatsapp": "WhatsApp.exe",
    "telegram": "Telegram.exe",
}


class CommandHandler:
    def __init__(self, speak_fn, notify_fn=None):
        """
        speak_fn: function(str) -> None, used to respond out loud (voice path)
        notify_fn: function(str) -> None, used to push to phone (optional)
        """
        self.speak = speak_fn
        self.notify = notify_fn or (lambda msg: None)

    def handle(self, text: str) -> str:
        """Returns the text reply (also spoken, and optionally pushed to phone)."""
        t = text.lower().strip()

        if t.startswith("open "):
            return self._open_app(t.replace("open ", "", 1).strip())

        if t.startswith("close "):
            return self._close_app(t.replace("close ", "", 1).strip())

        if "system report" in t or "diagnostics" in t or "status report" in t:
            return self._system_report()

        if t.startswith("analyze ") or "check my code" in t or "debug" in t:
            return self._analyze_code(t)

        if t.startswith("search "):
            query = t.replace("search ", "", 1).strip()
            webbrowser.open(f"https://www.google.com/search?q={query}")
            return f"Searching for {query}."

        if "shutdown" in t and "computer" in t:
            return "Shutdown command recognized but disabled by default for safety. Remove the safeguard in command_handler.py if you really want this live."

        if "notify" in t and "phone" in t:
            msg = t.split("saying", 1)[-1].strip() if "saying" in t else "Ultron here."
            self.notify(msg)
            return "Notification sent to your phone."

        if "volume up" in t or "increase volume" in t:
            return self._volume_step(0.10)

        if "volume down" in t or "decrease volume" in t or "lower volume" in t:
            return self._volume_step(-0.10)

        if "unmute" in t:
            return self._set_mute(False)

        if "mute" in t:
            return self._set_mute(True)

        if "screenshot" in t:
            return self._take_screenshot()

        if "dashboard" in t:
            webbrowser.open("http://localhost:5151/dashboard")
            return "Opening the dashboard."

        if t in ("play", "pause", "play music", "pause music", "toggle playback",
                 "resume music", "resume playback", "play pause"):
            pyautogui.press("playpause")
            return "Toggling playback."

        if "next track" in t or "skip track" in t or "next song" in t:
            pyautogui.press("nexttrack")
            return "Skipping to next track."

        if "previous track" in t or "last track" in t or "previous song" in t:
            pyautogui.press("prevtrack")
            return "Going to previous track."

        if "sleep" in t and ("pc" in t or "computer" in t):
            ctypes.windll.powrprof.SetSuspendState(0, 1, 0)
            return "Putting the PC to sleep."

        if "restart" in t and ("pc" in t or "computer" in t):
            return "Restart command recognized but disabled by default for safety. Remove the safeguard in command_handler.py if you really want this live."

        if "lock" in t and ("pc" in t or "computer" in t or "screen" in t):
            ctypes.windll.user32.LockWorkStation()
            return "Locking the PC."

        if "minimize" in t and ("all" in t or "everything" in t or "windows" in t):
            pyautogui.hotkey("win", "d")
            return "Minimizing all windows."

        if "who are you" in t or "introduce yourself" in t:
            return "I am Ultron, your local assistant. No world domination today — just file management and diagnostics."

        # Nothing matched a built-in fast command — log it, then hand
        # off to the LangGraph agent so it can still take real action
        # via tools, or explain itself, instead of a dead end.
        event_log.log_event("missed_command", text)
        return agent.run(text)

    def _volume_step(self, delta: float) -> str:
        try:
            device = AudioUtilities.GetSpeakers()
            volume = device.EndpointVolume
            device_name = getattr(device, "FriendlyName", "unknown device")
            current = volume.GetMasterVolumeLevelScalar()
            new_level = min(1.0, max(0.0, current + delta))
            volume.SetMasterVolumeLevelScalar(new_level, None)
            print(f"[debug] volume changed on device: {device_name} "
                  f"({round(current*100)}% -> {round(new_level*100)}%)")
            return (f"Volume {'up' if delta > 0 else 'down'}, now at {round(new_level * 100)} percent "
                    f"on {device_name}.")
        except Exception as e:
            return f"Couldn't change volume: {e}"

    def _set_mute(self, muted: bool) -> str:
        try:
            device = AudioUtilities.GetSpeakers()
            volume = device.EndpointVolume
            device_name = getattr(device, "FriendlyName", "unknown device")
            volume.SetMute(1 if muted else 0, None)
            print(f"[debug] {'muted' if muted else 'unmuted'} device: {device_name}")
            return f"Muted {device_name}." if muted else f"Unmuted {device_name}."
        except Exception as e:
            return f"Couldn't change mute state: {e}"

    def _open_app(self, name: str) -> str:
        name = name.strip().lower()
        path = APP_PATHS.get(name)
        if not path:
            # Fall back: try opening it as a file/folder path directly
            expanded = os.path.expandvars(name)
            if os.path.exists(expanded):
                os.startfile(expanded)
                return f"Opening {name}."
            return f"I don't know an app called {name}. Add it to APP_PATHS in command_handler.py."
        try:
            if path.endswith(":"):
                # URI protocol launch (e.g. "whatsapp:") for Store-installed apps
                os.startfile(path)
            else:
                expanded_path = os.path.expandvars(path)
                subprocess.Popen(expanded_path)
            return f"Opening {name}."
        except Exception as e:
            return f"Failed to open {name}: {e}"

    def _close_app(self, name: str) -> str:
        name = name.strip().lower()
        process_name = PROCESS_NAMES.get(name)
        if not process_name:
            return f"I don't know the process name for {name}. Add it to PROCESS_NAMES in command_handler.py."

        closed = 0
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if proc.info["name"] and proc.info["name"].lower() == process_name.lower():
                    proc.terminate()
                    closed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if closed:
            return f"Closed {name} ({closed} process{'es' if closed > 1 else ''})."
        return f"{name} doesn't appear to be running."

    def _take_screenshot(self) -> str:
        pictures_dir = os.path.join(os.path.expanduser("~"), "Pictures", "Ultron Screenshots")
        os.makedirs(pictures_dir, exist_ok=True)
        filename = f"screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        filepath = os.path.join(pictures_dir, filename)
        img = pyautogui.screenshot()
        img.save(filepath)
        return f"Screenshot saved to {filepath}."

    def _system_report(self) -> str:
        report = system_monitor.get_report()
        spoken = system_monitor.report_to_speech(report)
        return spoken

    def _analyze_code(self, text: str) -> str:
        # naive path extraction: "analyze C:\projects\app.py"
        parts = text.split()
        path_candidates = [p for p in parts if p.endswith(".py")]
        if not path_candidates:
            return "Tell me the path to the Python file, e.g. 'analyze C colon backslash projects backslash app dot p y'."
        path = path_candidates[0]
        if not os.path.exists(path):
            return f"I can't find a file at {path}."
        result = code_analyzer.analyze(path)
        return result