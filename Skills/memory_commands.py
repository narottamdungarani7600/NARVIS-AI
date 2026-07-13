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
_POSSESSIVE_PATTERN = re.compile(r"['\u2019]s\b", re.IGNORECASE)
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
    re.compile(r"^(?:what|which) company do i work for$", re.IGNORECASE),
    re.compile(r"^where do i work$", re.IGNORECASE),
    re.compile(r"^what colou?r do i (?:like|prefer)$", re.IGNORECASE),
    re.compile(r"^(?:what is|what's) (?P<field>her name|his name|their name)$", re.IGNORECASE),
)
_PROFILE_RECALL_KEYS = {
    "what company do i work for": "my company",
    "which company do i work for": "my company",
    "where do i work": "my company",
    "what color do i like": "my favorite color",
    "what colour do i like": "my favorite color",
    "what color do i prefer": "my favorite color",
    "what colour do i prefer": "my favorite color",
}
_PROFILE_STORE_PATTERNS = (
    (re.compile(r"^my name is (?P<value>.+)$", re.IGNORECASE), "my name"),
    (re.compile(r"^i work at (?P<value>.+)$", re.IGNORECASE), "my company"),
    (re.compile(r"^i work for (?P<value>.+)$", re.IGNORECASE), "my company"),
    (
        re.compile(r"^my favou?rite (?P<subject>[a-z0-9][a-z0-9 '\-]*?) is (?P<value>.+)$", re.IGNORECASE),
        "my favorite {subject}",
    ),
    (
        re.compile(
            r"^my (?P<relation>wife|husband|son|daughter|mother|father|sister|brother)(?:['\u2019]s)? name is (?P<value>.+)$",
            re.IGNORECASE,
        ),
        "my {relation} name",
    ),
    (
        re.compile(r"^my (?P<relation>wife|husband|son|daughter|mother|father|sister|brother) is (?P<value>.+)$", re.IGNORECASE),
        "my {relation}",
    ),
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

    without_possessive = _POSSESSIVE_PATTERN.sub("", str(value or "").strip().lower())
    normalized = _NON_WORD_PATTERN.sub("_", without_possessive).strip("_")
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

        for pattern, key_template in _PROFILE_STORE_PATTERNS:
            match = pattern.fullmatch(sentence)
            if match is None:
                continue
            groups = {name: str(value or "").strip() for name, value in match.groupdict().items()}
            value = groups.pop("value", "")
            key_text = key_template.format(**groups)
            return MemoryCommand(
                action=MemoryCommandAction.STORE,
                verb="profile fact",
                key=normalize_memory_key(key_text),
                query=key_text,
                value=value,
                scope=MemoryCommandScope.PROFILE,
            )

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
            aliased_query = _PROFILE_RECALL_KEYS.get(sentence.lower())
            query = aliased_query or (f"my {field}" if field and not field.lower().startswith(("her ", "his ", "their ")) else field)
            if not query:
                query = "profile"
            return MemoryCommand(
                action=MemoryCommandAction.RECALL,
                verb=match.group(0),
                key=normalize_memory_key(query) if query != "profile" else "",
                query=query,
                scope=MemoryCommandScope.PROFILE,
            )

        matched = self._match_prefix(normalized, lowered, _RECALL_PREFIXES)
        if matched is not None:
            verb, query = matched
            normalized_query = query.strip(" .?!").lower()
            whole_profile_query = normalized_query in {"me", "my profile"}
            profile_query = whole_profile_query or normalized_query.startswith("my ")
            scope = MemoryCommandScope.PROFILE if profile_query else MemoryCommandScope.GENERAL
            return MemoryCommand(
                action=MemoryCommandAction.RECALL,
                verb=verb,
                key="" if whole_profile_query else normalize_memory_key(query),
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
            value = value_match.group("value").strip().strip(" .?!")
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
