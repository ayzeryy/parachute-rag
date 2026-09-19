import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from parachute.agents import RequestContext
from parachute.calendar import AppointmentRepository
from parachute.centralized import CentralSupervisor
from parachute.decentralized import PeerNetwork
from parachute.factory import build_specialists
from parachute.hierarchical import ExecutiveManager
from parachute.models import SafetyLevel, WeatherSnapshot
from parachute.safety import assess_weather
from parachute.weather import ForecastDateError, WeatherService


TODAY = date(2026, 9, 18)


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def payload_for(requested, *, wind=12, gust=20, rain=0, clouds=15, temp=26):
    return {
        "daily": {
            "time": [requested.isoformat()],
            "temperature_2m_max": [temp],
            "precipitation_sum": [rain],
            "cloud_cover_mean": [clouds],
            "wind_speed_10m_max": [wind],
            "wind_gusts_10m_max": [gust],
        }
    }


def fake_service(requested, **values):
    def opener(url, timeout):
        assert "14.013722" in url
        assert "-90.771611" in url
        assert timeout == 15
        return Response(json.dumps(payload_for(requested, **values)).encode())

    return WeatherService(opener=opener, today_provider=lambda: TODAY)


class WeatherTests(unittest.TestCase):
    def test_reads_all_required_daily_values(self):
        requested = TODAY + timedelta(days=3)
        weather = fake_service(requested).forecast(requested)
        self.assertEqual(weather.date, requested)
        self.assertEqual(weather.temperature_2m, 26)
        self.assertEqual(weather.precipitation, 0)
        self.assertEqual(weather.cloud_cover, 15)
        self.assertEqual(weather.wind_speed_10m, 12)
        self.assertEqual(weather.wind_gust_10m, 20)

    def test_rejects_day_after_16_day_window(self):
        service = fake_service(TODAY)
        with self.assertRaises(ForecastDateError):
            service.validate_date(TODAY + timedelta(days=16))


class SafetyTests(unittest.TestCase):
    def snapshot(self, **changes):
        values = dict(
            date=TODAY,
            temperature_2m=25,
            precipitation=0,
            cloud_cover=10,
            wind_speed_10m=10,
            wind_gust_10m=20,
        )
        values.update(changes)
        return WeatherSnapshot(**values)

    def test_ideal_conditions(self):
        self.assertEqual(assess_weather(self.snapshot()).level, SafetyLevel.IDEAL)

    def test_surface_wind_is_marginal_at_20_and_prohibited_above_28(self):
        marginal = assess_weather(self.snapshot(wind_speed_10m=20))
        prohibited = assess_weather(self.snapshot(wind_speed_10m=28.1))
        self.assertEqual(marginal.level, SafetyLevel.MARGINAL)
        self.assertTrue(marginal.requires_experienced_tandem)
        self.assertEqual(prohibited.level, SafetyLevel.PROHIBITED)

    def test_any_rain_or_high_gust_or_high_cloud_is_prohibited(self):
        for values in (
            {"precipitation": 0.1},
            {"wind_gust_10m": 35.1},
            {"cloud_cover": 75.1},
        ):
            with self.subTest(values=values):
                self.assertEqual(
                    assess_weather(self.snapshot(**values)).level,
                    SafetyLevel.PROHIBITED,
                )

    def test_marginal_clouds_do_not_require_experienced_tandem(self):
        assessment = assess_weather(self.snapshot(cloud_cover=50))
        self.assertEqual(assessment.level, SafetyLevel.MARGINAL)
        self.assertFalse(assessment.requires_experienced_tandem)


class ArchitectureTests(unittest.TestCase):
    def test_all_architectures_solve_same_ideal_booking(self):
        requested = TODAY + timedelta(days=2)
        for architecture in (CentralSupervisor, ExecutiveManager, PeerNetwork):
            with self.subTest(architecture=architecture.__name__), tempfile.TemporaryDirectory() as tmp:
                db = Path(tmp) / "appointments.sqlite3"
                specialists = build_specialists(
                    database_path=db,
                    enable_rag=False,
                    weather_service=fake_service(requested),
                )
                answer = architecture(specialists).run(
                    RequestContext(f"Quiero reservar cita el {requested.isoformat()}", "Ana")
                )
                self.assertIn("Cita #1 creada", answer)
                with closing(sqlite3.connect(db)) as connection:
                    count = connection.execute(
                        "SELECT COUNT(*) FROM appointments"
                    ).fetchone()[0]
                self.assertEqual(count, 1)

    def test_marginal_wind_requires_experienced_tandem(self):
        requested = TODAY + timedelta(days=1)
        with tempfile.TemporaryDirectory() as tmp:
            specialists = build_specialists(
                database_path=Path(tmp) / "appointments.sqlite3",
                enable_rag=False,
                weather_service=fake_service(requested, wind=24),
            )
            system = CentralSupervisor(specialists)
            denied = system.run(RequestContext(f"cita {requested.isoformat()}"))
            self.assertIn("requiere un tándem experimentado", denied)


if __name__ == "__main__":
    unittest.main()
