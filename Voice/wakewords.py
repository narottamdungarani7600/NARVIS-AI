"""Backward-compatible wake-word exports for older Voice imports."""

from .wakeword import KeywordWakeWordDetector, PorcupineWakeWordDetector

__all__ = ["KeywordWakeWordDetector", "PorcupineWakeWordDetector"]
