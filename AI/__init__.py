"""AI package for NARVIS."""

from .brain import BrainEngine
from .conversation import ChatHistoryManager, ConversationManager, SessionManager
from .context import ConversationContext, InMemoryContextManager
from .intent import IntentAnalyzer, IntentClassification, IntentType, RuleBasedIntentClassifier
from .prompts import PromptBuilder
from .providers import ClaudeProvider, GeminiProvider, OllamaProvider, OpenAIProvider, Provider, ProviderFactory
from .response import BrainResponse, ResponseBuilder
from .router import IntentRouter, ModuleRoute

__all__ = [
    "BrainEngine",
    "BrainResponse",
    "ChatHistoryManager",
    "ClaudeProvider",
    "ConversationContext",
    "ConversationManager",
    "GeminiProvider",
    "InMemoryContextManager",
    "IntentAnalyzer",
    "IntentClassification",
    "IntentRouter",
    "IntentType",
    "ModuleRoute",
    "OllamaProvider",
    "OpenAIProvider",
    "PromptBuilder",
    "Provider",
    "ProviderFactory",
    "ResponseBuilder",
    "RuleBasedIntentClassifier",
    "SessionManager",
]
