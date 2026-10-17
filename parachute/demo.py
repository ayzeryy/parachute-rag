from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from config import demo_appointments_db, demo_corpus_path

from .calendar import AppointmentRepository
from .models import WeatherSnapshot
from .weather import ForecastDateError, guatemala_today


DEMO_DATABASE_MARKER = "parachute-demo-v1"


class DemoScenario(str, Enum):
    IDEAL = "ideal"
    PROHIBITED = "prohibido"
    MARGINAL_WIND = "viento_marginal"
    MARGINAL_CLOUDS = "nubes_marginales"


@dataclass(frozen=True)
class DemoScenarioDay:
    scenario: DemoScenario
    date: date
    description: str


class DemoCalendar:
    """Calendario meteorológico relativo al día actual de Guatemala."""

    def __init__(
        self,
        today_provider: Callable[[], date] = guatemala_today,
    ) -> None:
        self._today = today_provider

    def days(self) -> tuple[DemoScenarioDay, ...]:
        today = self._today()
        return (
            DemoScenarioDay(
                DemoScenario.IDEAL,
                today + timedelta(days=1),
                "Condiciones ideales; permite reservar.",
            ),
            DemoScenarioDay(
                DemoScenario.PROHIBITED,
                today + timedelta(days=2),
                "Precipitación; impide reservar.",
            ),
            DemoScenarioDay(
                DemoScenario.MARGINAL_WIND,
                today + timedelta(days=3),
                "Viento marginal; requiere tándem experimentado.",
            ),
            DemoScenarioDay(
                DemoScenario.MARGINAL_CLOUDS,
                today + timedelta(days=4),
                "Nubes marginales con viento ideal; no exige experiencia.",
            ),
        )

    def by_date(self, requested: date) -> DemoScenarioDay:
        by_date = {item.date: item for item in self.days()}
        if requested not in by_date:
            valid = ", ".join(day.isoformat() for day in by_date)
            raise ForecastDateError(
                "En MODO DEMO usa una de estas fechas: " + valid + "."
            )
        return by_date[requested]


class DemoWeatherService:
    """Pronóstico determinista; el usuario sólo selecciona una fecha válida."""

    def __init__(self, calendar: DemoCalendar | None = None) -> None:
        self.calendar = calendar or DemoCalendar()

    def forecast(self, requested: date) -> WeatherSnapshot:
        scenario = self.calendar.by_date(requested).scenario
        values = {
            DemoScenario.IDEAL: dict(
                precipitation=0,
                cloud_cover=15,
                wind_speed_10m=12,
                wind_gust_10m=18,
            ),
            DemoScenario.PROHIBITED: dict(
                precipitation=2,
                cloud_cover=20,
                wind_speed_10m=12,
                wind_gust_10m=18,
            ),
            DemoScenario.MARGINAL_WIND: dict(
                precipitation=0,
                cloud_cover=15,
                wind_speed_10m=24,
                wind_gust_10m=30,
            ),
            DemoScenario.MARGINAL_CLOUDS: dict(
                precipitation=0,
                cloud_cover=50,
                wind_speed_10m=12,
                wind_gust_10m=18,
            ),
        }[scenario]
        return WeatherSnapshot(
            date=requested,
            temperature_2m=26,
            **values,
        )


def _normalized_terms(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    ascii_text = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    stopwords = {
        "cual",
        "como",
        "donde",
        "para",
        "porque",
        "puedo",
        "tienen",
        "sobre",
        "esta",
        "este",
        "entre",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", ascii_text)
        if len(token) >= 4 and token not in stopwords
    }


class DemoKnowledgeBase:
    """Búsqueda léxica sobre las fichas reales, sin embeddings ni PostgreSQL."""

    def __init__(self, corpus_path: str | Path) -> None:
        self.corpus_path = Path(corpus_path)
        self._records = self._load_records()

    @classmethod
    def from_env(cls) -> "DemoKnowledgeBase":
        return cls(demo_corpus_path())

    def _load_records(self) -> list[dict[str, Any]]:
        content = self.corpus_path.read_text(encoding="utf-8")
        records: list[dict[str, Any]] = []
        pattern = re.compile(
            r"^ID: (?P<id>[^\r\n]+)\r?\n"
            r"CATEGORÍA: (?P<category>[^\r\n]+)\r?\n"
            r"PREGUNTA: (?P<question>[^\r\n]+)\r?\n"
            r"RESPUESTA: (?P<answer>[^\r\n]+)\r?\n"
            r"METADATA: (?P<metadata>\{[^\r\n]+\})$",
            re.MULTILINE,
        )
        for match in pattern.finditer(content):
            records.append(
                {
                    "id": match.group("id"),
                    "categoria": match.group("category"),
                    "pregunta": match.group("question"),
                    "respuesta": match.group("answer"),
                    "metadata": json.loads(match.group("metadata")),
                }
            )
        if not records:
            raise ValueError(
                f"No se encontraron fichas FAQ en {self.corpus_path}."
            )
        return records

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query_terms = _normalized_terms(query)
        if not query_terms:
            return []
        matches = []
        for record in self._records:
            question_terms = _normalized_terms(record["pregunta"])
            overlap = len(query_terms & question_terms)
            similarity = overlap / len(query_terms)
            if overlap >= 2 and similarity >= 0.5:
                matches.append(record | {"similitud": round(similarity, 4)})
        matches.sort(key=lambda item: (-item["similitud"], item["id"]))
        return matches[: max(1, min(int(limit), 8))]


class DemoAppointmentRepository(AppointmentRepository):
    """SQLite marcada explícitamente para impedir reinicios sobre datos reales."""

    def __init__(self, path: str | Path | None = None) -> None:
        resolved = Path(path) if path is not None else demo_appointments_db()
        super().__init__(resolved)

    def _connect(self) -> sqlite3.Connection:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        connection = super()._connect()
        connection.execute(
            """CREATE TABLE IF NOT EXISTS demo_metadata (
                   key TEXT PRIMARY KEY,
                   value TEXT NOT NULL
               )"""
        )
        connection.execute(
            "INSERT OR IGNORE INTO demo_metadata (key, value) VALUES (?, ?)",
            ("database_kind", DEMO_DATABASE_MARKER),
        )
        connection.commit()
        return connection


def verify_demo_database(connection: sqlite3.Connection) -> None:
    try:
        row = connection.execute(
            "SELECT value FROM demo_metadata WHERE key = ?",
            ("database_kind",),
        ).fetchone()
    except sqlite3.Error as exc:
        raise ValueError("La base no contiene la marca de MODO DEMO.") from exc
    if row is None or row[0] != DEMO_DATABASE_MARKER:
        raise ValueError("La base no contiene la marca de MODO DEMO.")


def list_demo_appointments(path: Path | None = None) -> list[tuple[Any, ...]]:
    resolved = path or demo_appointments_db()
    if not resolved.exists():
        return []
    with closing(sqlite3.connect(resolved)) as connection:
        verify_demo_database(connection)
        return connection.execute(
            "SELECT id, customer, appointment_date, condition, created_at "
            "FROM appointments ORDER BY id"
        ).fetchall()


def reset_demo_appointments(path: Path | None = None) -> int:
    resolved = path or demo_appointments_db()
    if not resolved.exists():
        return 0
    with closing(sqlite3.connect(resolved)) as connection:
        verify_demo_database(connection)
        with connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM appointments"
            ).fetchone()[0]
            connection.execute("DELETE FROM appointments")
            connection.execute(
                "DELETE FROM sqlite_sequence WHERE name = 'appointments'"
            )
        return int(count)
