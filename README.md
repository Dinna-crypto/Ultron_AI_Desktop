# ULTRON — Local Voice/Gesture Desktop Assistant (Windows)

A JARVIS/Ultron-style assistant that runs entirely on your own PC:
voice commands, system diagnostics, code error analysis, hand-gesture
control, an animated reactor-core HUD, and a bridge to your Android phone.

## What it actually does (and doesn't)

✅ Wake-word voice control ("Ultron, ...")
✅ Opens apps/files, runs system diagnostics, analyzes Python errors
✅ Hand gestures via webcam (pinch to zoom, swipe to switch windows)
✅ Animated Ultron-style HUD (glowing core, spinning rings, live state)
✅ Push notifications to your phone; phone can send commands back to the PC

❌ Does **not** remotely unlock your phone. Android/iOS deliberately block
   that — any tool claiming otherwise is either lying or a security risk.
   What it *does* do: push a command to your phone that Tasker can act on
   (open an app, read a notification, reply to a text) while your phone's
   own PIN/biometric lock stays fully intact.
❌ Isn't a general AI that "does anything" unprompted — every capability
   here is an explicit command you define, which is what makes it safe to
   run with system-level access in the first place.

## 1. Setup (Windows)

```bash
# Python 3.10+ recommended
pip install -r requirements.txt
```

Notes on tricky installs:
- **Audio capture uses `sounddevice`, not PyAudio.** PyAudio needs a C++
  compiler to build on Python 3.13+ (no prebuilt Windows wheel exists yet
  upstream) — `sounddevice` avoids that entirely with prebuilt wheels, so
  there's nothing extra to install here.
- **mediapipe** requires 64-bit Python.
- Grant microphone + webcam permission to Python/Terminal in
  Windows Settings > Privacy > Microphone / Camera.
- If you have multiple microphones and the wrong one gets used, list
  devices with `python -c "import sounddevice as sd; print(sd.query_devices())"`
  and set the default: `sd.default.device = <index>` near the top of
  `voice_engine.py`.

**How listening works now:** instead of continuously streaming audio,
Ultron records short fixed clips (4 seconds by default) and checks each
one for the wake word. So say **"Ultron"**, pause briefly for the "Yes?"
prompt, then say your command — or say it all in one breath
("Ultron, open chrome") within that 4-second window. Adjust
`phrase_seconds` / `command_seconds` in `VoiceEngine(...)` inside
`main.py` if you want longer windows.

## 2. Configure your apps

Open `command_handler.py` and edit the `APP_PATHS` dictionary to match
where your actual apps live, e.g.:

```python
APP_PATHS = {
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "vscode": r"C:\Users\YOURNAME\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    ...
}
```

## 3. Enable deep code analysis (free, local, recommended)

Code errors work out of the box with a solid local heuristic (covers the
~15 most common Python exceptions, zero setup). For genuinely deep
root-cause analysis of *your specific code*, Ultron checks these in order:

**Option A — Ollama (100% free, runs on your PC, no API key, no internet):**
1. Download and install from https://ollama.com/download
2. Pull a model once: `ollama pull llama3.1` (about 4.7GB)
3. That's it — Ollama runs its own local server automatically, and
   `code_analyzer.py` will detect and use it with zero configuration.
   This is also the more "Ultron" way to do it: no cloud, no API bill,
   your code never leaves your machine.

**Option B — Claude API (paid, no free tier, but the deepest analysis):**
```bash
setx ANTHROPIC_API_KEY "your-key-here"
```
Only used if Ollama isn't running.

**Option C — do nothing:** falls back to the local heuristic explainer,
which is instant and covers the common cases (NameError, TypeError,
ModuleNotFoundError, etc.) but won't reason about your specific logic.

## 4. Run it

```bash
python main.py
```

This launches:
- The voice loop (say **"Ultron"**, then your command)
- The Ultron HUD window (borderless, always-on-top, reacts to state)
- A local server on port 5151 for your phone to talk to

Try saying:
- "Ultron, open chrome"
- "Ultron, system report"
- "Ultron, analyze C:\projects\app.py"
- "Ultron, search latest news"

## 5. Hand gestures (run separately, needs its own webcam loop)

```bash
python gesture_control.py
```

- **Pinch in/out** (thumb + index finger) → zoom out / in (Ctrl -/+)
- **Swipe palm right** → Alt+Tab
- **Swipe palm left** → Task View (Win+Tab)
- **Make a fist** → pauses gesture recognition (safety stop)

Tune sensitivity via `_action_cooldown` and the `0.04` / `0.08` thresholds
in `gesture_control.py` if it's too twitchy or too sluggish.

## 6. Connect your Android phone

**A. Receive pushes from the PC (2 minutes):**
1. Install the **ntfy** app from the Play Store.
2. Pick a private topic name nobody would guess, e.g. `ultron-7f2ac91`.
3. Subscribe to that topic in the ntfy app.
4. Set it on your PC before running:
   ```bash
   setx ULTRON_NTFY_TOPIC "ultron-7f2ac91"
   ```
5. Now `phone_bridge.notify_phone("message")` (or saying "Ultron, notify
   my phone saying ...") pushes straight to your phone's lock screen.

**B. Send commands from the phone to the PC:**
1. Find your PC's local IP: open Command Prompt → `ipconfig` → note the
   IPv4 address (e.g. `192.168.1.42`).
2. From your phone's browser (same WiFi), visit
   `http://192.168.1.42:5151/status` — you should see `{"status": "online"}`.
3. For real one-tap commands, install **Tasker** on Android and create a
   task with an **HTTP Request** action:
   - Method: POST
   - URL: `http://192.168.1.42:5151/command`
   - Body: `{"text": "open chrome"}`
   Bind that task to a widget, NFC tag, or voice shortcut ("Hey Google,
   run Ultron command") for a true phone-to-PC trigger.
4. `GET http://192.168.1.42:5151/report` from the phone browser gives you
   a live JSON system report, anywhere on your home network.

## 7. Security notes (read this)

- The Flask server has **no authentication** by default — fine on a
  trusted home network, not fine if you expose port 5151 to the internet.
  If you want it reachable outside your LAN, put it behind a proper
  auth layer (e.g. an API key header check) first.
- The `shutdown computer` voice command is intentionally disabled in
  `command_handler.py`. Remove the guard only if you're confident in your
  wake-word false-positive rate.
- Gesture control uses `pyautogui.FAILSAFE = True` — slam your mouse to a
  screen corner any time to instantly kill an in-progress automated action.

## File map

```
ultron/
├── main.py              # orchestrator — run this
├── voice_engine.py       # wake word, speech-to-text, text-to-speech
├── command_handler.py    # routes text -> real actions (EDIT APP_PATHS HERE)
├── system_monitor.py     # CPU/RAM/disk/process diagnostics
├── code_analyzer.py      # runs scripts, explains tracebacks
├── gesture_control.py    # webcam hand-gesture -> OS actions
├── phone_bridge.py       # Flask server + ntfy push for Android
├── hud/hud.html          # Ultron-style animated HUD (WebSocket-driven)
└── requirements.txt
```

## Extending it

- Add more voice commands in `command_handler.py`'s `handle()` method.
- Add more gestures in `gesture_control.py` (e.g. two-hand gestures,
  finger-count commands using `mp_hands` landmark indices).
- Add more Tasker profiles on Android to react to specific ntfy messages
  (e.g. "if message contains 'lock', trigger Do Not Disturb").
