"""
Groq client
===========
Thin async wrapper around Groq's OpenAI-compatible `/chat/completions`
endpoint (https://api.groq.com/openai/v1). This is the ONLY place that
knows how to talk to Groq — agents call `GroqClient.complete(...)` and
never touch httpx/env vars directly, so swapping providers later means
editing one file.

Design choices that matter for an emergency-response pipeline:
  - Fails soft. If GROQ_API_KEY isn't set, or the request errors out
    (network blip, rate limit, timeout), `complete()` returns None
    instead of raising. Every call site is expected to fall back to its
    existing deterministic logic — an LLM hiccup must never take down
    mission planning.
  - No decision-making here. This client returns text/JSON; whether
    that output is trusted for anything safety-critical is a decision
    each agent makes explicitly (see base_agent.BaseAgent._think).
  - Small, focused surface: one `complete()` method, optional JSON mode.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

import httpx
from dotenv import load_dotenv

# Loads backend/.env (or project-root .env) if present. Safe to call
# more than once; no-ops if the file doesn't exist or vars are already set.
load_dotenv()

logger = logging.getLogger("reliefmesh.llm.groq")

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
# openai/gpt-oss-120b is Groq's current recommended general-purpose model
# (llama-3.3-70b-versatile is deprecated). Override with GROQ_MODEL.
DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_RETRIES = 2


class GroqClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("GROQ_API_KEY")
        self.model = model or os.getenv("GROQ_MODEL", DEFAULT_MODEL)
        self.base_url = (base_url or os.getenv("GROQ_API_BASE", DEFAULT_BASE_URL)).rstrip("/")
        self.timeout_seconds = timeout_seconds or float(
            os.getenv("GROQ_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        )
        self.max_retries = max_retries if max_retries is not None else int(
            os.getenv("GROQ_MAX_RETRIES", DEFAULT_MAX_RETRIES)
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 600,
    ) -> Optional[str]:
        """
        Returns the model's text (or, if json_mode=True, a JSON string)
        on success, or None if the client isn't configured or the call
        ultimately fails. Never raises for ordinary failure modes
        (missing key, timeout, HTTP error) — callers should treat None
        as "fall back to deterministic logic", not as an exception path.
        """
        if not self.is_configured:
            logger.info("groq_not_configured", extra={"reason": "GROQ_API_KEY unset"})
            return None

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"

        last_error: Optional[Exception] = None
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.post(url, headers=headers, json=payload)
                    if response.status_code == 429 or response.status_code >= 500:
                        last_error = RuntimeError(
                            f"groq_retryable_status status={response.status_code}"
                        )
                        logger.warning(
                            "groq_retryable_status",
                            extra={"status": response.status_code, "attempt": attempt},
                        )
                        continue
                    response.raise_for_status()
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
                except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                    last_error = exc
                    logger.warning(
                        "groq_call_failed",
                        extra={"attempt": attempt, "error": str(exc)},
                    )

        logger.error("groq_call_exhausted_retries", extra={"error": str(last_error)})
        return None

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 600,
    ) -> Optional[Dict[str, Any]]:
        """Convenience wrapper around complete(json_mode=True) that also
        parses the result. Returns None on failure OR unparsable output —
        callers should never assume a dict comes back."""
        raw = await self.complete(
            system_prompt,
            user_prompt,
            json_mode=True,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            logger.warning("groq_json_parse_failed", extra={"raw_preview": raw[:200]})
            return None


_client_singleton: Optional[GroqClient] = None


def get_groq_client() -> GroqClient:
    """Process-wide singleton so agents share one httpx config/env read
    instead of each constructing their own."""
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = GroqClient()
    return _client_singleton
