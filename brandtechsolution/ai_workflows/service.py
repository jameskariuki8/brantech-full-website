"""
ChatAssistant service following LangChain official patterns.
See: https://docs.langchain.com/oss/python/langchain/quickstart
"""
from typing import Optional, TypedDict, List
from dataclasses import dataclass
import logging
import os
import re

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, trim_messages
from langchain_core.messages.utils import count_tokens_approximately

from ai_workflows.checkpointer import DjangoCheckpointer
from ai_workflows.tools import search_blog_posts, search_projects, create_user_info_tool
from brandtechsolution.config import config

logger = logging.getLogger(__name__)


def _set_external_environment():
    """Expose select configuration values to libraries that read from os.environ."""
    env_overrides = {
        'GOOGLE_API_KEY': config.google_api_key,
        'LANGSMITH_TRACING': config.langsmith_tracing,
        'LANGSMITH_API_KEY': config.langsmith_api_key,
        'LANGSMITH_PROJECT': config.langsmith_project,
    }
    for key, value in env_overrides.items():
        if value is not None:
            os.environ[key] = str(value)


_set_external_environment()


# System prompt following official docs pattern
SYSTEM_PROMPT = """You are a helpful assistant for BranTech Solutions, a web development and digital innovation company.

You can help users with:
- Information about our services and solutions
- Details about our blog posts and articles
- Information about our completed projects
- General questions about web development and technology

## Available Tools

You have access to these tools:
1. **search_blog_posts**: Search our blog for articles about services, technologies, or topics
2. **search_projects**: Search our completed projects for examples of our work

## Guidelines

- Be friendly, professional, and helpful
- Use tools when users ask about specific blog content or projects
- If you don't know something, say so and offer to help find the information
- Keep responses concise but informative
"""


class AssistantResponse(TypedDict):
    """Response structure from the assistant."""
    response: str
    suggested_questions: List[str]


@dataclass
class ChatContext:
    """Runtime context for the chat assistant."""
    user_id: Optional[int] = None
    is_authenticated: bool = False


