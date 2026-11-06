"""
phone_bridge.py
Connects Ultron to your Android phone using two free, no-signup pieces
of infrastructure:

  1. ntfy.sh — send push notifications / commands FROM the PC TO your phone.
  2. A local Flask server — lets your phone send commands TO the PC.

SECURITY: every route except /status requires a token, passed either as
a header (X-Ultron-Token) or a URL query param (?token=...). Set
ULTRON_API_TOKEN in your .env file — if you don't, one is generated
randomly each run (which will keep breaking any bookmarked panel/
dashboard URL, since it changes every restart), so set it once and
keep it.

IMPORTANT — about phone unlocking:
Android intentionally does not allow a remote device to bypass its lock
screen. What we CAN do: have Tasker (installed on your phone) listen
for a push/command and run an on-device profile (open an app, read a
notification, reply to a text) while your phone's own lock stays fully
in control.
"""

import os
import secrets
import functools
import requests
from flask import Flask, request, jsonify, Response

NTFY_TOPIC = os.environ.get("ULTRON_NTFY_TOPIC", "Ultron-zxcvb")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

API_TOKEN = os.environ.get("ULTRON_API_TOKEN", "")
if not API_TOKEN:
    API_TOKEN = secrets.token_urlsafe(24)
    print("=" * 70)
    print("[phone_bridge] WARNING: no ULTRON_API_TOKEN set in .env — using a")
    print(f"random one for this session only: {API_TOKEN}")
    print("Add ULTRON_API_TOKEN=<this value> to your .env file so it stays")
    print("the same across restarts, or your bookmarked panel/dashboard URLs")
    print("will break every time you restart Ultron.")
    print("=" * 70)

app = Flask(__name__)

_command_dispatcher = None


def require_token(f):
    """Checks the request for a valid token, either as header
    X-Ultron-Token or query param ?token=. Returns 401 if missing/wrong."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Ultron-Token") or request.args.get("token", "")
        if not secrets.compare_digest(token, API_TOKEN):
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper


PANEL_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ULTRON</title>
<style>
  body { background:#05060a; color:#d8dee6; font-family:sans-serif; margin:0; padding:16px; }
  h1 { color:#ff2b1f; letter-spacing:3px; font-size:20px; text-align:center; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:16px; }
  button {
    background:#14171d; color:#d8dee6; border:1px solid #5c1006;
    border-radius:10px; padding:18px 8px; font-size:15px; font-weight:bold;
  }
  button:active { background:#ff2b1f; color:#000; }
  #reply { margin-top:16px; padding:12px; background:#14171d; border-radius:10px;
           min-height:20px; font-size:14px; color:#ffb238; }
  input { width:100%; box-sizing:border-box; padding:12px; margin-top:16px;
          border-radius:10px; border:1px solid #5c1006; background:#14171d; color:#fff; }
</style>
</head>
<body>
  <h1>ULTRON</h1>
  <div class="grid">
    <button onclick="send('system report')">System Report</button>
    <button onclick="send('open chrome')">Open Chrome</button>
    <button onclick="send('take a screenshot')">Screenshot</button>
    <button onclick="send('volume up')">Volume Up</button>
    <button onclick="send('volume down')">Volume Down</button>
    <button onclick="send('mute')">Mute</button>
    <button onclick="send('lock pc')">Lock PC</button>
    <button onclick="send('start')">Start Gestures</button>
    <button onclick="send('stop')">Stop Gestures</button>
    <button onclick="send('minimize all windows')">Minimize All</button>
  </div>
  <input id="custom" placeholder="Type any command..." onkeydown="if(event.key==='Enter') sendCustom()">
  <div id="reply">Ready.</div>
<script>
  const ULTRON_TOKEN = "__TOKEN__";
  async function send(text) {
    document.getElementById('reply').innerText = 'Sending: ' + text + ' ...';
    try {
      const res = await fetch('/command', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Ultron-Token': ULTRON_TOKEN},
        body: JSON.stringify({text: text})
      });
      const data = await res.json();
      document.getElementById('reply').innerText = data.reply || JSON.stringify(data);
    } catch (e) {
      document.getElementById('reply').innerText = 'Error: ' + e;
    }
  }
  function sendCustom() {
    const val = document.getElementById('custom').value;
    if (val) send(val);
    document.getElementById('custom').value = '';
  }
</script>
</body>
</html>
"""


