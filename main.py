"""
main.py
Boots the full Ultron assistant:
  - voice_engine   (wake word "ultron" + speech recognition + TTS)
  - command_handler (routes text -> real actions)
  - gesture_control (started/stopped on demand via voice: "start gestures")
  - phone_bridge   (Flask server + ntfy push, for Android)
  - HUD            (Ultron-style visual, in a native window via pywebview)

Run with:  python main.py
Stop with: Ctrl+C in the console, or close the HUD window.
"""

# Load .env FIRST, before any other project module is imported — several
# modules (phone_bridge, agent, web_search_tool, weather_tool, etc.) read
# their config with os.environ.get(...) at import time, so the .env file
# has to be loaded before those imports happen or it's too late.
from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import threading
import time
import webview
import websockets

from voice_engine import VoiceEngine
from command_handler import CommandHandler
from gesture_control import GestureController
from sentry import SentryController
import phone_bridge
import event_log
import calendar_integration
import agent
import system_monitor

HUD_PATH = f"http://localhost:5151/dashboard?token={phone_bridge.API_TOKEN}"
WS_PORT = 8765


class GestureManager:
    """Starts/stops gesture recognition on its own thread, on demand,
    so it doesn't run (and hold the webcam) unless you actually ask
    for it via voice."""
    def __init__(self, on_state_change):
        self.on_state_change = on_state_change
        self._controller = None
        self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> str:
        if self.is_running():
            return "Gesture control is already active."
        try:
            self._controller = GestureController(on_state_change=self.on_state_change)
        except Exception as e:
            return f"Couldn't start gesture control: {e}"
        self._thread = threading.Thread(target=self._controller.run, daemon=True)
        self._thread.start()
        return "Gesture control activated. Show me your hand — pinch to zoom, swipe to switch windows, fist to pause. Press Q on the camera window, or say 'stop gestures', to end."

    def stop(self) -> str:
        if not self.is_running():
            return "Gesture control isn't running."
        self._controller.stop()
        self._thread.join(timeout=3)
        return "Gesture control stopped."


class SentryManager:
    """Starts/stops security sentry mode on its own thread. When a face
    is detected, pushes an image alert to the phone via the provided
    notify_fn (phone_bridge.notify_phone_with_image)."""
    def __init__(self, on_state_change, notify_fn):
        self.on_state_change = on_state_change
        self.notify_fn = notify_fn
        self._controller = None
        self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> str:
        if self.is_running():
            return "Sentry mode is already active."

        def on_alert(image_path):
            event_log.log_event("sentry", f"Face detected, snapshot saved to {image_path}")
            self.notify_fn(image_path, "Someone's at your PC.")

        try:
            self._controller = SentryController(on_alert=on_alert, on_state_change=self.on_state_change)
        except Exception as e:
            return f"Couldn't start sentry mode: {e}"
        self._thread = threading.Thread(target=self._controller.run, daemon=True)
        self._thread.start()
        return "Sentry mode activated. I'll alert your phone with a photo if anyone shows up on camera."

    def stop(self) -> str:
        if not self.is_running():
            return "Sentry mode isn't running."
        self._controller.stop()
        self._thread.join(timeout=3)
        return "Sentry mode deactivated."

# ---- WebSocket state broadcaster (HUD listens to this) ----
_connected_clients = set()
_loop = None


async def _ws_handler(websocket):
    _connected_clients.add(websocket)
    try:
        async for _ in websocket:
            pass  # HUD doesn't send anything back, just listens
    finally:
        _connected_clients.discard(websocket)


async def _broadcast(state: str, text: str = "", progress=None):
    if not _connected_clients:
        return
    payload = json.dumps({"state": state, "text": text, "progress": progress})
    await asyncio.gather(*(ws.send(payload) for ws in list(_connected_clients)),
                          return_exceptions=True)


def push_state(state: str, text: str = "", progress=None):
    """Thread-safe hook other modules call to update the HUD."""
    if _loop is not None:
        asyncio.run_coroutine_threadsafe(_broadcast(state, text, progress), _loop)


def _start_ws_server():
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

    async def _serve():
        async with websockets.serve(_ws_handler, "localhost", WS_PORT):
            await asyncio.Future()  # run forever

    _loop.run_until_complete(_serve())


def boot_sequence(voice):
    """
    A dramatic, staged activation sequence: flashing red HUD, escalating
    progress percentage, and a staged voice countdown, before the
    assistant actually goes live and starts normal listening.
    """
    steps = [
        ("Initializing core systems.", 12),
        ("Calibrating audio input matrix.", 30),
        ("Loading gesture recognition protocols.", 48),
        ("Establishing local network uplink.", 65),
        ("Synchronizing command pathways.", 82),
        ("All systems nominal.", 95),
        ("Ultron online.", 100),
    ]
    push_state("booting", "Activation sequence initiated.", 0)
    time.sleep(0.6)
    for text, progress in steps:
        push_state("booting", text, progress)
        voice.speak(text)
        # Rough pacing so the HUD progress and the spoken line land
        # together, instead of the HUD racing ahead of the voice.
        time.sleep(max(1.0, len(text.split()) / 2.2))
    push_state("idle", "Say the word to begin.")
    voice.speak("Say the word to begin.")


