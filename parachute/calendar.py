from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .models import SafetyLevel, WeatherAssessment


class DuplicateAppointmentError(ValueError):
    """La combinación de cliente y fecha ya está reservada."""


@dataclass(frozen=True)
class Appointment:
    id: int
    customer: str
    date: date
    condition: SafetyLevel


class AppointmentRepository:
    def __init__(self, path: str | Path = "appointments.sqlite3") -> None:
        self.path = str(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute(
            """CREATE TABLE IF NOT EXISTS appointments (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   customer TEXT NOT NULL,
                   appointment_date TEXT NOT NULL,
                   condition TEXT NOT NULL,
                   weather_summary TEXT NOT NULL,
                   created_at TEXT NOT NULL,
                   UNIQUE(customer, appointment_date)
               )"""
        )
        return connection

    def create(
        self, customer: str, requested: date, assessment: WeatherAssessment
    ) -> Appointment:
        if not assessment.can_schedule:
            raise ValueError("Una condición no segura nunca se puede calendarizar.")
        try:
            with closing(self._connect()) as connection:
                with connection:
                    cursor = connection.execute(
                        """INSERT INTO appointments
                           (customer, appointment_date, condition, weather_summary, created_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            customer.strip() or "Cliente",
                            requested.isoformat(),
                            assessment.level.value,
                            assessment.summary(),
                            datetime.now().isoformat(timespec="seconds"),
                        ),
                    )
        except sqlite3.IntegrityError as exc:
            raise DuplicateAppointmentError(
                f"Ya existe una cita para {customer.strip() or 'Cliente'} "
                f"el {requested.isoformat()}."
            ) from exc
        return Appointment(cursor.lastrowid, customer, requested, assessment.level)