def set_dispatcher(fn):
    """fn(text: str) -> str   -- runs a command and returns a spoken/text reply"""
    global _command_dispatcher
    _command_dispatcher = fn


def notify_phone(message: str, title: str = "Ultron"):
    """Push a notification to the phone via ntfy."""
    print(f"[debug] publishing ntfy notification to topic '{NTFY_TOPIC}' -> {NTFY_URL}")
    try:
        resp = requests.post(NTFY_URL, data=message.encode("utf-8"),
                              headers={"Title": title}, timeout=5)
        print(f"[debug] ntfy response: {resp.status_code} {resp.text[:200]}")
        return True
    except requests.RequestException as e:
        print(f"[phone_bridge] notify failed: {e}")
        return False


def notify_phone_with_image(image_path: str, message: str = "", title: str = "Ultron Sentry"):
    """Pushes a notification with an image attached (e.g. a sentry-mode
    snapshot), using ntfy's file-attachment support."""
    print(f"[debug] publishing ntfy image notification to topic '{NTFY_TOPIC}'")
    try:
        with open(image_path, "rb") as f:
            data = f.read()
        headers = {"Title": title, "Filename": os.path.basename(image_path)}
        if message:
            headers["Message"] = message
        resp = requests.post(NTFY_URL, data=data, headers=headers, timeout=10)
        print(f"[debug] ntfy image response: {resp.status_code} {resp.text[:200]}")
        return resp.status_code == 200
    except Exception as e:
        print(f"[phone_bridge] sentry image notify failed: {e}")
        return False


@app.route("/status", methods=["GET"])
def status():
    """Left unauthenticated on purpose — just confirms the server is up,
    reveals nothing sensitive, useful for a quick reachability check."""
    return jsonify({"status": "online", "assistant": "Ultron"})


@app.route("/panel", methods=["GET"])
@require_token
def panel():
    """A zero-install mobile control panel. Bookmark this URL WITH your
    token on your phone's browser, e.g.:
    http://<ip>:5151/panel?token=<your ULTRON_API_TOKEN>"""
    return PANEL_HTML_TEMPLATE.replace("__TOKEN__", API_TOKEN)


@app.route("/dashboard", methods=["GET"])
@require_token
def dashboard():
    """Live system dashboard. Bookmark WITH your token, e.g.:
    http://<ip>:5151/dashboard?token=<your ULTRON_API_TOKEN>"""
    dashboard_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hud", "dashboard.html")
    with open(dashboard_path, "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__ULTRON_TOKEN__", API_TOKEN)
    return Response(html, mimetype="text/html")


@app.route("/command", methods=["POST"])
@require_token
def command():
    """
    Phone -> PC command endpoint.
    Send a POST with JSON: {"text": "open chrome"} and header
    X-Ultron-Token: <your ULTRON_API_TOKEN>
    """
    data = request.get_json(force=True, silent=True) or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "no text provided"}), 400
    if _command_dispatcher is None:
        return jsonify({"error": "dispatcher not ready"}), 503
    reply = _command_dispatcher(text)
    return jsonify({"reply": reply})


@app.route("/report", methods=["GET"])
@require_token
def report():
    """Quick system report, fetchable straight from the phone's browser."""
    import system_monitor
    r = system_monitor.get_report()
    return jsonify(r)


def run_server(host="0.0.0.0", port=5151):
    """
    Runs on your PC's local network. threaded=True matters: without it,
    Flask's dev server handles ONE request at a time, so a single slow
    request (e.g. the AI agent waiting on a slow API call) freezes
    every other button on the panel/dashboard until it resolves.
    """
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    run_server()