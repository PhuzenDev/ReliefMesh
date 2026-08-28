"""
Common agent scaffolding. Every ReliefMesh agent gets a name, a logger,
and a uniform async `run` entrypoint so the orchestrator can treat all
five agents interchangeably and so every decision can be mirrored into
the audit store later without each agent reinventing logging.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    name: str = "base_agent"

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"reliefmesh.agents.{self.name}")

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