def boot_report(voice):
    """
    Runs right after the activation sequence: gives a spoken system
    status report, plus a summary of anything logged (sentry alerts,
    missed commands) since the last time Ultron was running.
    """
    events = event_log.get_events_since_last_boot()
    summary = event_log.summarize_events(events)
    voice.speak(summary)

    report = system_monitor.get_report()
    voice.speak(system_monitor.report_to_speech(report))

    event_log.mark_boot()


def main():
    # 1. Voice engine setup
    voice = VoiceEngine(
        wake_word="ultron",
        on_state_change=lambda state: push_state(state)
    )

    # 2. Gesture manager, started/stopped on demand by voice command
    gestures = GestureManager(on_state_change=lambda state: push_state(state))
    sentry = SentryManager(on_state_change=lambda state: push_state(state),
                            notify_fn=phone_bridge.notify_phone_with_image)

    # 3. Command handler wired to voice.speak and phone notifications
    handler = CommandHandler(speak_fn=voice.speak, notify_fn=phone_bridge.notify_phone)
    agent.init(handler)

    def on_command(text: str):
        push_state("thinking", text)
        t = text.lower().strip()
        if "sentry" in t and ("stop" in t or "deactivate" in t or "off" in t):
            reply = sentry.stop()
        elif "sentry" in t:
            reply = sentry.start()
        elif t in ("start", "start gesture", "start gestures") or \
           "gesture mode" in t or "activate gesture" in t or "hand tracking" in t:
            reply = gestures.start()
        elif t in ("stop", "stop gesture", "stop gestures"):
            reply = gestures.stop()
        else:
            reply = handler.handle(text)
        voice.speak(reply)

    voice.on_command = on_command

    # 4. Phone bridge dispatcher: lets phone-issued commands run the same path
    def phone_dispatch(text: str) -> str:
        push_state("thinking", f"[phone] {text}")
        t = text.lower().strip()
        if "sentry" in t and ("stop" in t or "deactivate" in t or "off" in t):
            reply = sentry.stop()
        elif "sentry" in t:
            reply = sentry.start()
        elif t in ("start", "start gesture", "start gestures") or "gesture mode" in t:
            reply = gestures.start()
        elif t in ("stop", "stop gesture", "stop gestures"):
            reply = gestures.stop()
        else:
            reply = handler.handle(text)
        voice.speak(reply)
        return reply

    phone_bridge.set_dispatcher(phone_dispatch)

    # 5. Start the websocket state server (drives the HUD)
    threading.Thread(target=_start_ws_server, daemon=True).start()

    # 6. Start the Flask phone bridge server
    threading.Thread(
        target=phone_bridge.run_server,
        kwargs={"host": "0.0.0.0", "port": 5151},
        daemon=True
    ).start()

    # 7. Dramatic activation sequence, then a system/event report, then
    # normal listening — delayed slightly so the HUD window has time to
    # load and connect its websocket before we start broadcasting to it.
    def _delayed_boot_and_listen():
        time.sleep(1.5)
        boot_sequence(voice)
        boot_report(voice)
        voice.listen_loop()

    threading.Thread(target=_delayed_boot_and_listen, daemon=True).start()

    # 7b. Google Calendar meeting watcher (only starts if credentials.json
    # is present — see calendar_integration.py for one-time setup steps)
    def on_meeting_soon(event):
        msg = f"Heads up — {event['summary']} starts soon."
        voice.speak(msg)
        phone_bridge.notify_phone(msg, title="Ultron — Meeting Reminder")

    if calendar_integration.is_configured():
        calendar_integration.start_watcher_thread(on_meeting_soon, warn_minutes=10)
    else:
        print("[main] Google Calendar not configured (no credentials.json) — "
              "meeting reminders disabled. See calendar_integration.py for setup.")

    # 8. Launch the HUD window (now the full dashboard) — blocking call,
    # keeps the app alive if it works
    try:
        webview.create_window(
            "ULTRON",
            HUD_PATH,
            width=1400, height=900,
            resizable=True,
            on_top=False,
            background_color="#050201"
        )
        webview.start(debug=True)
    except Exception:
        import traceback
        print("\n=== HUD WINDOW CRASHED — full traceback below ===")
        traceback.print_exc()
        print("\nContinuing in VOICE-ONLY mode (no visual HUD). Voice, gestures,")
        print("system commands, and the phone bridge all still work.")
        print("Press CTRL+C to quit.\n")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down.")


if __name__ == "__main__":
    main()