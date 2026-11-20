"""
Configuration Module for DarGlobal + Wasalt Chatbot
Loads environment variables and provides centralized application settings.
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Automatically load .env file from project root
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


class Settings:
    """Application settings and configuration parameters."""

    # OpenRouter API Configuration
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    PRIMARY_MODEL: str = os.getenv("PRIMARY_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    FALLBACK_MODEL: str = os.getenv("FALLBACK_MODEL", "qwen/qwen-2.5-72b-instruct:free")

    # Vector Database & Embeddings
    _raw_chroma_dir = os.getenv("CHROMA_PERSIST_DIRECTORY", "data/chroma")
    if Path(_raw_chroma_dir).is_absolute():
        CHROMA_PERSIST_DIRECTORY: str = _raw_chroma_dir
    else:
        CHROMA_PERSIST_DIRECTORY: str = str((Path(__file__).resolve().parent.parent / _raw_chroma_dir).resolve())
    COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "property_documents")
    EMBEDDING_MODEL_NAME: str = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")

    # Retrieval & RAG Parameters
    TOP_K: int = int(os.getenv("TOP_K", "5"))
    TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.2"))
    MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "1024"))
    REQUEST_TIMEOUT: float = float(os.getenv("REQUEST_TIMEOUT", "30.0"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))

    # Server Configuration
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    @classmethod
    def is_llm_configured(cls) -> bool:
        """Check if a valid non-placeholder OpenRouter key is provided."""
        key = cls.OPENROUTER_API_KEY.strip()
        return bool(key) and key != "your_openrouter_api_key_here"


settings = Settings()
