"""
weather_tool.py
Real weather data via OpenWeatherMap (free tier: 1000 calls/day).

Setup: sign up at https://openweathermap.org/api, grab an API key,
set it as an environment variable:
    setx OPENWEATHER_API_KEY "your-key-here"
(then open a fresh terminal)
"""

import os
import requests

OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")


def get_weather(city: str) -> str:
    if not OPENWEATHER_API_KEY:
        return ("Weather isn't configured. Set the OPENWEATHER_API_KEY "
                "environment variable (free tier at openweathermap.org).")
    try:
        resp = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": OPENWEATHER_API_KEY, "units": "metric"},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        desc = data["weather"][0]["description"]
        temp = data["main"]["temp"]
        feels = data["main"]["feels_like"]
        return f"{city}: {desc}, {temp} degrees Celsius, feels like {feels}."
    except Exception as e:
        return f"Couldn't get weather for {city}: {e}"