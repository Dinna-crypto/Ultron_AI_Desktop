"""
code_analyzer.py
Runs a target script, captures any traceback, and explains the error.

Three tiers of analysis, in priority order:
  1. Ollama (FREE, fully local, no API key, no internet needed) — if you
     have it installed and running (https://ollama.com), this is used
     automatically. Recommended default: `ollama pull llama3.1` then
     `ollama serve` (it usually auto-starts after install).
  2. Anthropic Claude — if ANTHROPIC_API_KEY is set, used for the deepest
     analysis (costs a small amount per call, no free tier).
  3. Local heuristic explainer — always available as the final fallback,
     zero setup, covers ~15 common Python error types.
"""

import subprocess
import sys
import os
import re
import json
import requests


OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:1b")

# Optional deep analysis via Claude (paid, no free tier)
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


COMMON_ERRORS = {
    "ModuleNotFoundError": "A required package isn't installed. Run pip install <package name> to fix it.",
    "ImportError": "Something failed to import — check the module name and that it's installed correctly.",
    "SyntaxError": "There's a typo or malformed structure in the code — often a missing colon, bracket, or quote.",
    "IndentationError": "Python is picky about whitespace — check that this block's indentation matches its neighbors.",
    "NameError": "You're using a variable or function before it's defined, or there's a typo in its name.",
    "TypeError": "An operation was used on a type it doesn't support — e.g. adding a string to a number.",
    "ValueError": "A function got an argument of the right type but an invalid value.",
    "KeyError": "You tried to access a dictionary key that doesn't exist.",
    "IndexError": "You tried to access a list/array index that's out of range.",
    "AttributeError": "You tried to use a method or property that doesn't exist on that object.",
    "ZeroDivisionError": "Division by zero — check your denominator before dividing.",
    "FileNotFoundError": "The file path doesn't exist or is misspelled — double check the path.",
    "PermissionError": "The process doesn't have OS-level permission to access this file or resource.",
}


def run_and_capture(script_path: str, args=None, timeout=30) -> dict:
    """Runs a Python script and captures stdout/stderr/return code."""
    cmd = [sys.executable, script_path] + (args or [])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Execution timed out.", "returncode": -1}


def parse_traceback(stderr: str) -> dict:
    """Extracts error type, message, and line number from a Python traceback."""
    if not stderr.strip():
        return {}
    lines = stderr.strip().splitlines()
    last_line = lines[-1] if lines else ""
    match = re.match(r"(\w+Error|\w+Exception)(:\s*(.*))?", last_line)
    error_type = match.group(1) if match else "UnknownError"
    error_msg = match.group(3) if match and match.group(3) else last_line

    line_no = None
    file_ref = None
    for line in reversed(lines):
        m = re.search(r'File "(.+?)", line (\d+)', line)
        if m:
            file_ref, line_no = m.group(1), m.group(2)
            break

    return {
        "error_type": error_type,
        "error_message": error_msg,
        "file": file_ref,
        "line": line_no,
        "raw_traceback": stderr
    }


def explain_locally(parsed: dict) -> str:
    error_type = parsed.get("error_type", "UnknownError")
    hint = COMMON_ERRORS.get(error_type, "This is a less common error — read the traceback closely for context.")
    loc = f" at line {parsed['line']} in {parsed['file']}" if parsed.get("line") else ""
    return f"{error_type}{loc}: {parsed.get('error_message', '')}\nLikely cause: {hint}"


def explain_with_ollama(source_code: str, parsed: dict) -> str:
    """Free, local, no API key. Requires Ollama installed and running
    (https://ollama.com/download) with a model pulled, e.g.:
        ollama pull llama3.1
    """
    prompt = f"""A Python script failed with this traceback:

{parsed['raw_traceback']}

Here is the source code:

{source_code}

In 3-4 concise sentences: explain the root cause and the exact fix. No preamble."""

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=60
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except requests.RequestException as e:
        print(f"[code_analyzer] Ollama call failed: {e}")
        return None


def explain_with_claude(source_code: str, parsed: dict) -> str:
    """Send the code + error to Claude for a deeper explanation. Requires
    ANTHROPIC_API_KEY in environment."""
    if not _HAS_ANTHROPIC or not os.environ.get("ANTHROPIC_API_KEY"):
        return explain_locally(parsed)

    client = anthropic.Anthropic()
    prompt = f"""A Python script failed with this traceback:

{parsed['raw_traceback']}

Here is the source code:

{source_code}

In 3-4 concise sentences: explain the root cause and the exact fix. No preamble."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        return f"(Claude analysis unavailable: {e})\n\n" + explain_locally(parsed)


def analyze(script_path: str, use_claude=True) -> str:
    result = run_and_capture(script_path)
    if result["returncode"] == 0:
        return "Script ran cleanly — no errors detected."

    parsed = parse_traceback(result["stderr"])
    if not parsed:
        return f"Script exited with code {result['returncode']} but produced no traceback.\n{result['stderr']}"

    if use_claude:
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception:
            source = ""

        # Tier 1: free local Ollama, if running
        if _ollama_available():
            result = explain_with_ollama(source, parsed)
            if result:
                return result

        # Tier 2: Claude, if an API key is configured
        if _HAS_ANTHROPIC and os.environ.get("ANTHROPIC_API_KEY"):
            return explain_with_claude(source, parsed)

        # Tier 3: local heuristic, always available
        return explain_locally(parsed)
    else:
        return explain_locally(parsed)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python code_analyzer.py <script_to_check.py>")
        sys.exit(1)
    print(analyze(sys.argv[1]))
