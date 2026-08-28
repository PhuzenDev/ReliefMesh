"""
Common agent scaffolding. Every ReliefMesh agent gets a name, a logger,
and a uniform async `run` entrypoint so the orchestrator can treat all
five agents interchangeably and so every decision can be mirrored into
the audit store later without each agent reinventing logging.

Agents that want an LLM-backed reasoning step (Groq, via app.llm) get it
through `_think` / `_think_json` below rather than importing the Groq
client directly, so:
  - there's one shared, testable seam to mock in unit tests,
  - every LLM call is uniformly logged and never raises into agent
    logic (it returns None on failure — see app.llm.groq_client),
  - deterministic pipeline logic stays authoritative; the LLM is always
    an optional add-on an agent explicitly chooses to use for narrative
    or soft-signal extraction, never for the underlying feasible/
    infeasible or allocation decision itself.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from app.llm import get_groq_client


class BaseAgent(ABC):
    name: str = "base_agent"

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"reliefmesh.agents.{self.name}")
        self.llm = get_groq_client()

    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> Any:
        """Each agent implements its core step here."""
        raise NotImplementedError

    def _log_decision(self, message: str, **context: Any) -> None:
        """
        Structured log line. The orchestrator's audit store hook can
        subscribe to a logging.Handler on the 'reliefmesh.agents' logger
        tree to persist every decision without agents knowing about the DB.
        """
        self.logger.info(message, extra={"agent": self.name, **context})

    async def _think(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 600,
    ) -> Optional[str]:
        """Ask Groq for free-text reasoning. Returns None (never raises)
        if GROQ_API_KEY isn't set or the call fails — always pair this
        with a deterministic fallback in the caller."""
        if not self.llm.is_configured:
            return None
        result = await self.llm.complete(
            system_prompt, user_prompt, temperature=temperature, max_tokens=max_tokens
        )
        self._log_decision(
            "llm_think",
            used_llm=result is not None,
            model=self.llm.model if result is not None else None,
        )
        return result

    async def _think_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 600,
    ) -> Optional[Dict[str, Any]]:
        """Same as `_think` but parses a JSON object out of the response.
        Returns None if unconfigured, the call fails, or parsing fails."""
        if not self.llm.is_configured:
            return None
        result = await self.llm.complete_json(
            system_prompt, user_prompt, temperature=temperature, max_tokens=max_tokens
        )
        self._log_decision(
            "llm_think_json",
            used_llm=result is not None,
            model=self.llm.model if result is not None else None,
        )
        return result