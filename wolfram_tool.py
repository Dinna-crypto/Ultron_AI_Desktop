"""
wolfram_tool.py
Real math, unit conversion, and factual queries via Wolfram Alpha's
simple "short answer" API (free tier: 2000 calls/month).

Setup: sign up at https://products.wolframalpha.com/api, grab an
"AppID", set it as an environment variable:
    setx WOLFRAM_APP_ID "your-app-id-here"
(then open a fresh terminal)
"""

import os
import requests

WOLFRAM_APP_ID = os.environ.get("WOLFRAM_APP_ID", "")


def ask_wolfram(query: str) -> str:
    if not WOLFRAM_APP_ID:
        return ("Wolfram Alpha isn't configured. Set the WOLFRAM_APP_ID "
                "environment variable (free tier at wolframalpha.com/api).")
    try:
        resp = requests.get(
            "https://api.wolframalpha.com/v1/result",
            params={"appid": WOLFRAM_APP_ID, "i": query},
            timeout=10
        )
        if resp.status_code == 501:
            return f"Wolfram Alpha couldn't compute an answer for '{query}'."
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        return f"Wolfram Alpha query failed: {e}"