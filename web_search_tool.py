"""
web_search_tool.py
Real web search for the LangGraph agent, via Tavily — built specifically
for LLM agents, has a free tier (1000 searches/month).

Setup: sign up at https://tavily.com, grab an API key, set it as an
environment variable:
    setx TAVILY_API_KEY "your-key-here"
(then open a fresh terminal — see the note in README about setx needing
a new session to take effect)
"""

import os
import requests

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")


def search(query: str, max_results=4) -> str:
    if not TAVILY_API_KEY:
        return ("Web search isn't configured. Set the TAVILY_API_KEY "
                "environment variable (free tier at tavily.com).")
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": TAVILY_API_KEY, "query": query, "max_results": max_results},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return f"No results found for '{query}'."
        lines = [f"{r['title']}: {r['content'][:150]}" for r in results[:max_results]]
        return " | ".join(lines)
    except Exception as e:
        return f"Search failed: {e}"