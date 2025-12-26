"""
DEPRECATED: This module is deprecated. Use ai_workflows.service instead.

All functionality has been consolidated into ChatAssistant in service.py.
"""
import warnings

from ai_workflows.service import ChatAssistant, get_chatbot_response

warnings.warn(
    "ai_workflows.agents is deprecated. Use ai_workflows.service instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export for backwards compatibility
__all__ = ["ChatAssistant", "get_chatbot_response"]
