"""
plugins/weather_tool.py
------------------------
Returns actual current weather as text (spoken by Eva), instead of opening
a browser search.

Primary source: wttr.in - free, keyless, and auto-detects the user's
location from IP when no city is given. Secondary source: Open-Meteo (also
free, keyless) used only if wttr.in fails for any reason - a network error,
a timeout, or (what actually happened here) wttr.in's own TLS certificate
being expired, which breaks every request to it until they renew it,
completely outside our control. Two independent providers means a single
provider's outage doesn't take the whole feature down.

Open-Meteo's forecast API needs latitude/longitude rather than a city name,
so the fallback path adds one extra lookup first: Open-Meteo's own
geocoding API for a named city, or ip-api.com (free, keyless) to resolve
the caller's approximate location from IP when no city was given - the
same "no location given" behavior wttr.in provides.

A short in-memory cache avoids hitting the network again for the same
location within a few minutes - weather doesn't meaningfully change that
fast, and it removes a real network round-trip from repeated questions.
"""

import time
import threading
import requests
from urllib.parse import quote as url_quote
from plugins.base import BasePlugin

_cache: dict = {}  # location_key -> (timestamp, result_text)
_cache_lock = threading.Lock()
_CACHE_TTL_SECONDS = 600  # 10 minutes

# Open-Meteo's "weather code" -> a short human description. Codes per the
# WMO table Open-Meteo documents; only current-conditions codes are needed
# here (not the extended precipitation-probability set).
_WMO_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    56: "light freezing drizzle", 57: "dense freezing drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    66: "light freezing rain", 67: "heavy freezing rain",
    71: "slight snow fall", 73: "moderate snow fall", 75: "heavy snow fall",
    77: "snow grains",
    80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
}


class WeatherPlugin(BasePlugin):
    name = "get_weather"

    def is_enabled(self, config) -> bool:
        return config.get("permissions", "weather", "enabled", default=False)

    def declaration(self, config):
        from local_types import types
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Gets the current real weather conditions (temperature, feels-like, "
                "condition, humidity, wind) plus today's forecast (high/low and "
                "expected conditions) for a city, or the user's current location "
                "if no city is given. Use this for any weather or forecast question "
                "instead of web_search, since it returns a spoken-ready answer directly."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "location": {
                        "type": "STRING",
                        "description": "City name, e.g. 'Cairo'. Leave empty to use the user's current location."
                    }
                },
            },
        )

    def execute(self, args: dict, config, context: dict) -> str:
        if not self.is_enabled(config):
            return "The weather permission is disabled. Enable it via permissions.weather.enabled in config.yaml."

        location = (args.get("location") or "").strip()
        default_location = config.get("permissions", "weather", "default_location", default="")
        query_location = location or default_location
        cache_key = query_location.lower()

        with _cache_lock:
            cached = _cache.get(cache_key)
        if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

        result, error = self._try_wttr(query_location)
        if result is None:
            result, fallback_error = self._try_open_meteo(query_location)
            if result is None:
                return (
                    f"Could not fetch the weather right now. Primary source failed "
                    f"({error}); backup source also failed ({fallback_error})."
                )

        with _cache_lock:
            _cache[cache_key] = (time.time(), result)
        return result

    # ------------------------------------------------------------- wttr.in ---

    def _try_wttr(self, query_location: str):
        url = f"https://wttr.in/{url_quote(query_location)}?format=j1" if query_location else "https://wttr.in/?format=j1"
        try:
            response = requests.get(url, timeout=8, headers={"User-Agent": "curl"})
            response.raise_for_status()
            data = response.json()

            current = data["current_condition"][0]
            area_name = data.get("nearest_area", [{}])[0].get("areaName", [{}])
            city_name = area_name[0]["value"] if area_name else (query_location or "your location")

            temp_c = current["temp_C"]
            feels_like_c = current["FeelsLikeC"]
            condition = current["weatherDesc"][0]["value"]
            humidity = current["humidity"]
            wind_kmph = current["windspeedKmph"]

            result = (
                f"Current weather in {city_name}: {condition}, {temp_c}°C "
                f"(feels like {feels_like_c}°C), humidity {humidity}%, "
                f"wind {wind_kmph} km/h."
            )

            # wttr.in's j1 format includes a "weather" array of upcoming
            # days - today's entry (index 0) carries the day's high/low and
            # an hourly breakdown, which is enough for a one-line forecast
            # without a second request.
            today_forecast = (data.get("weather") or [None])[0]
            if today_forecast:
                max_c = today_forecast.get("maxtempC")
                min_c = today_forecast.get("mintempC")
                hourly = today_forecast.get("hourly") or []
                # Pick the midday slot (index 4 of 8 three-hourly entries,
                # i.e. ~12:00) as a representative "what the day looks
                # like" description, rather than just repeating "now".
                midday = hourly[len(hourly) // 2] if hourly else None
                forecast_desc = midday["weatherDesc"][0]["value"] if midday else condition
                if max_c and min_c:
                    result += f" Today's forecast: high {max_c}°C, low {min_c}°C, {forecast_desc.lower()}."

            return result, None
        except requests.exceptions.RequestException as e:
            return None, f"wttr.in network issue: {e}"
        except (KeyError, IndexError, ValueError) as e:
            return None, f"wttr.in returned unexpected data: {e}"

    # --------------------------------------------------------- open-meteo ---

    def _resolve_location(self, query_location: str):
        """Returns (latitude, longitude, display_name) or (None, None, None)."""
        if query_location:
            r = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": query_location, "count": 1},
                timeout=8,
            )
            r.raise_for_status()
            results = r.json().get("results") or []
            if not results:
                return None, None, None
            top = results[0]
            return top["latitude"], top["longitude"], top.get("name", query_location)

        # No city given - resolve from the caller's IP instead, same
        # "use my current location" behavior wttr.in provides with no
        # location argument. ip-api.com is free, keyless, HTTP-only.
        r = requests.get("http://ip-api.com/json/", timeout=8)
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "success":
            return None, None, None
        return data["lat"], data["lon"], data.get("city", "your location")

    def _try_open_meteo(self, query_location: str):
        try:
            lat, lon, display_name = self._resolve_location(query_location)
            if lat is None:
                return None, f"could not resolve location '{query_location or '(current location)'}'"

            r = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,weather_code",
                    "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                    "timezone": "auto",
                },
                timeout=8,
            )
            r.raise_for_status()
            payload = r.json()
            current = payload["current"]

            condition = _WMO_CODES.get(current.get("weather_code"), "unknown conditions")
            result = (
                f"Current weather in {display_name}: {condition}, "
                f"{current['temperature_2m']}°C (feels like {current['apparent_temperature']}°C), "
                f"humidity {current['relative_humidity_2m']}%, "
                f"wind {current['wind_speed_10m']} km/h."
            )

            daily = payload.get("daily") or {}
            if daily.get("temperature_2m_max"):
                max_c = daily["temperature_2m_max"][0]
                min_c = daily["temperature_2m_min"][0]
                day_condition = _WMO_CODES.get(daily["weather_code"][0], "unknown conditions")
                result += f" Today's forecast: high {max_c}°C, low {min_c}°C, {day_condition}."

            return result, None
        except requests.exceptions.RequestException as e:
            return None, f"network issue: {e}"
        except (KeyError, IndexError, ValueError) as e:
            return None, f"unexpected data: {e}"


PLUGIN = WeatherPlugin()
