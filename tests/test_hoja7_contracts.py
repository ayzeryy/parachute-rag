import os
import unittest
from datetime import date
from unittest.mock import patch

from pydantic import ValidationError

import config
from parachute.calendar import Appointment
from parachute.models import SafetyLevel, WeatherSnapshot
from parachute.safety import assess_weather
from parachute.tool_contracts import (
    AppointmentData,
    CreateAppointmentRequest,
    SafetyData,
    WeatherData,
)


class ConfigurationTests(unittest.TestCase):
    def test_protocol_defaults_are_loopback_urls(self):
        names = (
            "MCP_HOST",
            "MCP_PORT",
            "MCP_SERVER_URL",
            "A2A_HOST",
            "A2A_PORT",
            "A2A_SERVER_URL",
        )
        with patch.dict(os.environ, {}, clear=False):
            for name in names:
                os.environ.pop(name, None)
            self.assertEqual(config.mcp_server_url(), "http://127.0.0.1:8001/mcp")
            self.assertEqual(config.a2a_server_url(), "http://127.0.0.1:8000")

    def test_ports_and_log_level_are_validated(self):
        with patch.dict(os.environ, {"MCP_PORT": "0"}):
            with self.assertRaises(ValueError):
                config.mcp_port()
        with patch.dict(os.environ, {"LOG_LEVEL": "verbose"}):
            with self.assertRaises(ValueError):
                config.log_level()


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = WeatherSnapshot(
            date=date(2026, 10, 20),
            temperature_2m=25,
            precipitation=0,
            cloud_cover=40,
            wind_speed_10m=12,
            wind_gust_10m=20,
        )

    def test_weather_contract_round_trips_domain_model_and_iso_date(self):
        contract = WeatherData.from_domain(self.snapshot)
        self.assertEqual(contract.to_domain(), self.snapshot)
        self.assertEqual(
            contract.model_dump(mode="json")["requested_date"], "2026-10-20"
        )

    def test_safety_contract_is_derived_from_existing_domain_rules(self):
        assessment = assess_weather(self.snapshot)
        contract = SafetyData.from_domain(assessment)
        self.assertEqual(contract.level, SafetyLevel.MARGINAL)
        self.assertTrue(contract.can_schedule)
        self.assertFalse(contract.requires_experienced_tandem)

    def test_create_request_rejects_fabricated_approval_or_weather(self):
        values = {
            "customer": "Ana",
            "requested_date": "2026-10-20",
            "experienced_tandem": False,
        }
        request = CreateAppointmentRequest.model_validate(values)
        self.assertEqual(request.customer, "Ana")
        for injected in (
            {"approved": True},
            {"wind_speed_kmh": 10},
            {"assessment": {"level": "ideal"}},
        ):
            with self.subTest(injected=injected), self.assertRaises(ValidationError):
                CreateAppointmentRequest.model_validate(values | injected)

    def test_appointment_contract_serializes_domain_model(self):
        appointment = Appointment(
            id=7,
            customer="Ana",
            date=date(2026, 10, 20),
            condition=SafetyLevel.IDEAL,
        )
        serialized = AppointmentData.from_domain(appointment).model_dump(mode="json")
        self.assertEqual(serialized["appointment_id"], 7)
        self.assertEqual(serialized["requested_date"], "2026-10-20")
        self.assertEqual(serialized["condition"], "ideal")


if __name__ == "__main__":
    unittest.main()
