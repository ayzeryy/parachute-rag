from __future__ import annotations

from .models import SafetyLevel, WeatherAssessment, WeatherSnapshot


MARGINAL_WIND_MIN_KMH = 20
MAX_SURFACE_WIND_KMH = 28
MAX_WIND_GUST_KMH = 35
MARGINAL_CLOUD_COVER_MIN_PERCENT = 30
MAX_CLOUD_COVER_PERCENT = 75


def assess_weather(snapshot: WeatherSnapshot) -> WeatherAssessment:
    prohibited: list[str] = []
    marginal: list[str] = []

    if snapshot.wind_speed_10m > MAX_SURFACE_WIND_KMH:
        prohibited.append(
            f"viento en superficie mayor a {MAX_SURFACE_WIND_KMH} km/h"
        )
    elif snapshot.wind_speed_10m >= MARGINAL_WIND_MIN_KMH:
        marginal.append(
            f"viento de {MARGINAL_WIND_MIN_KMH} a {MAX_SURFACE_WIND_KMH} "
            "km/h: solo tándem experimentado"
        )
    if snapshot.wind_gust_10m > MAX_WIND_GUST_KMH:
        prohibited.append(f"ráfagas mayores a {MAX_WIND_GUST_KMH} km/h")
    if snapshot.precipitation > 0:
        prohibited.append("hay precipitación")
    if snapshot.cloud_cover > MAX_CLOUD_COVER_PERCENT:
        prohibited.append(
            f"cobertura de nubes mayor a {MAX_CLOUD_COVER_PERCENT}%"
        )
    elif snapshot.cloud_cover >= MARGINAL_CLOUD_COVER_MIN_PERCENT:
        marginal.append(
            "cobertura de nubes entre "
            f"{MARGINAL_CLOUD_COVER_MIN_PERCENT}% y {MAX_CLOUD_COVER_PERCENT}%"
        )

    if prohibited:
        return WeatherAssessment(SafetyLevel.PROHIBITED, tuple(prohibited), snapshot)
    if marginal:
        return WeatherAssessment(SafetyLevel.MARGINAL, tuple(marginal), snapshot)
    return WeatherAssessment(
        SafetyLevel.IDEAL,
        ("todos los valores están dentro del rango ideal",),
        snapshot,
    )


def safety_policy_markdown() -> str:
    """Publica las reglas usando las mismas constantes que la evaluación."""

    return f"""# Políticas meteorológicas de seguridad

- Viento en superficie mayor a {MAX_SURFACE_WIND_KMH} km/h: prohibido.
- Viento entre {MARGINAL_WIND_MIN_KMH} y {MAX_SURFACE_WIND_KMH} km/h, inclusive: marginal y requiere tándem experimentado.
- Ráfagas mayores a {MAX_WIND_GUST_KMH} km/h: prohibido.
- Precipitación mayor a 0 mm: prohibido.
- Cobertura de nubes mayor a {MAX_CLOUD_COVER_PERCENT}%: prohibido.
- Cobertura de nubes entre {MARGINAL_CLOUD_COVER_MIN_PERCENT}% y {MAX_CLOUD_COVER_PERCENT}%, inclusive: marginal; por sí sola no exige tándem experimentado.
- Cualquier condición prohibida prevalece sobre las condiciones marginales.
"""
