"""
calendar_integration.py
Watches your Google Calendar and fires an alert a few minutes before
each meeting starts.

SETUP (one-time, you need to do this yourself — it requires your own
Google account, I can't do this part for you):

1. Go to https://console.cloud.google.com/ and create a project (or
   use an existing one).
2. APIs & Services -> Enable APIs -> search "Google Calendar API" -> Enable.
   (If you also want the Gmail tool, also enable "Gmail API" here.)
3. APIs & Services -> OAuth consent screen -> fill in App name, your
   email as support/developer contact, add yourself under Test Users.
4. APIs & Services -> Credentials -> Create Credentials -> OAuth client ID.
   - Application type: Desktop app
5. Download the resulting JSON and save it as `credentials.json` right
   here in the `ultron/` project folder.
6. First time you run main.py, a browser window will pop up asking you
   to log in and grant access. After that, a `token.json` is cached
   here so you won't be asked again (until the token expires).

If `credentials.json` isn't present, calendar features are silently
skipped — everything else in Ultron still works fine without it.
"""

import datetime
import threading
import time

import google_services


def is_configured() -> bool:
    return google_services.is_configured()


def get_upcoming_events(max_results=10):
    """Returns upcoming calendar events as a list of dicts with
    'summary', 'start' (datetime), and 'id'."""
    if not is_configured():
        return []
    try:
        service = google_services.get_calendar_service()
        now = datetime.datetime.utcnow().isoformat() + "Z"
        result = service.events().list(
            calendarId="primary", timeMin=now, maxResults=max_results,
            singleEvents=True, orderBy="startTime"
        ).execute()
        events = []
        for item in result.get("items", []):
            # Only timed events have "dateTime" (with a timezone offset).
            # All-day events only have "date" (just YYYY-MM-DD, no
            # timezone) — those can't be meaningfully compared against
            # an offset-aware "now" for a "starts in N minutes" warning,
            # so they're skipped here rather than crashing the watcher.
            start_raw = item["start"].get("dateTime")
            if not start_raw:
                continue
            try:
                start_dt = datetime.datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            events.append({
                "id": item["id"],
                "summary": item.get("summary", "Untitled event"),
                "start": start_dt
            })
        return events
    except Exception as e:
        print(f"[calendar_integration] failed to fetch events: {e}")
        return []


def get_upcoming_summary(max_results=5) -> str:
    """Short spoken summary of upcoming events, for the agent tool."""
    events = get_upcoming_events(max_results=max_results)
    if not events:
        return "No upcoming events found, or calendar isn't configured."
    parts = []
    for ev in events:
        when = ev["start"].strftime("%a %I:%M %p")
        parts.append(f"{ev['summary']} at {when}")
    return "Upcoming: " + "; ".join(parts) + "."


class MeetingWatcher:
    """Polls Google Calendar every 60 seconds and fires on_meeting_soon
    exactly once per event, `warn_minutes` before it starts."""
    def __init__(self, on_meeting_soon, warn_minutes=10, poll_interval=60):
        self.on_meeting_soon = on_meeting_soon
        self.warn_minutes = warn_minutes
        self.poll_interval = poll_interval
        self._running = False
        self._warned_ids = set()

    def run(self):
        if not is_configured():
            print("[calendar_integration] no credentials.json found, meeting watcher not started")
            return
        self._running = True
        while self._running:
            try:
                events = get_upcoming_events()
                now = datetime.datetime.now(datetime.timezone.utc)
                for ev in events:
                    if ev["id"] in self._warned_ids:
                        continue
                    minutes_until = (ev["start"] - now).total_seconds() / 60
                    if 0 <= minutes_until <= self.warn_minutes:
                        self._warned_ids.add(ev["id"])
                        self.on_meeting_soon(ev)
            except Exception as e:
                print(f"[calendar_integration] watcher error: {e}")
            time.sleep(self.poll_interval)

    def stop(self):
        self._running = False


def start_watcher_thread(on_meeting_soon, warn_minutes=10):
    """Convenience: starts MeetingWatcher on a daemon thread. Returns
    the watcher (call .stop() on it to end), or None if not configured."""
    if not is_configured():
        return None
    watcher = MeetingWatcher(on_meeting_soon, warn_minutes=warn_minutes)
    threading.Thread(target=watcher.run, daemon=True).start()
    return watcher