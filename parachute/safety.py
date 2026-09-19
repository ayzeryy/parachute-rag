from __future__ import annotations

from .models import SafetyLevel, WeatherAssessment, WeatherSnapshot


def assess_weather(snapshot: WeatherSnapshot) -> WeatherAssessment:
    prohibited: list[str] = []
    marginal: list[str] = []

    if snapshot.wind_speed_10m > 28:
        prohibited.append("viento en superficie mayor a 28 km/h")
    elif snapshot.wind_speed_10m >= 20:
        marginal.append("viento de 20 a 28 km/h: solo tándem experimentado")
    if snapshot.wind_gust_10m > 35:
        prohibited.append("ráfagas mayores a 35 km/h")
    if snapshot.precipitation > 0:
        prohibited.append("hay precipitación")
    if snapshot.cloud_cover > 75:
        prohibited.append("cobertura de nubes mayor a 75%")
    elif snapshot.cloud_cover >= 30:
        marginal.append("cobertura de nubes entre 30% y 75%")

    if prohibited:
        return WeatherAssessment(SafetyLevel.PROHIBITED, tuple(prohibited), snapshot)
    if marginal:
        return WeatherAssessment(SafetyLevel.MARGINAL, tuple(marginal), snapshot)
    return WeatherAssessment(
        SafetyLevel.IDEAL,
        ("todos los valores están dentro del rango ideal",),
        snapshot,
    )
