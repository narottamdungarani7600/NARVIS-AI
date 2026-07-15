"""Public intelligent context API for the NARVIS Conversation engine."""

from .context_manager import (
    ConversationContextManager,
    IntelligentContextManager,
    MemoryReferenceReader,
    NamedReferenceReader,
)
from .exceptions import (
    ContextServiceValidationError,
    ConversationContextError,
    ReferenceNotFoundError,
    ReferenceValidationError,
    SearchValidationError,
    SummaryGenerationError,
    TopicDetectionError,
    WindowValidationError,
)
from .models import (
    ContextReferences,
    ContextStatistics,
    ConversationSearchResult,
    ConversationSummary,
    ConversationWindow,
    SearchMatch,
    SearchMode,
    TopicDetection,
)
from .search import ConversationSearch, MessageSearch
from .summary import (
    ConversationSummarizer,
    ExtractiveConversationSummarizer,
    SummaryGenerator,
)
from .topic import ConversationTopicDetector, KeywordTopicDetector, TopicDetector
from .window import ConversationWindowManager, WindowManager

__all__ = [
    "ContextReferences",
    "ContextServiceValidationError",
    "ContextStatistics",
    "ConversationContextError",
    "ConversationContextManager",
    "ConversationSearch",
    "ConversationSearchResult",
    "ConversationSummarizer",
    "ConversationSummary",
    "ConversationTopicDetector",
    "ConversationWindow",
    "ConversationWindowManager",
    "ExtractiveConversationSummarizer",
    "IntelligentContextManager",
    "KeywordTopicDetector",
    "MemoryReferenceReader",
    "MessageSearch",
    "NamedReferenceReader",
    "ReferenceNotFoundError",
    "ReferenceValidationError",
    "SearchMatch",
    "SearchMode",
    "SearchValidationError",
    "SummaryGenerationError",
    "SummaryGenerator",
    "TopicDetection",
    "TopicDetectionError",
    "TopicDetector",
    "WindowManager",
    "WindowValidationError",
]
