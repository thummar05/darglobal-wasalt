"""
LLM Client Wrapper for OpenRouter with Fallback Chain
Dispatches all user prompts and grounded context directly to the LLM.
No pre-defined or hard-coded outputs.
"""

import logging
from typing import List, Optional
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


def create_llm_chain():
    """
    Construct the primary ChatOpenAI model linked with a fallback model.
    Falls back gracefully if primary model encounters rate limits (429) or 5xx errors.
    """
    headers = {
        "HTTP-Referer": "https://github.com/darglobal/realestate-chatbot",
        "X-Title": "DarGlobal Wasalt Real Estate Advisor"
    }

    # Primary Model (Llama 3.3 70B Free)
    primary_llm = ChatOpenAI(
        model=settings.PRIMARY_MODEL,
        openai_api_key=settings.OPENROUTER_API_KEY or "dummy_key",
        openai_api_base=settings.OPENROUTER_BASE_URL,
        temperature=settings.TEMPERATURE,
        max_tokens=settings.MAX_TOKENS,
        timeout=settings.REQUEST_TIMEOUT,
        max_retries=settings.MAX_RETRIES,
        default_headers=headers
    )

    # Fallback Model (Qwen 2.5 72B Free)
    fallback_llm = ChatOpenAI(
        model=settings.FALLBACK_MODEL,
        openai_api_key=settings.OPENROUTER_API_KEY or "dummy_key",
        openai_api_base=settings.OPENROUTER_BASE_URL,
        temperature=settings.TEMPERATURE,
        max_tokens=settings.MAX_TOKENS,
        timeout=settings.REQUEST_TIMEOUT,
        max_retries=settings.MAX_RETRIES,
        default_headers=headers
    )

    # Chain with automatic fallback
    return primary_llm.with_fallbacks([fallback_llm])


class ResilientLLM:
    """
    Direct LLM invoker.
    All user requests go directly to the LLM chain.
    No hardcoded, static, or pre-defined canned outputs.
    """

    def __init__(self):
        self.chain = None
        self._init_chain()

    def _init_chain(self):
        try:
            self.chain = create_llm_chain()
            logger.info(
                f"✓ LLM Chain initialized (Primary: {settings.PRIMARY_MODEL}, Fallback: {settings.FALLBACK_MODEL})"
            )
        except Exception as e:
            logger.error(f"Failed to initialize LLM chain: {e}")
            self.chain = None

    def invoke(self, messages: List[BaseMessage], context_docs: Optional[List[dict]] = None) -> str:
        """
        Directly invoke the LLM with messages.
        All generation is performed by the LLM adhering to the system prompt guardrails.
        """
        if not self.chain:
            self._init_chain()

        if not self.chain:
            return "LLM service is not initialized. Please verify your OpenRouter configuration in .env."

        try:
            response = self.chain.invoke(messages)
            if hasattr(response, "content") and response.content:
                return response.content
            return str(response)
        except Exception as e:
            logger.error(f"Error during LLM invocation: {e}", exc_info=True)
            return (
                f"An error occurred while generating the response from the language model: {e}. "
                "Please ensure a valid OPENROUTER_API_KEY is configured in your .env file."
            )
