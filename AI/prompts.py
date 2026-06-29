"""Prompt construction helpers for the NARVIS Brain subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .context import ConversationContext
from .intent import IntentClassification
from .router import ModuleRoute


@dataclass(slots=True)
class PromptTemplateConfig:
    """Configuration values used by :class:`PromptBuilder`."""

    assistant_name: str = "NARVIS"
    base_system_prompt: str = (
        "You are NARVIS, a helpful AI assistant. Respond clearly, concisely, "
        "truthfully, and in a way that moves the task forward."
    )
    summary_instruction: str = "Summarize the following conversation in a concise paragraph."
    max_history_turns: int = 12


class PromptBuilder:
    """Construct role-specific prompts for AI providers."""

    def __init__(self, config: PromptTemplateConfig | None = None) -> None:
        """Initialize the prompt builder with configurable templates."""
        self.config = config or PromptTemplateConfig()

    def build_system_prompt(
        self,
        intent: IntentClassification | None = None,
        memory_summary: str | None = None,
        route: ModuleRoute | None = None,
        context: ConversationContext | None = None,
    ) -> str:
        """Build the system instruction for the provider."""
        instructions = [self.config.base_system_prompt]
        instructions.append("Use the supplied conversation context and avoid inventing missing facts.")
        if intent is not None:
            instructions.append(f"Detected intent: {intent.intent.value}.")
        if route is not None:
            instructions.append(f"Selected logical route: {route.name}.")
        if context is not None and context.session_id is not None:
            instructions.append(f"Active session id: {context.session_id}.")
        if memory_summary:
            instructions.append(f"Relevant memory: {memory_summary}.")
        return "\n".join(instructions)

    def build_user_prompt(
        self,
        user_text: str,
        history: list[Any] | None = None,
        memory_summary: str | None = None,
        intent: IntentClassification | None = None,
        route: ModuleRoute | None = None,
        context: ConversationContext | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create the user-facing prompt sent to the provider."""
        sections = [f"Current user message:\n{user_text}"]
        if intent is not None:
            sections.append(f"Detected intent: {intent.intent.value} (confidence: {intent.confidence:.2f})")
        if route is not None:
            sections.append(f"Logical route: {route.name}")
        if memory_summary:
            sections.append(f"Memory summary:\n{memory_summary}")
        if context is not None:
            sections.append(f"Conversation id: {context.conversation_id}")
            if context.session_id is not None:
                sections.append(f"Session id: {context.session_id}")
        if metadata:
            sections.append("Runtime metadata:\n" + self._format_metadata(metadata))

        history_text = self._format_history(history or [])
        if history_text:
            sections.append(f"Recent conversation:\n{history_text}")
        return "\n\n".join(sections)

    def build_messages(
        self,
        user_text: str,
        history: list[Any] | None = None,
        memory_summary: str | None = None,
        intent: IntentClassification | None = None,
        route: ModuleRoute | None = None,
        context: ConversationContext | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        """Build chat-completion messages for a provider request."""
        messages: list[dict[str, str]] = []
        for turn in (history or [])[-self.config.max_history_turns :]:
            role = getattr(turn, "role", None) or (turn.get("role") if isinstance(turn, dict) else "user")
            content = getattr(turn, "content", None) or (turn.get("content") if isinstance(turn, dict) else str(turn))
            messages.append({"role": self._normalize_role(str(role)), "content": str(content)})

        messages.append(
            {
                "role": "user",
                "content": self.build_user_prompt(
                    user_text=user_text,
                    history=[],
                    memory_summary=memory_summary,
                    intent=intent,
                    route=route,
                    context=context,
                    metadata=metadata,
                ),
            }
        )
        return messages

    def build_summary_prompt(self, history: list[Any]) -> str:
        """Create a prompt for summarizing recent conversation history."""
        history_text = self._format_history(history)
        if not history_text:
            return "No conversation history is available to summarize."
        return f"{self.config.summary_instruction}\n{history_text}"

    def _format_history(self, history: list[Any]) -> str:
        """Convert history turns into a plain-text representation."""
        if not history:
            return ""

        entries: list[str] = []
        for turn in history[-self.config.max_history_turns :]:
            role = getattr(turn, "role", None) or (turn.get("role") if isinstance(turn, dict) else "user")
            content = getattr(turn, "content", None) or (turn.get("content") if isinstance(turn, dict) else str(turn))
            entries.append(f"{self._normalize_role(str(role))}: {str(content).strip()}")
        return "\n".join(entries)

    def _format_metadata(self, metadata: dict[str, Any]) -> str:
        """Serialize metadata into a readable line-based block."""
        return "\n".join(f"- {key}: {value}" for key, value in sorted(metadata.items()))

    def _normalize_role(self, role: str) -> str:
        """Normalize message roles to values expected by chat providers."""
        normalized = role.strip().lower()
        if normalized in {"assistant", "system", "user"}:
            return normalized
        return "user"
