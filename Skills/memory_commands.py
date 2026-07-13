"""Pure natural-language parsing for built-in memory commands."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class MemoryCommandAction(str, Enum):
    """The closed memory operations recognized by the built-in skill."""

    STORE = "store"
    RECALL = "recall"
    FORGET = "forget"


class MemoryCommandScope(str, Enum):
    """The memory domain targeted by a parsed command."""

    GENERAL = "general"
    PROFILE = "profile"
    CONVERSATION = "conversation"


@dataclass(slots=True, frozen=True)
class MemoryCommand:
    """One immutable parsed memory command containing user-supplied data only."""

    action: MemoryCommandAction
    verb: str
    key: str
    query: str
    value: str = ""
    scope: MemoryCommandScope = MemoryCommandScope.GENERAL


_NON_WORD_PATTERN = re.compile(r"[^a-z0-9]+")
_STORE_VALUE_PATTERN = re.compile(
    r"^(?P<key>.+?)\s+(?:(?:is|as)\s+|=\s*)(?P<value>.+)$",
    re.IGNORECASE,
)
_RECALL_PREFIXES = (
    "what do you remember about",
    "what do you remember",
    "search memory for",
    "remember about",
    "recall",
)
_FORGET_PREFIXES = (
    "delete memory",
    "forget",
)
_STORE_PREFIXES = (
    "remember",
    "save",
    "store",
    "note",
)
_PROFILE_RECALL_PATTERNS = (
    re.compile(r"^(?:profile|show my profile|recall my profile)$", re.IGNORECASE),
    re.compile(r"^(?:what do you know about me|who am i)$", re.IGNORECASE),
    re.compile(r"^(?:what is|what's) my (?P<field>.+)$", re.IGNORECASE),
)
_CONVERSATION_RECALL_PATTERNS = (
    re.compile(r"^what did i tell you(?: about (?P<query>.+))?$", re.IGNORECASE),
    re.compile(r"^what did we discuss(?: about (?P<query>.+))?$", re.IGNORECASE),
    re.compile(r"^what did we talk about(?: (?P<query>.+))?$", re.IGNORECASE),
    re.compile(r"^recall (?:our|this) conversation(?: about (?P<query>.+))?$", re.IGNORECASE),
    re.compile(r"^conversation memory(?: about (?P<query>.+))?$", re.IGNORECASE),
)


def normalize_memory_key(value: str) -> str:
    """Create one stable storage key from user-provided memory text."""

    normalized = _NON_WORD_PATTERN.sub("_", str(value or "").strip().lower()).strip("_")
    return normalized[:120].rstrip("_") or ""


def display_memory_key(value: str) -> str:
    """Convert an internal scoped key into a compact user-facing label."""

    key = str(value or "").rsplit(":", 1)[-1]
    return " ".join(key.replace("_", " ").split()) or "memory"


class MemoryCommandParser:
    """Parse common memory verbs without storage, routing, or runtime access."""

    def parse(self, text: str) -> MemoryCommand | None:
        """Return one typed memory command or None when no memory verb matches."""

        if not isinstance(text, str):
            return None
        normalized = " ".join(text.strip().split())
        if not normalized:
            return None
        lowered = normalized.lower()
        sentence = normalized.strip(" .?!")

        for pattern in _CONVERSATION_RECALL_PATTERNS:
            match = pattern.fullmatch(sentence)
            if match is None:
                continue
            query = str(match.groupdict().get("query") or "").strip()
            return MemoryCommand(
                action=MemoryCommandAction.RECALL,
                verb=match.group(0),
                key=normalize_memory_key(query),
                query=query,
                scope=MemoryCommandScope.CONVERSATION,
            )

        for pattern in _PROFILE_RECALL_PATTERNS:
            match = pattern.fullmatch(sentence)
            if match is None:
                continue
            field = str(match.groupdict().get("field") or "").strip()
            query = f"my {field}" if field else "profile"
            return MemoryCommand(
                action=MemoryCommandAction.RECALL,
                verb=match.group(0),
                key=normalize_memory_key(query) if field else "",
                query=query,
                scope=MemoryCommandScope.PROFILE,
            )

        matched = self._match_prefix(normalized, lowered, _RECALL_PREFIXES)
        if matched is not None:
            verb, query = matched
            profile_query = query.strip(" .?!").lower() in {"me", "my profile"}
            scope = MemoryCommandScope.PROFILE if profile_query else MemoryCommandScope.GENERAL
            return MemoryCommand(
                action=MemoryCommandAction.RECALL,
                verb=verb,
                key="" if profile_query else normalize_memory_key(query),
                query=query,
                scope=scope,
            )

        matched = self._match_prefix(normalized, lowered, _FORGET_PREFIXES)
        if matched is not None:
            verb, query = matched
            scope = MemoryCommandScope.PROFILE if query.lower().startswith("my ") else MemoryCommandScope.GENERAL
            return MemoryCommand(
                action=MemoryCommandAction.FORGET,
                verb=verb,
                key=normalize_memory_key(query),
                query=query,
                scope=scope,
            )

        matched = self._match_prefix(normalized, lowered, _STORE_PREFIXES)
        if matched is None:
            return None
        verb, content = matched
        if content.lower().startswith("that "):
            content = content[5:].strip()
        value_match = _STORE_VALUE_PATTERN.fullmatch(content)
        if value_match is None:
            key_text = content
            value = content
        else:
            key_text = value_match.group("key").strip()
            value = value_match.group("value").strip()
        return MemoryCommand(
            action=MemoryCommandAction.STORE,
            verb=verb,
            key=normalize_memory_key(key_text),
            query=key_text,
            value=value,
            scope=(
                MemoryCommandScope.PROFILE
                if key_text.lower().startswith("my ")
                else MemoryCommandScope.GENERAL
            ),
        )

    def _match_prefix(
        self,
        normalized: str,
        lowered: str,
        prefixes: tuple[str, ...],
    ) -> tuple[str, str] | None:
        """Return the first exact command prefix and its remaining user text."""

        for prefix in prefixes:
            if lowered == prefix:
                return prefix, ""
            if lowered.startswith(f"{prefix} "):
                return prefix, normalized[len(prefix) :].strip()
        return None


__all__ = [
    "MemoryCommand",
    "MemoryCommandAction",
    "MemoryCommandParser",
    "MemoryCommandScope",
    "display_memory_key",
    "normalize_memory_key",
]
