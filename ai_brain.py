"""
ai_brain.py
General conversational AI fallback for Ultron. Used when a spoken
command doesn't match any built-in command in command_handler.py, so
Ultron can actually hold a conversation instead of just saying
"I don't understand."

Free, local, no API key: uses Ollama if it's installed and running
(https://ollama.com). Falls back to Anthropic Claude if ANTHROPIC_API_KEY
is set and Ollama isn't available. If neither is available, returns a
plain, honest "no AI backend configured" message rather than pretending.
"""

import os
import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:1b")

SYSTEM_PROMPT = (
    "You are Ultron, a helpful local voice assistant running on the user's "
    "own PC. Keep replies SHORT: 1-3 sentences maximum, since they get read "
    "aloud by text-to-speech and long replies are tedious to listen to. Be "
    "direct and a little dry/witty, but genuinely helpful. Never claim you "
    "took a real-world action (like opening an app) in this reply, since "
    "you are only the general-conversation fallback, not the command router."
)

try:
    import anthropic
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False


def _ollama_available() -> bool:
    try:
        requests.get(OLLAMA_URL.replace("/api/generate", "/api/tags"), timeout=1)
        return True
    except requests.RequestException:
        return False


def _ask_ollama(prompt: str):
    full_prompt = f"{SYSTEM_PROMPT}\n\nUser: {prompt}\nUltron:"
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": full_prompt, "stream": False},
            timeout=30
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except requests.RequestException as e:
        print(f"[ai_brain] Ollama call failed: {e}")
        return None


def _ask_claude(prompt: str):
    if not _HAS_ANTHROPIC or not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        print(f"[ai_brain] Claude call failed: {e}")
        return None


def chat(prompt: str) -> str:
    if _ollama_available():
        reply = _ask_ollama(prompt)
        if reply:
            return reply

    reply = _ask_claude(prompt)
    if reply:
        return reply

    return ("I heard you, but I don't have a command mapped for that, and no AI "
            "backend is available for general conversation. Install Ollama from "
            "ollama.com and run 'ollama pull llama3.1' to enable this.")
