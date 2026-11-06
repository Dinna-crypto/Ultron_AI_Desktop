"""
event_log.py
A tiny local JSON event log. Ultron records things here (sentry alerts,
missed/unrecognized voice commands) as they happen. On the next boot,
main.py reads back everything logged since the last boot and reports
it out loud, so "what happened while I was off" actually works.
"""

import os
import json
import datetime

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ultron_events.json")
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ultron_state.json")


def _load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def log_event(kind: str, message: str):
    """Append an event. kind: 'sentry', 'missed_command', etc."""
    events = _load(LOG_PATH, [])
    events.append({
        "kind": kind,
        "message": message,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds")
    })
    # Keep the log from growing forever
    events = events[-500:]
    _save(LOG_PATH, events)


def get_events_since_last_boot() -> list:
    """Returns events logged after the last recorded boot time."""
    state = _load(STATE_PATH, {})
    last_boot = state.get("last_boot")
    events = _load(LOG_PATH, [])
    if not last_boot:
        return []
    return [e for e in events if e["timestamp"] > last_boot]


def mark_boot():
    """Call this once at the start of each run to reset the 'since last
    boot' window for next time."""
    state = _load(STATE_PATH, {})
    state["last_boot"] = datetime.datetime.now().isoformat(timespec="seconds")
    _save(STATE_PATH, state)


def get_recent_command_patterns(limit=15) -> list:
    """Returns the raw text of the most recent commands that fell
    through to the AI agent (i.e. didn't match a fast keyword command)
    — used to give the agent a feel for this specific user's natural
    phrasing habits, refreshed each time Ultron starts up."""
    events = _load(LOG_PATH, [])
    missed = [e["message"] for e in events if e["kind"] == "missed_command"]
    return missed[-limit:]


def summarize_events(events: list) -> str:
    """Turns a list of events into a short spoken summary."""
    if not events:
        return "No events since my last run."

    sentry_events = [e for e in events if e["kind"] == "sentry"]
    missed = [e for e in events if e["kind"] == "missed_command"]

    parts = []
    if sentry_events:
        parts.append(f"{len(sentry_events)} sentry alert{'s' if len(sentry_events) != 1 else ''}")
    if missed:
        parts.append(f"{len(missed)} command{'s' if len(missed) != 1 else ''} I didn't understand")

    if not parts:
        return f"{len(events)} event{'s' if len(events) != 1 else ''} logged since my last run."

    return "Since my last run: " + ", and ".join(parts) + "."