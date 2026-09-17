"""
AI Product Ops Research System - LLM Client Abstraction
========================================================
Flexible LLM provider abstraction supporting OpenAI-compatible endpoints,
Google Gemini API, or fallback deterministic extraction when running without API keys.
Configured strictly via environment variables (no hardcoded keys).
"""

import json
import logging
import os
import re
from typing import Dict, Any, Optional
import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("agent.llm_client")


class LLMClient:
    """Configurable LLM client for structured schema extraction."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = (
            api_key
            or os.getenv("LLM_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        self.model = model or os.getenv("LLM_MODEL") or "gemini-2.5-flash"
        self.base_url = base_url or os.getenv("LLM_BASE_URL")

    @property
    def is_configured(self) -> bool:
        """Return True if an API key is configured."""
        return bool(self.api_key and self.api_key.strip())

    def call_llm(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """Invoke LLM endpoint if configured.

        Supports standard OpenAI-compatible completions format.
        """
        if not self.is_configured:
            logger.info("No LLM API key configured. Using deterministic extraction.")
            return None

        # Determine endpoint
        url = self.base_url or "https://api.openai.com/v1/chat/completions"
        if "generativelanguage.googleapis.com" in url or (not self.base_url and os.getenv("GEMINI_API_KEY")):
            # Gemini OpenAI-compatible endpoint
            url = f"https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"]
            else:
                logger.warning(f"LLM API returned status {response.status_code}: {response.text}")
                return None
        except Exception as e:
            logger.warning(f"Failed to call LLM: {e}")
            return None