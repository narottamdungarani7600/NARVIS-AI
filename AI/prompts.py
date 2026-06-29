"""Prompt construction helpers for the NARVIS Brain subsystem."""

from __future__ import annotations

from typing import Any

from .intent import IntentClassification


class PromptBuilder:
    """Constructs role-specific prompts for AI providers."""

    def build_system_prompt(self, intent: IntentClassification | None = None, memory_summary: str | None = None) -> str:
        """Build the system instruction for the provider."""
        intent_note = f" The current intent is {intent.intent.value}." if intent else ""
        memory_note = f" Relevant memory: {memory_summary}." if memory_summary else ""
        return (
            "You are NARVIS, a helpful AI assistant. Respond clearly, concisely, and professionally."
            + intent_note
            + memory_note
        )

    def build_user_prompt(self, user_text: str, history: list[Any] | None = None, memory_summary: str | None = None, intent: IntentClassification | None = None) -> str:
        """Create the user-facing prompt sent to the provider."""
        history_text = self._format_history(history or [])
        memory_note = f"\nMemory summary: {memory_summary}" if memory_summary else ""
        intent_note = f"\nDetected intent: {intent.intent.value}" if intent else ""
        return f"User message: {user_text}{intent_note}{memory_note}{history_text}"

    def build_summary_prompt(self, history: list[Any]) -> str:
        """Create a prompt for summarizing recent conversation history."""
        history_text = self._format_history(history)
        return f"Summarize the following conversation in a concise paragraph.\n{history_text}"

    def _format_history(self, history: list[Any]) -> str:
        """Convert history turns into a plain-text representation."""
        if not history:
            return ""
        entries = []
        for turn in history:
            entries.append(f"{turn.role}: {turn.content}")
        return "\n" + "\n".join(entries)
