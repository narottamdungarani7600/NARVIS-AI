"""Voice session management and orchestration for NARVIS."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from .audio import AudioFrame, _emit_log
from .listener import VoiceListener
from .speaker import SpeakerService


class VoiceState(str, Enum):
    """Represent the current lifecycle state of the voice pipeline."""

    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    PAUSED = "paused"


@dataclass(slots=True)
class VoiceSession:
    """Represent an active voice interaction session."""

    session_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_input: str | None = None
    last_output: str | None = None
    input_count: int = 0
    output_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class VoiceQueue:
    """Manage a queue of transcribed voice commands."""

    def __init__(self, max_size: int = 100) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=max_size)

    async def enqueue(self, text: str) -> None:
        """Add a text command to the queue."""

        await self._queue.put(text)

    async def dequeue(self, timeout: float | None = None) -> str | None:
        """Retrieve the next text command from the queue."""

        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def size(self) -> int:
        """Return the number of queued items."""

        return self._queue.qsize()

    def empty(self) -> bool:
        """Return whether the queue is empty."""

        return self._queue.empty()


class VoiceSessionManager:
    """Track voice sessions and their recent activity."""

    def __init__(self, logger: Any | None = None) -> None:
        self.logger = logger
        self._sessions: dict[str, VoiceSession] = {}
        self._current_session_id: str | None = None

    def create_session(self, session_id: str | None = None) -> VoiceSession:
        """Create and activate a new voice session."""

        resolved_session_id = session_id or f"voice-session-{len(self._sessions) + 1}"
        session = VoiceSession(session_id=resolved_session_id)
        self._sessions[resolved_session_id] = session
        self._current_session_id = resolved_session_id
        _emit_log(self.logger, "info", "Voice session created", session_id=resolved_session_id)
        return session

    def get_session(self, session_id: str | None = None) -> VoiceSession | None:
        """Return a voice session by identifier."""

        resolved_session_id = session_id or self._current_session_id
        if resolved_session_id is None:
            return None
        return self._sessions.get(resolved_session_id)

    def ensure_session(self) -> VoiceSession:
        """Return the active session, creating one if needed."""

        session = self.get_session()
        if session is not None:
            return session
        return self.create_session()

    def update_session_input(self, text: str, session_id: str | None = None) -> None:
        """Record user speech input in the session."""

        session = self.get_session(session_id) or self.ensure_session()
        session.last_input = text
        session.input_count += 1

    def update_session_output(self, text: str, session_id: str | None = None) -> None:
        """Record system speech output in the session."""

        session = self.get_session(session_id) or self.ensure_session()
        session.last_output = text
        session.output_count += 1

    def end_session(self, session_id: str | None = None) -> None:
        """Remove a session from the session manager."""

        resolved_session_id = session_id or self._current_session_id
        if resolved_session_id is None:
            return
        self._sessions.pop(resolved_session_id, None)
        if self._current_session_id == resolved_session_id:
            self._current_session_id = None
        _emit_log(self.logger, "info", "Voice session ended", session_id=resolved_session_id)


class VoiceCommandProcessor:
    """Process transcribed commands through an injected handler."""

    def __init__(
        self,
        command_handler: Callable[[str], str | None] | None = None,
        logger: Any | None = None,
    ) -> None:
        self.command_handler = command_handler
        self.logger = logger

    def process(self, text: str) -> str | None:
        """Process a transcript and return an optional response."""

        if not text.strip():
            return None
        if self.command_handler is None:
            _emit_log(self.logger, "info", "Voice command processor received transcript without handler")
            return text
        try:
            return self.command_handler(text)
        except Exception as error:
            _emit_log(self.logger, "warning", "Voice command handler failed", error=str(error))
            return None


class VoiceManager:
    """Coordinate listening, command processing, and speech output."""

    def __init__(
        self,
        *,
        listener: VoiceListener,
        speaker: SpeakerService,
        command_processor: VoiceCommandProcessor | None = None,
        session_manager: VoiceSessionManager | None = None,
        logger: Any | None = None,
    ) -> None:
        self.listener = listener
        self.speaker = speaker
        self.command_processor = command_processor or VoiceCommandProcessor(logger=logger)
        self.session_manager = session_manager or VoiceSessionManager(logger=logger)
        self.logger = logger
        self.state = VoiceState.IDLE

    def listen_once(self, *, require_wake_word: bool = True, max_frames: int | None = None) -> str:
        """Capture a single voice command and return the recognized text."""

        if self.state == VoiceState.PAUSED:
            _emit_log(self.logger, "warning", "Listen requested while voice manager is paused")
            return ""

        self.state = VoiceState.LISTENING
        transcript = self.listener.listen(require_wake_word=require_wake_word, max_frames=max_frames)
        self.state = VoiceState.IDLE
        if transcript:
            self.session_manager.update_session_input(transcript)
        return transcript

    def process_once(
        self,
        *,
        require_wake_word: bool = True,
        max_frames: int | None = None,
        speak_response: bool = False,
    ) -> str | None:
        """Capture a voice command, process it, and optionally synthesize a reply."""

        transcript = self.listen_once(require_wake_word=require_wake_word, max_frames=max_frames)
        if not transcript:
            return None

        self.state = VoiceState.PROCESSING
        response = self.command_processor.process(transcript)
        self.state = VoiceState.IDLE

        if response:
            self.session_manager.update_session_output(response)
            if speak_response:
                self.speak_text(response)
        return response

    def speak_text(self, text: str) -> AudioFrame:
        """Synthesize spoken output for the supplied text."""

        self.state = VoiceState.SPEAKING
        frame = self.speaker.speak(text)
        self.state = VoiceState.IDLE
        return frame

    def pause(self) -> None:
        """Pause new voice work until resumed."""

        self.state = VoiceState.PAUSED

    def resume(self) -> None:
        """Resume voice work after a pause."""

        if self.state == VoiceState.PAUSED:
            self.state = VoiceState.IDLE

    def stop(self) -> None:
        """Stop the voice manager and reset it to idle."""

        self.state = VoiceState.IDLE

    def get_state(self) -> str:
        """Return the current state as a string."""

        return self.state.value


class VoiceSystemManager(VoiceManager):
    """Backward-compatible asynchronous wrapper around ``VoiceManager``."""

    async def listen(self, timeout_seconds: int = 30) -> str | None:
        """Capture a single voice command asynchronously."""

        microphone = self.listener.audio_input_service.microphone_service.microphone
        sample_rate = getattr(microphone, "sample_rate", 16000)
        chunk_size = getattr(microphone, "chunk_size", 1024)
        frames_per_second = max(1, int(sample_rate / max(1, chunk_size)))
        max_frames = max(1, timeout_seconds * frames_per_second)
        transcript = await asyncio.to_thread(
            self.listen_once,
            require_wake_word=True,
            max_frames=max_frames,
        )
        return transcript or None

    async def speak(self, text: str) -> bool:
        """Synthesize text asynchronously and report success."""

        frame = await asyncio.to_thread(self.speak_text, text)
        return not frame.is_empty()
