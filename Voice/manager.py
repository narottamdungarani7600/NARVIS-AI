"""Voice management and orchestration for NARVIS Voice system."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from .audio import AudioFrame, AudioSink
from .microphone import BaseMicrophone, Microphone
from .realmic import RealMicrophone, VoiceActivityDetector
from .speech import SpeechToTextEngine, TextToSpeechEngine
from .wakeword import BaseWakeWordDetector, WakeWordEvent


class VoiceState(str, Enum):
    """States for the voice system."""

    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    PAUSED = "paused"


@dataclass(slots=True)
class VoiceSession:
    """Represents an active voice session."""

    session_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_input: str | None = None
    last_output: str | None = None
    input_count: int = 0
    output_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class VoiceQueue:
    """Manages a queue of voice commands for sequential processing."""

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
        """Return the current queue size."""
        return self._queue.qsize()

    def empty(self) -> bool:
        """Check if the queue is empty."""
        return self._queue.empty()


class VoiceSessionManager:
    """Manages voice sessions and session state."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("narvis.voice.session")
        self._sessions: dict[str, VoiceSession] = {}
        self._current_session_id: str | None = None

    def create_session(self, session_id: str | None = None) -> VoiceSession:
        """Create a new voice session."""
        if session_id is None:
            session_id = f"voice-session-{len(self._sessions) + 1}"
        session = VoiceSession(session_id=session_id)
        self._sessions[session_id] = session
        self._current_session_id = session_id
        self.logger.debug(f"Created voice session: {session_id}")
        return session

    def get_session(self, session_id: str | None = None) -> VoiceSession | None:
        """Retrieve a voice session by ID."""
        if session_id is None:
            session_id = self._current_session_id
        return self._sessions.get(session_id)

    def update_session_input(self, text: str, session_id: str | None = None) -> None:
        """Record user input in the session."""
        session = self.get_session(session_id)
        if session:
            session.last_input = text
            session.input_count += 1

    def update_session_output(self, text: str, session_id: str | None = None) -> None:
        """Record system output in the session."""
        session = self.get_session(session_id)
        if session:
            session.last_output = text
            session.output_count += 1

    def end_session(self, session_id: str | None = None) -> None:
        """Mark a session as ended."""
        if session_id is None:
            session_id = self._current_session_id
        if session_id and session_id in self._sessions:
            del self._sessions[session_id]
            if self._current_session_id == session_id:
                self._current_session_id = None
            self.logger.debug(f"Ended voice session: {session_id}")


class VoiceSystemManager:
    """Central manager for the complete voice system."""

    def __init__(
        self,
        microphone: Microphone | None = None,
        wake_word_detector: BaseWakeWordDetector | None = None,
        speech_to_text_engine: SpeechToTextEngine | None = None,
        text_to_speech_engine: TextToSpeechEngine | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.logger = logger or logging.getLogger("narvis.voice")
        self.microphone = microphone or RealMicrophone(logger=self.logger)
        self.wake_word_detector = wake_word_detector
        self.speech_to_text_engine = speech_to_text_engine
        self.text_to_speech_engine = text_to_speech_engine
        self.voice_activity_detector = VoiceActivityDetector(logger=self.logger)
        self.voice_queue = VoiceQueue()
        self.session_manager = VoiceSessionManager(logger=self.logger)
        self.state = VoiceState.IDLE
        self._is_listening = False
        self._interrupt_flag = False
        self._on_text_callback: Callable[[str], None] | None = None
        self._on_wake_word_callback: Callable[[WakeWordEvent], None] | None = None

    async def listen(self, timeout_seconds: int = 30) -> str | None:
        """Listen for voice input and return transcribed text."""
        if self.state != VoiceState.IDLE:
            self.logger.warning(f"Cannot listen; current state is {self.state}")
            return None

        self.state = VoiceState.LISTENING
        self._is_listening = True
        self._interrupt_flag = False

        try:
            audio_frames: list[AudioFrame] = []

            class _Sink(AudioSink):
                def __init__(self, parent: VoiceSystemManager) -> None:
                    self.parent = parent

                def write(self, frame: AudioFrame) -> None:
                    if self.parent._interrupt_flag:
                        return
                    audio_frames.append(frame)
                    if self.parent.wake_word_detector:
                        event = self.parent.wake_word_detector.process(frame)
                        if event and self.parent._on_wake_word_callback:
                            self.parent._on_wake_word_callback(event)

            sink = _Sink(self)
            if isinstance(self.microphone, RealMicrophone):
                self.microphone.start()

            start_time = asyncio.get_event_loop().time()
            while self._is_listening:
                if asyncio.get_event_loop().time() - start_time > timeout_seconds:
                    self.logger.warning(f"Listen timeout after {timeout_seconds}s")
                    break
                await asyncio.sleep(0.1)

            if isinstance(self.microphone, RealMicrophone):
                self.microphone.stop()

            if not audio_frames:
                self.logger.debug("No audio frames captured")
                self.state = VoiceState.IDLE
                return None

            combined_data = b"".join(f.data for f in audio_frames)
            audio_frame = audio_frames[0]
            audio_frame.data = combined_data

            if self.speech_to_text_engine is None:
                self.logger.warning("No speech-to-text engine configured")
                self.state = VoiceState.IDLE
                return None

            self.state = VoiceState.PROCESSING
            text = await asyncio.to_thread(self.speech_to_text_engine.transcribe, audio_frame)
            self.state = VoiceState.IDLE

            if text and self._on_text_callback:
                self._on_text_callback(text)

            return text
        except Exception as e:
            self.logger.error(f"Listen error: {e}")
            self.state = VoiceState.IDLE
            return None
        finally:
            self._is_listening = False

    async def speak(self, text: str) -> bool:
        """Synthesize and play text-to-speech output."""
        if self.text_to_speech_engine is None:
            self.logger.warning("No text-to-speech engine configured")
            return False

        try:
            self.state = VoiceState.SPEAKING
            audio_frame = await asyncio.to_thread(self.text_to_speech_engine.synthesize, text)
            self.state = VoiceState.IDLE
            self.logger.debug(f"Synthesized {len(audio_frame.data)} bytes of audio")
            return True
        except Exception as e:
            self.logger.error(f"Speak error: {e}")
            self.state = VoiceState.IDLE
            return False

    def stop(self) -> None:
        """Stop listening and reset the voice system."""
        self._is_listening = False
        self._interrupt_flag = True
        if isinstance(self.microphone, RealMicrophone):
            self.microphone.stop()
        self.state = VoiceState.IDLE
        self.logger.debug("Voice system stopped")

    def pause(self) -> None:
        """Pause the voice system."""
        self._is_listening = False
        self.state = VoiceState.PAUSED
        self.logger.debug("Voice system paused")

    def resume(self) -> None:
        """Resume the voice system from a paused state."""
        if self.state == VoiceState.PAUSED:
            self.state = VoiceState.IDLE
            self.logger.debug("Voice system resumed")

    def on_text(self, callback: Callable[[str], None]) -> None:
        """Register a callback for transcribed text."""
        self._on_text_callback = callback

    def on_wake_word(self, callback: Callable[[WakeWordEvent], None]) -> None:
        """Register a callback for wake-word detection."""
        self._on_wake_word_callback = callback

    def get_state(self) -> str:
        """Return the current voice system state."""
        return self.state.value
