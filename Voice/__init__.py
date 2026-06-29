"""Voice package for NARVIS.

This package provides reusable abstractions for microphone input, wake-word
recognition, speech-to-text, text-to-speech, and listener/speaker orchestration.
"""

from .audio import AudioFormat, AudioFrame, AudioSink
from .engines import (
    GoogleSpeechRecognitionEngine,
    Pyttsx3TextToSpeechEngine,
    RealSpeechToTextEngine,
    RealTextToSpeechEngine,
)
from .listener import Listener, VoiceListener
from .manager import VoiceQueue, VoiceSessionManager, VoiceState, VoiceSystemManager
from .microphone import AudioCaptureSession, BaseMicrophone, Microphone, NullMicrophone
from .realmic import RealMicrophone, VoiceActivityDetector
from .speaker import Speaker, VoiceSpeaker
from .speech import (
    BaseSpeechToTextEngine,
    BaseTextToSpeechEngine,
    PassthroughSpeechToText,
    PassthroughTextToSpeech,
    SpeechToTextEngine,
    TextToSpeechEngine,
)
from .wakeword import BaseWakeWordDetector, NullWakeWordDetector, WakeWordDetector, WakeWordEvent
from .wakewords import KeywordWakeWordDetector, PorcupineWakeWordDetector

__all__ = [
    "AudioCaptureSession",
    "AudioFormat",
    "AudioFrame",
    "AudioSink",
    "BaseMicrophone",
    "BaseSpeechToTextEngine",
    "BaseTextToSpeechEngine",
    "BaseWakeWordDetector",
    "GoogleSpeechRecognitionEngine",
    "KeywordWakeWordDetector",
    "Listener",
    "Microphone",
    "NullMicrophone",
    "NullWakeWordDetector",
    "PassthroughSpeechToText",
    "PassthroughTextToSpeech",
    "PorcupineWakeWordDetector",
    "Pyttsx3TextToSpeechEngine",
    "RealMicrophone",
    "RealSpeechToTextEngine",
    "RealTextToSpeechEngine",
    "Speaker",
    "SpeechToTextEngine",
    "TextToSpeechEngine",
    "VoiceActivityDetector",
    "VoiceListener",
    "VoiceQueue",
    "VoiceSessionManager",
    "VoiceSpeaker",
    "VoiceState",
    "VoiceSystemManager",
    "WakeWordDetector",
    "WakeWordEvent",
]
