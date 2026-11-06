"""
gmail_integration.py
Read/summarize unread Gmail messages. Uses the same Google OAuth setup
as calendar_integration.py (shared credentials.json / token.json via
google_services.py) — if you've already set up the calendar, Gmail
just needs "Gmail API" enabled in the same Google Cloud project, then
re-authorize once (to grant the added Gmail scope — delete token.json
and restart if it complains about insufficient scope).
"""

import google_services


def get_unread_summary(max_results=5) -> str:
    if not google_services.is_configured():
        return "Gmail isn't configured. Set up credentials.json first (see calendar_integration.py)."
    try:
        service = google_services.get_gmail_service()
        result = service.users().messages().list(
            userId="me", labelIds=["INBOX", "UNREAD"], maxResults=max_results
        ).execute()
        messages = result.get("messages", [])
        if not messages:
            return "No unread emails."

        summaries = []
        for m in messages:
            msg = service.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "Subject"]
            ).execute()
            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            sender = headers.get("From", "Unknown sender")
            subject = headers.get("Subject", "(no subject)")
            summaries.append(f"From {sender}: {subject}")

        total = result.get("resultSizeEstimate", len(messages))
        listed = "; ".join(summaries)
        return f"You have {total} unread email{'s' if total != 1 else ''}. Most recent: {listed}."
    except Exception as e:
        print(f"[gmail_integration] failed: {e}")
        return f"Couldn't check Gmail: {e}"