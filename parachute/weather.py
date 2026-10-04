from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from .models import WeatherSnapshot


LATITUDE = 14.013722
LONGITUDE = -90.771611
MAX_FORECAST_DAYS = 16
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
DAILY_FIELDS = (
    "temperature_2m_max",
    "precipitation_sum",
    "cloud_cover_mean",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
)


def guatemala_today() -> date:
    return datetime.now(ZoneInfo("America/Guatemala")).date()


class ForecastDateError(ValueError):
    """La fecha solicitada no pertenece a la ventana disponible."""


class WeatherService:
    def __init__(
        self,
        opener: Callable[..., Any] = urlopen,
        today_provider: Callable[[], date] = guatemala_today,
    ) -> None:
        self._opener = opener
        self._today = today_provider

    def validate_date(self, requested: date) -> None:
        today = self._today()
        last_day = today + timedelta(days=MAX_FORECAST_DAYS - 1)
        if requested < today:
            raise ForecastDateError("No se puede calendarizar una cita en el pasado.")
        if requested > last_day:
            raise ForecastDateError(
                "Open-Meteo solo permite consultar 16 días, del "
                f"{today.isoformat()} al {last_day.isoformat()}."
            )

    def forecast(self, requested: date) -> WeatherSnapshot:
        self.validate_date(requested)
        query = urlencode(
            {
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "start_date": requested.isoformat(),
                "end_date": requested.isoformat(),
                "daily": ",".join(DAILY_FIELDS),
                "timezone": "America/Guatemala",
                "wind_speed_unit": "kmh",
                "temperature_unit": "celsius",
                "precipitation_unit": "mm",
            }
        )
        with self._opener(f"{OPEN_METEO_URL}?{query}", timeout=15) as response:
            payload = json.load(response)
        return self._parse(payload, requested)

    @staticmethod
    def _parse(payload: dict[str, Any], requested: date) -> WeatherSnapshot:
        daily = payload.get("daily") or {}
        try:
            index = daily["time"].index(requested.isoformat())
            return WeatherSnapshot(
                date=requested,
                temperature_2m=float(daily["temperature_2m_max"][index]),
                precipitation=float(daily["precipitation_sum"][index]),
                cloud_cover=float(daily["cloud_cover_mean"][index]),
                wind_speed_10m=float(daily["wind_speed_10m_max"][index]),
                wind_gust_10m=float(daily["wind_gusts_10m_max"][index]),
            )
        except (KeyError, ValueError, IndexError, TypeError) as exc:
            raise RuntimeError("Open-Meteo devolvió una respuesta incompleta.") from exc
