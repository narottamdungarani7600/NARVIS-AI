"""Weather provider abstractions and live providers for the NARVIS Internet package."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlencode

from .requests import BaseHttpClient


def _emit_log(logger: Any | None, level: str, message: str, **context: Any) -> None:
    """Write a log message through either the Core logger or stdlib logging."""

    if logger is None:
        return

    if hasattr(logger, level.lower()):
        details = " | ".join(f"{key}={value}" for key, value in sorted(context.items()))
        payload = f"{message} | {details}" if details else message
        getattr(logger, level.lower())(payload)
        return

    try:
        from Core.logger import LogLevel

        log_level = getattr(LogLevel, level.upper(), LogLevel.INFO)
        logger.log(log_level, message, **context)
    except Exception:
        return


@dataclass(slots=True)
class WeatherReport:
    """Represents a weather report payload."""

    location: str
    condition: str = "unknown"
    temperature_c: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class WeatherProvider(Protocol):
    """Protocol for weather provider services."""

    def fetch(self, location: str) -> WeatherReport:
        """Fetch a weather report for the given location."""


class BaseWeatherProvider(ABC):
    """Abstract base class for weather provider implementations."""

    @abstractmethod
    def fetch(self, location: str) -> WeatherReport:
        """Fetch a weather report for the given location."""


@dataclass(slots=True, frozen=True)
class _ResolvedLocation:
    """Represents one normalized Open-Meteo geocoding result."""

    display_name: str
    latitude: float
    longitude: float
    country: str = ""
    country_code: str = ""
    admin1: str = ""
    timezone: str = ""


@dataclass(slots=True, frozen=True)
class _GeocodingOutcome:
    """Represents the result of one geocoding lookup."""

    status: str
    location: _ResolvedLocation | None = None


_WEATHER_CODE_LABELS = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snowfall",
    73: "moderate snowfall",
    75: "heavy snowfall",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


class OpenMeteoWeatherProvider(BaseWeatherProvider):
    """Weather provider backed by Open-Meteo geocoding and forecast APIs."""

    def __init__(
        self,
        *,
        http_client: BaseHttpClient,
        timeout_seconds: float = 6.0,
        geocoding_endpoint: str = "https://geocoding-api.open-meteo.com/v1/search",
        forecast_endpoint: str = "https://api.open-meteo.com/v1/forecast",
        logger: Any | None = None,
    ) -> None:
        self.http_client = http_client
        self.timeout_seconds = timeout_seconds
        self.geocoding_endpoint = geocoding_endpoint
        self.forecast_endpoint = forecast_endpoint
        self.logger = logger

    def fetch(self, location: str) -> WeatherReport:
        """Fetch current weather conditions for the best matching location."""

        requested_location = self._normalize_text(location)
        if not requested_location:
            return self._build_report(
                location="",
                condition="location not provided",
                status="empty_location",
                requested_location="",
            )

        geocoding = self._geocode(requested_location)
        if geocoding.location is None:
            condition = "location not found" if geocoding.status == "location_not_found" else "unavailable"
            return self._build_report(
                location=requested_location,
                condition=condition,
                status=geocoding.status,
                requested_location=requested_location,
            )

        payload = self._fetch_forecast_payload(geocoding.location)
        if payload is None:
            return self._build_report(
                location=geocoding.location.display_name,
                condition="unavailable",
                status="forecast_unavailable",
                requested_location=requested_location,
                resolved_location=geocoding.location,
            )

        current = payload.get("current")
        if not isinstance(current, dict):
            _emit_log(
                self.logger,
                "warning",
                "Open-Meteo forecast payload missing current weather block",
                location=geocoding.location.display_name,
            )
            return self._build_report(
                location=geocoding.location.display_name,
                condition="unavailable",
                status="invalid_current_weather",
                requested_location=requested_location,
                resolved_location=geocoding.location,
            )

        temperature_c = self._coerce_number(current.get("temperature_2m"))
        weather_code = self._coerce_int(current.get("weather_code"))
        if temperature_c is None and weather_code is None:
            _emit_log(
                self.logger,
                "warning",
                "Open-Meteo current weather payload missing temperature and weather code",
                location=geocoding.location.display_name,
            )
            return self._build_report(
                location=geocoding.location.display_name,
                condition="unavailable",
                status="invalid_current_weather",
                requested_location=requested_location,
                resolved_location=geocoding.location,
            )

        metadata = self._metadata(
            status="ok",
            requested_location=requested_location,
            resolved_location=geocoding.location,
        )
        observed_at = self._coerce_text(current.get("time"))
        if observed_at:
            metadata["observed_at"] = observed_at
        timezone = self._coerce_text(payload.get("timezone"))
        if timezone:
            metadata["timezone"] = timezone
        if weather_code is not None:
            metadata["weather_code"] = weather_code

        return WeatherReport(
            location=geocoding.location.display_name,
            condition=self._describe_weather_code(weather_code),
            temperature_c=temperature_c,
            metadata=metadata,
        )

    def _geocode(self, location: str) -> _GeocodingOutcome:
        """Resolve a free-form location string into coordinates."""

        payload = self._request_json(
            self.geocoding_endpoint,
            {
                "name": location,
                "count": "5",
                "format": "json",
                "language": "en",
            },
        )
        if payload is None:
            return _GeocodingOutcome(status="geocoding_unavailable")

        raw_results = payload.get("results")
        if raw_results is None:
            return _GeocodingOutcome(status="location_not_found")
        if not isinstance(raw_results, list):
            _emit_log(self.logger, "warning", "Open-Meteo geocoding returned invalid results shape", location=location)
            return _GeocodingOutcome(status="geocoding_unavailable")
        if not raw_results:
            return _GeocodingOutcome(status="location_not_found")

        for item in raw_results:
            if not isinstance(item, dict):
                continue
            name = self._coerce_text(item.get("name"))
            latitude = self._coerce_number(item.get("latitude"))
            longitude = self._coerce_number(item.get("longitude"))
            if not name or latitude is None or longitude is None:
                continue
            admin1 = self._coerce_text(item.get("admin1"))
            country = self._coerce_text(item.get("country"))
            display_name = self._build_display_name(name, admin1, country)
            return _GeocodingOutcome(
                status="ok",
                location=_ResolvedLocation(
                    display_name=display_name,
                    latitude=latitude,
                    longitude=longitude,
                    country=country,
                    country_code=self._coerce_text(item.get("country_code")),
                    admin1=admin1,
                    timezone=self._coerce_text(item.get("timezone")),
                ),
            )

        _emit_log(self.logger, "warning", "Open-Meteo geocoding results lacked valid entries", location=location)
        return _GeocodingOutcome(status="geocoding_unavailable")

    def _fetch_forecast_payload(self, location: _ResolvedLocation) -> dict[str, Any] | None:
        """Fetch the current weather block for one resolved location."""

        return self._request_json(
            self.forecast_endpoint,
            {
                "latitude": self._format_coordinate(location.latitude),
                "longitude": self._format_coordinate(location.longitude),
                "current": "temperature_2m,weather_code",
                "temperature_unit": "celsius",
                "timezone": "auto",
            },
        )

    def _request_json(self, endpoint: str, params: dict[str, str]) -> dict[str, Any] | None:
        """Perform one GET request and validate the JSON payload."""

        url = self._build_url(endpoint, params)
        try:
            response = self.http_client.get(url, timeout=self.timeout_seconds)
        except Exception as exc:
            _emit_log(self.logger, "warning", "Weather request raised an exception", url=url, error=str(exc))
            return None

        if not isinstance(response, dict):
            _emit_log(self.logger, "warning", "Weather request returned a non-dict response", url=url)
            return None

        status = response.get("status")
        if not isinstance(status, int) or status < 200 or status >= 300:
            _emit_log(
                self.logger,
                "warning",
                "Weather request failed",
                url=url,
                status=status,
                error=response.get("error"),
            )
            return None

        payload = response.get("json")
        if not isinstance(payload, dict):
            _emit_log(self.logger, "warning", "Weather request returned malformed JSON", url=url)
            return None
        return payload

    def _build_report(
        self,
        *,
        location: str,
        condition: str,
        status: str,
        requested_location: str,
        resolved_location: _ResolvedLocation | None = None,
    ) -> WeatherReport:
        """Build one normalized weather report for success or failure paths."""

        return WeatherReport(
            location=location,
            condition=condition,
            metadata=self._metadata(
                status=status,
                requested_location=requested_location,
                resolved_location=resolved_location,
            ),
        )

    def _metadata(
        self,
        *,
        status: str,
        requested_location: str,
        resolved_location: _ResolvedLocation | None,
    ) -> dict[str, Any]:
        """Build compact metadata without retaining raw API payloads."""

        metadata: dict[str, Any] = {
            "provider": "open-meteo",
            "status": status,
            "requested_location": requested_location,
        }
        if resolved_location is not None:
            metadata["resolved_location"] = resolved_location.display_name
            metadata["latitude"] = resolved_location.latitude
            metadata["longitude"] = resolved_location.longitude
            if resolved_location.admin1:
                metadata["admin1"] = resolved_location.admin1
            if resolved_location.country:
                metadata["country"] = resolved_location.country
            if resolved_location.country_code:
                metadata["country_code"] = resolved_location.country_code
            if resolved_location.timezone:
                metadata["timezone"] = resolved_location.timezone
        return metadata

    def _build_url(self, endpoint: str, params: dict[str, str]) -> str:
        """Build a query URL against the configured API endpoint."""

        separator = "&" if "?" in endpoint else "?"
        return f"{endpoint}{separator}{urlencode(params)}"

    def _build_display_name(self, name: str, admin1: str, country: str) -> str:
        """Compose a compact, deduplicated display name for the resolved location."""

        parts: list[str] = []
        seen: set[str] = set()
        for value in (name, admin1, country):
            normalized_value = self._normalize_text(value)
            if not normalized_value:
                continue
            marker = normalized_value.casefold()
            if marker in seen:
                continue
            seen.add(marker)
            parts.append(normalized_value)
        return ", ".join(parts) if parts else name

    def _describe_weather_code(self, weather_code: int | None) -> str:
        """Translate a WMO weather code into a stable human-readable label."""

        if weather_code is None:
            return "unknown"
        return _WEATHER_CODE_LABELS.get(weather_code, "unknown")

    def _format_coordinate(self, value: float) -> str:
        """Format coordinates deterministically for query parameters."""

        return f"{value:.6f}".rstrip("0").rstrip(".")

    def _normalize_text(self, value: Any) -> str:
        """Collapse internal whitespace for a text payload."""

        return " ".join(str(value).strip().split())

    def _coerce_text(self, value: Any) -> str:
        """Return a safe string representation for optional text fields."""

        return value.strip() if isinstance(value, str) else ""

    def _coerce_number(self, value: Any) -> float | None:
        """Convert one JSON scalar into a finite floating-point value."""

        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            resolved = float(value)
            if resolved == resolved and resolved not in (float("inf"), float("-inf")):
                return resolved
        return None

    def _coerce_int(self, value: Any) -> int | None:
        """Convert one JSON scalar into an integer weather code."""

        number = self._coerce_number(value)
        if number is None:
            return None
        if int(number) != number:
            return None
        return int(number)


class NullWeatherProvider(BaseWeatherProvider):
    """No-op weather provider used as a placeholder implementation."""

    def fetch(self, location: str) -> WeatherReport:
        """Return an empty weather report."""
        return WeatherReport(location=location)


__all__ = [
    "BaseWeatherProvider",
    "NullWeatherProvider",
    "OpenMeteoWeatherProvider",
    "WeatherProvider",
    "WeatherReport",
]
