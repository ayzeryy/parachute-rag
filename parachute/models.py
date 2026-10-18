from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class SafetyLevel(str, Enum):
    IDEAL = "ideal"
    MARGINAL = "marginal"
    PROHIBITED = "no_seguro"


@dataclass(frozen=True)
class WeatherSnapshot:
    date: date
    temperature_2m: float
    precipitation: float
    cloud_cover: float
    wind_speed_10m: float
    wind_gust_10m: float


@dataclass(frozen=True)
class WeatherAssessment:
    level: SafetyLevel
    reasons: tuple[str, ...]
    snapshot: WeatherSnapshot

    @property
    def can_schedule(self) -> bool:
        return self.level is not SafetyLevel.PROHIBITED

    @property
    def requires_experienced_tandem(self) -> bool:
        speed = self.snapshot.wind_speed_10m
        return 20 <= speed <= 28

    def summary(self) -> str:
        weather = self.snapshot
        details = (
            f"viento {weather.wind_speed_10m:.1f} km/h, "
            f"ráfagas {weather.wind_gust_10m:.1f} km/h, "
            f"precipitación {weather.precipitation:.1f} mm, "
            f"nubes {weather.cloud_cover:.0f}%, "
            f"temperatura {weather.temperature_2m:.1f} °C"
        )
        return f"Condición {self.level.value.upper()}: {details}. {'; '.join(self.reasons)}"
