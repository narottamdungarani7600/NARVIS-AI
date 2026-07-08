"""Read-only current-capability inventory helpers for the Evolution package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import CapabilityInventorySnapshot, CapabilityRecord, compact_text, stable_id


def _emit_log(logger: Any | None, level: str, message: str, **context: Any) -> None:
    """Write a log message using either stdlib-style or Core logger contracts."""

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
class CapabilityInventoryBuilder:
    """Build one deterministic read-only capability inventory snapshot."""

    config: Any
    ai_provider: Any
    memory_storage: Any
    short_term_memory: Any
    long_term_memory: Any
    session_memory: Any
    profile_memory: Any
    internet_service: Any
    skill_registry: Any
    plugin_registry: Any
    voice_runtime_service: Any | None = None
    vision_service: Any | None = None
    logger: Any | None = None

    def build(self) -> CapabilityInventorySnapshot:
        """Create one deterministic snapshot from current runtime facts."""

        records: list[CapabilityRecord] = []
        records.extend(self._build_core_records())
        records.extend(self._build_memory_records())
        records.extend(self._build_internet_records())
        records.extend(self._build_skill_records())
        records.extend(self._build_plugin_records())
        records.extend(self._build_health_records())
        ordered = tuple(sorted(records, key=lambda record: (record.category, record.name, record.capability_id)))
        snapshot_id = stable_id(
            "capability_inventory",
            [record.to_dict() for record in ordered],
        )
        snapshot = CapabilityInventorySnapshot(snapshot_id=snapshot_id, capabilities=ordered)
        _emit_log(self.logger, "info", "Built capability inventory snapshot", capability_count=len(snapshot.capabilities))
        return snapshot

    def _build_core_records(self) -> list[CapabilityRecord]:
        """Return core runtime and AI provider capability facts."""

        provider_metrics = self.ai_provider.get_metrics() if hasattr(self.ai_provider, "get_metrics") else {}
        return [
            CapabilityRecord(
                capability_id="core:narvis-runtime",
                name="core:narvis-runtime",
                category="core",
                status="available",
                implementation="NARVISApplication",
                source_of_truth="config",
                metadata={
                    "environment": getattr(self.config, "environment", "unknown"),
                    "version": getattr(self.config, "version", "unknown"),
                },
            ),
            CapabilityRecord(
                capability_id="ai:provider",
                name="ai:provider",
                category="ai",
                status="configured",
                implementation=type(self.ai_provider).__name__,
                source_of_truth="ai_provider",
                metadata={
                    "provider_name": getattr(self.ai_provider, "name", type(self.ai_provider).__name__),
                    "request_count": provider_metrics.get("request_count", 0),
                    "last_error": provider_metrics.get("last_error") or "",
                },
            ),
        ]

    def _build_memory_records(self) -> list[CapabilityRecord]:
        """Return durable memory capability facts."""

        return [
            self._memory_record("memory:storage", self.memory_storage),
            self._memory_record("memory:short-term", self.short_term_memory),
            self._memory_record("memory:long-term", self.long_term_memory),
            self._memory_record("memory:session", self.session_memory),
            self._memory_record("memory:profile", self.profile_memory),
        ]

    def _memory_record(self, name: str, instance: Any) -> CapabilityRecord:
        """Create one memory capability record."""

        return CapabilityRecord(
            capability_id=name,
            name=name,
            category="memory",
            status="available",
            implementation=type(instance).__name__,
            source_of_truth=name.split(":", 1)[1].replace("-", "_"),
        )

    def _build_internet_records(self) -> list[CapabilityRecord]:
        """Return internet capability records backed by runtime service metadata."""

        capability_map = dict(self.internet_service.capabilities())
        network_status = self.internet_service.network_status()
        records = [
            CapabilityRecord(
                capability_id="internet:runtime",
                name="internet:runtime",
                category="internet",
                status="available",
                implementation=type(self.internet_service).__name__,
                source_of_truth="internet_service.capabilities",
                metadata={
                    "network_mode": network_status.details.get("mode", "unknown"),
                    "online": bool(network_status.online),
                },
            )
        ]
        for capability_name in (
            "http_client",
            "search_provider",
            "research_service",
            "news_provider",
            "weather_provider",
            "wikipedia_provider",
            "youtube_provider",
        ):
            implementation = str(capability_map.get(capability_name, "unknown"))
            records.append(
                CapabilityRecord(
                    capability_id=f"internet:{capability_name}",
                    name=f"internet:{capability_name}",
                    category="internet",
                    status="available" if not implementation.lower().startswith("null") else "unavailable",
                    implementation=implementation,
                    source_of_truth="internet_service.capabilities",
                )
            )
        return records

    def _build_skill_records(self) -> list[CapabilityRecord]:
        """Return skill-derived capability facts."""

        records: list[CapabilityRecord] = []
        for skill in sorted(self.skill_registry.list_skills(), key=lambda item: item.name):
            records.append(
                CapabilityRecord(
                    capability_id=f"skill:{skill.name}",
                    name=f"skill:{skill.name}",
                    category=self._category_for_skill(skill.name),
                    status="available",
                    implementation=type(skill).__name__,
                    source_of_truth="skill_registry",
                    metadata={"description": getattr(skill, "description", "")},
                )
            )
        return records

    def _category_for_skill(self, skill_name: str) -> str:
        """Map one skill name onto a broader capability category."""

        lowered = skill_name.lower()
        if lowered.startswith("internet.") or lowered.startswith("wikipedia") or lowered.startswith("youtube"):
            return "internet"
        if lowered.startswith("memory."):
            return "memory"
        if lowered.startswith("desktop."):
            return "computer_control"
        if lowered.startswith("help.") or lowered.startswith("runtime."):
            return "core"
        return "skill"

    def _build_plugin_records(self) -> list[CapabilityRecord]:
        """Return plugin-derived capability facts without triggering plugin actions."""

        records: list[CapabilityRecord] = []
        for plugin in self.plugin_registry.list_plugins():
            category = self._category_for_plugin_kind(plugin.descriptor.kind)
            records.append(
                CapabilityRecord(
                    capability_id=f"plugin:{plugin.descriptor.name}",
                    name=f"plugin:{plugin.descriptor.name}",
                    category=category,
                    status="loaded" if plugin.loaded else "registered",
                    implementation=plugin.descriptor.kind,
                    source_of_truth="plugin_registry",
                    metadata={
                        "services": tuple(plugin.descriptor.services),
                        "description": plugin.descriptor.description,
                    },
                )
            )
        return records

    def _category_for_plugin_kind(self, plugin_kind: str) -> str:
        """Map one plugin kind onto a capability category."""

        normalized = compact_text(plugin_kind, max_chars=40).lower()
        if normalized in {"automation", "internet", "voice", "vision", "memory"}:
            return normalized
        if normalized == "skills":
            return "skill"
        return "plugin"

    def _build_health_records(self) -> list[CapabilityRecord]:
        """Return read-only Voice and Vision health facts when available."""

        records: list[CapabilityRecord] = []
        if self.voice_runtime_service is not None:
            voice_health = self.voice_runtime_service.health_report()
            recognition = voice_health.details.get("speech_recognition", {})
            records.append(
                CapabilityRecord(
                    capability_id="voice:runtime",
                    name="voice:runtime",
                    category="voice",
                    status=str(voice_health.status),
                    implementation=type(self.voice_runtime_service).__name__,
                    source_of_truth="voice_runtime_service.health_report",
                    metadata={
                        "microphone_available": bool(voice_health.details.get("microphone_available")),
                        "speech_recognition_available": bool(recognition.get("any_available", False)),
                        "text_to_speech_available": bool(voice_health.details.get("text_to_speech_available")),
                        "optional_dependency_warning_count": len(voice_health.details.get("optional_dependency_warnings", [])),
                    },
                )
            )
        if self.vision_service is not None:
            vision_health = self.vision_service.health_report()
            records.append(
                CapabilityRecord(
                    capability_id="vision:runtime",
                    name="vision:runtime",
                    category="vision",
                    status=str(vision_health.status),
                    implementation=type(self.vision_service).__name__,
                    source_of_truth="vision_service.health_report",
                    metadata={
                        "camera_available": bool(vision_health.details.get("camera_available")),
                        "screenshot_available": bool(vision_health.details.get("screenshot_available")),
                        "ocr_available": bool(vision_health.details.get("ocr_available")),
                    },
                )
            )
        return records


__all__ = ["CapabilityInventoryBuilder"]
