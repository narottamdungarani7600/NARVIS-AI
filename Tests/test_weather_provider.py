"""Tests for the live Open-Meteo-backed weather provider."""

from __future__ import annotations

import unittest
from typing import Any

from Internet import OpenMeteoWeatherProvider


class _QueuedHttpClient:
    """HTTP client stub that returns queued responses without live network access."""

    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, float | None]] = []

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: float | None = None) -> dict[str, Any]:
        self.calls.append((url, timeout))
        if not self.responses:
            raise AssertionError("Unexpected GET request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post(
        self,
        url: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        raise AssertionError("POST should not be used by the weather provider")


class OpenMeteoWeatherProviderTests(unittest.TestCase):
    """Verify the Open-Meteo provider normalizes weather responses safely."""

    def test_provider_normalizes_geocoding_and_current_weather(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "json": {
                        "results": [
                            {
                                "name": "Ahmedabad",
                                "admin1": "Gujarat",
                                "country": "India",
                                "country_code": "IN",
                                "latitude": 23.02579,
                                "longitude": 72.58727,
                                "timezone": "Asia/Kolkata",
                            }
                        ]
                    },
                },
                {
                    "status": 200,
                    "json": {
                        "timezone": "Asia/Kolkata",
                        "current": {
                            "temperature_2m": 32.4,
                            "weather_code": 3,
                            "time": "2026-07-07T12:00",
                        },
                    },
                },
            ]
        )
        provider = OpenMeteoWeatherProvider(http_client=http_client, timeout_seconds=4.5)

        report = provider.fetch("  Ahmedabad  ")

        self.assertEqual(report.location, "Ahmedabad, Gujarat, India")
        self.assertEqual(report.condition, "overcast")
        self.assertEqual(report.temperature_c, 32.4)
        self.assertEqual(report.metadata["provider"], "open-meteo")
        self.assertEqual(report.metadata["status"], "ok")
        self.assertEqual(report.metadata["requested_location"], "Ahmedabad")
        self.assertEqual(report.metadata["resolved_location"], "Ahmedabad, Gujarat, India")
        self.assertEqual(report.metadata["country_code"], "IN")
        self.assertEqual(report.metadata["timezone"], "Asia/Kolkata")
        self.assertEqual(report.metadata["weather_code"], 3)
        self.assertEqual(report.metadata["observed_at"], "2026-07-07T12:00")
        self.assertEqual(len(http_client.calls), 2)
        self.assertIn("name=Ahmedabad", http_client.calls[0][0])
        self.assertIn("count=5", http_client.calls[0][0])
        self.assertIn("current=temperature_2m%2Cweather_code", http_client.calls[1][0])
        self.assertIn("temperature_unit=celsius", http_client.calls[1][0])
        self.assertEqual(http_client.calls[0][1], 4.5)
        self.assertEqual(http_client.calls[1][1], 4.5)

    def test_provider_returns_location_not_found_when_geocoding_has_no_results(self) -> None:
        http_client = _QueuedHttpClient([{"status": 200, "json": {"results": []}}])
        provider = OpenMeteoWeatherProvider(http_client=http_client)

        report = provider.fetch("Atlantis")

        self.assertEqual(report.location, "Atlantis")
        self.assertEqual(report.condition, "location not found")
        self.assertIsNone(report.temperature_c)
        self.assertEqual(report.metadata["status"], "location_not_found")
        self.assertEqual(len(http_client.calls), 1)

    def test_provider_returns_unavailable_on_geocoding_http_failure(self) -> None:
        http_client = _QueuedHttpClient([{"status": 503, "error": "service unavailable"}])
        provider = OpenMeteoWeatherProvider(http_client=http_client)

        report = provider.fetch("Ahmedabad")

        self.assertEqual(report.location, "Ahmedabad")
        self.assertEqual(report.condition, "unavailable")
        self.assertEqual(report.metadata["status"], "geocoding_unavailable")

    def test_provider_returns_unavailable_on_forecast_http_failure(self) -> None:
        http_client = _QueuedHttpClient(
            [
                {
                    "status": 200,
                    "json": {
                        "results": [
                            {"name": "Ahmedabad", "admin1": "Gujarat", "country": "India", "latitude": 23.02579, "longitude": 72.58727}
                        ]
                    },
                },
                {"status": 504, "error": "gateway timeout"},
            ]
        )
        provider = OpenMeteoWeatherProvider(http_client=http_client)

        report = provider.fetch("Ahmedabad")

        self.assertEqual(report.location, "Ahmedabad, Gujarat, India")
        self.assertEqual(report.condition, "unavailable")
        self.assertEqual(report.metadata["status"], "forecast_unavailable")
        self.assertEqual(report.metadata["resolved_location"], "Ahmedabad, Gujarat, India")

    def test_provider_returns_unavailable_on_malformed_json_response(self) -> None:
        http_client = _QueuedHttpClient([{"status": 200, "text": "not-json"}])
        provider = OpenMeteoWeatherProvider(http_client=http_client)

        report = provider.fetch("Ahmedabad")

        self.assertEqual(report.location, "Ahmedabad")
        self.assertEqual(report.condition, "unavailable")
        self.assertEqual(report.metadata["status"], "geocoding_unavailable")

    def test_provider_returns_unavailable_on_invalid_payload_shape(self) -> None:
        http_client = _QueuedHttpClient([{"status": 200, "json": {"results": {}}}])
        provider = OpenMeteoWeatherProvider(http_client=http_client)

        report = provider.fetch("Ahmedabad")

        self.assertEqual(report.location, "Ahmedabad")
        self.assertEqual(report.condition, "unavailable")
        self.assertEqual(report.metadata["status"], "geocoding_unavailable")

    def test_provider_handles_missing_temperature_or_weather_code_deterministically(self) -> None:
        geocoding_response = {
            "status": 200,
            "json": {
                "results": [
                    {"name": "Ahmedabad", "admin1": "Gujarat", "country": "India", "latitude": 23.02579, "longitude": 72.58727}
                ]
            },
        }

        provider_with_missing_code = OpenMeteoWeatherProvider(
            http_client=_QueuedHttpClient(
                [
                    geocoding_response,
                    {"status": 200, "json": {"current": {"temperature_2m": 29.1}}},
                ]
            )
        )
        provider_with_missing_temp = OpenMeteoWeatherProvider(
            http_client=_QueuedHttpClient(
                [
                    geocoding_response,
                    {"status": 200, "json": {"current": {"weather_code": 95}}},
                ]
            )
        )
        provider_with_both_missing = OpenMeteoWeatherProvider(
            http_client=_QueuedHttpClient(
                [
                    geocoding_response,
                    {"status": 200, "json": {"current": {}}},
                ]
            )
        )

        missing_code_report = provider_with_missing_code.fetch("Ahmedabad")
        missing_temp_report = provider_with_missing_temp.fetch("Ahmedabad")
        missing_both_report = provider_with_both_missing.fetch("Ahmedabad")

        self.assertEqual(missing_code_report.condition, "unknown")
        self.assertEqual(missing_code_report.temperature_c, 29.1)
        self.assertEqual(missing_code_report.metadata["status"], "ok")
        self.assertEqual(missing_temp_report.condition, "thunderstorm")
        self.assertIsNone(missing_temp_report.temperature_c)
        self.assertEqual(missing_temp_report.metadata["status"], "ok")
        self.assertEqual(missing_both_report.condition, "unavailable")
        self.assertEqual(missing_both_report.metadata["status"], "invalid_current_weather")

    def test_provider_maps_weather_codes_deterministically(self) -> None:
        provider = OpenMeteoWeatherProvider(http_client=_QueuedHttpClient([]))

        self.assertEqual(provider._describe_weather_code(0), "clear sky")
        self.assertEqual(provider._describe_weather_code(61), "slight rain")
        self.assertEqual(provider._describe_weather_code(99), "thunderstorm with heavy hail")
        self.assertEqual(provider._describe_weather_code(999), "unknown")

    def test_provider_returns_empty_location_report_for_blank_input(self) -> None:
        provider = OpenMeteoWeatherProvider(http_client=_QueuedHttpClient([]))

        report = provider.fetch("   ")

        self.assertEqual(report.location, "")
        self.assertEqual(report.condition, "location not provided")
        self.assertEqual(report.metadata["status"], "empty_location")


if __name__ == "__main__":
    unittest.main()