class ChatAssistant:
    """
    ChatAssistant following LangChain official patterns.
    
    Usage:
        assistant = ChatAssistant(thread_id="unique_thread_id")
        response = assistant.send_message("Hello!")
        print(response["response"])
    """

    MAX_TOKENS_FOR_TRIMMING = 2000

    def __init__(
        self,
        thread_id: str,
        user_id: Optional[int] = None,
        use_tools: bool = True,
    ):
        """
        Initialize the ChatAssistant.
        
        Args:
            thread_id: Required unique identifier for this conversation
            user_id: Optional user ID if authenticated
            use_tools: Whether to enable RAG tools (default True)
        """
        self.thread_id = thread_id
        self.user_id = user_id
        
        # Build config following official docs pattern
        self.config = {
            "configurable": {"thread_id": thread_id},
            "workflow_type": "chatbot",
        }
        if user_id:
            self.config["user_id"] = user_id
        
        # Initialize components
        self.checkpointer = DjangoCheckpointer(thread_id)
        self.model = ChatGoogleGenerativeAI(
            model=config.gemini_chat_model,
            google_api_key=config.google_api_key,
        )
        
        # Collect tools
        self.tools = []
        if use_tools:
            self.tools = [search_blog_posts, search_projects]
            
            # Add user info tool if user_id is present
            if self.user_id:
                self.tools.append(create_user_info_tool(self.user_id))
        
        # Create the agent
        self._create_agent()

    def _create_agent(self):
        """Create the LangChain agent with middleware."""
        
        # Message trimming middleware following WozapAuto pattern
        @wrap_model_call
        def trim_message_history(
            request: ModelRequest,
            handler
        ) -> ModelResponse:
            """Trim message history to fit within token limit before model call."""
            messages = request.messages
            if not messages:
                return handler(request)

            trimmed = trim_messages(
                messages=messages,
                max_tokens=self.MAX_TOKENS_FOR_TRIMMING,
                token_counter=count_tokens_approximately,
                strategy="last",
                allow_partial=True,
                include_system=True,
                start_on="human",
                end_on=["human", "tool", "ai"],
            )

            if len(trimmed) != len(messages):
                logger.info(
                    f"Trimmed messages from {len(messages)} to {len(trimmed)} for model call"
                )
                modified_request = request.override(messages=trimmed)
                return handler(modified_request)
            
            return handler(request)

        # Create agent following official docs pattern
        self.app = create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=SYSTEM_PROMPT,
            middleware=[trim_message_history],
            checkpointer=self.checkpointer,
        )

    def send_message(self, message: str) -> AssistantResponse:
        """
        Send a message to the assistant and get a response.
        
        Args:
            message: The user's message
            
        Returns:
            AssistantResponse with response text and suggested questions
        """
        try:
            output = self.app.invoke(
                {"messages": [HumanMessage(content=message)]},
                self.config,
            )
            
            # Extract response from messages
            messages = output.get("messages", [])
            content = ""
            if messages:
                last = messages[-1]
                if hasattr(last, "content"):
                    content = last.content
                elif isinstance(last, dict):
                    content = last.get("content", str(last))
                else:
                    content = str(last)
            
            # Handle list of content objects (Gemini raw format)
            if isinstance(content, list):
                # Extract text from list of dicts if found
                text_parts = []
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        text_parts.append(part["text"])
                    elif isinstance(part, str):
                        text_parts.append(part)
                if text_parts:
                    content = "\n".join(text_parts)
                else:
                    # Fallback for unknown list structure
                    content = str(content)
            
            return {
                "response": content,
                "suggested_questions": [],
            }
            
        except Exception as e:
            logger.error(f"Error in send_message: {e}", exc_info=True)
            return {
                "response": "I apologize, but I encountered an error processing your message. Please try again.",
                "suggested_questions": [],
            }

    def _extract_content_from_stringified(self, msg_str: str) -> Optional[str]:
        """
        Extract content from a stringified LangChain message object.
        
        Handles formats like:
        - content='Hello' additional_kwargs={} ...
        - content=[{'type': 'text', 'text': 'Hello...'}] ...
        
        Returns:
            Extracted content string, or None if parsing fails
        """
        # Try to extract content from stringified message
        # Pattern 1: content='simple string'
        match = re.search(r"content='([^']*)'", msg_str)
        if match:
            return match.group(1)
        
        # Pattern 2: content=[{'type': 'text', 'text': '...'}]
        # Look for the text field inside the list
        match = re.search(r"'text':\s*'([^']*)'", msg_str)
        if match:
            return match.group(1)
        
        # Pattern 3: content="" (empty)
        if "content=''" in msg_str or 'content=""' in msg_str:
            return ""
        
        return None

    def _get_role_from_stringified(self, msg_str: str) -> str:
        """
        Determine role from a stringified message.
        
        Returns:
            'user' or 'assistant'
        """
        if msg_str.startswith("HumanMessage") or "HumanMessage(" in msg_str:
            return "user"
        if msg_str.startswith("AIMessage") or "AIMessage(" in msg_str:
            return "assistant"
        # Check for tool calls (AI messages with function_call)
        if "function_call" in msg_str or "tool_calls" in msg_str:
            return "assistant"
        # Default to user for simple content messages
        return "user"

    def get_history(self) -> List[dict]:
        """
        Get conversation history for this thread.
        
        Returns:
            List of message dicts with role and content
        """
        try:
            checkpoint = self.checkpointer.get_tuple(self.config)
            if not checkpoint:
                return []
            
            messages = checkpoint.checkpoint.get("channel_values", {}).get("messages", [])
            history = []
            
            for msg in messages:
                content = None
                role = "user"
                
                # Handle LangChain message objects (shouldn't happen after serialization, but just in case)
                if hasattr(msg, "content"):
                    role = "assistant" if isinstance(msg, AIMessage) else "user"
                    content = msg.content
                
                # Handle proper dict format (new format after fix)
                elif isinstance(msg, dict):
                    msg_type = msg.get("type", msg.get("role", "unknown"))
                    if msg_type in ("human", "user"):
                        role = "user"
                    elif msg_type in ("ai", "assistant"):
                        role = "assistant"
                    else:
                        role = "user"
                    content = msg.get("content", "")
                
                # Handle stringified message objects (legacy data)
                elif isinstance(msg, str):
                    role = self._get_role_from_stringified(msg)
                    content = self._extract_content_from_stringified(msg)
                    if content is None:
                        # Skip messages we can't parse
                        continue
                
                # Skip empty content or tool call messages
                if content is None or content == "":
                    continue
                
                # Handle list content (Gemini format)
                if isinstance(content, list):
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and "text" in part:
                            text_parts.append(part["text"])
                        elif isinstance(part, str):
                            text_parts.append(part)
                    content = "\n".join(text_parts) if text_parts else None
                    if content is None:
                        continue
                
                # Skip error messages that shouldn't be in conversation history
                # These are tool errors that got stored incorrectly
                content_str = str(content).lower()
                if any(indicator in content_str for indicator in [
                    "error searching",
                    "error embedding",
                    "resource_exhausted",
                    "429 resource_exhausted",
                    "quota exceeded",
                    "error:",
                ]):
                    # Skip this message - it's a tool error, not a real message
                    continue
                
                history.append({"role": role, "content": content})
            
            return history
            
        except Exception as e:
            logger.error(f"Error getting history: {e}", exc_info=True)
            return []


# Convenience function for simple usage (backwards compatibility)
def get_chatbot_response(
    message: str,
    thread_id: str,
    user_id: Optional[int] = None,
) -> dict:
    """
    Get chatbot response for a message.
    
    This is a convenience function that creates a ChatAssistant instance
    and sends a single message.
    
    Args:
        message: User message
        thread_id: Thread ID for conversation
        user_id: Optional user ID
        
    Returns:
        Dict with response and metadata
    """
    assistant = ChatAssistant(thread_id=thread_id, user_id=user_id)
    result = assistant.send_message(message)
    
    return {
        "response": result["response"],
        "thread_id": thread_id,
        "metadata": {
            "suggested_questions": result.get("suggested_questions", []),
        },
    }
