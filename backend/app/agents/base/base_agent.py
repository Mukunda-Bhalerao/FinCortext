"""Base agent interface.

All agents implement `analyze(symbol) -> AgentOutput` and share persistence
behavior through the AgentOutputRepository.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models.agent_output import AgentId, AgentOutput
from app.repositories.agent_output_repository import AgentOutputRepository


class BaseAgent(ABC):
    """Common agent plumbing: id, persistence, run-and-record."""

    agent_id: AgentId

    def __init__(self, output_repo: AgentOutputRepository | None = None):
        self._output_repo = output_repo

    @abstractmethod
    def analyze(self, symbol: str) -> AgentOutput:
        """Produce a standardized AgentOutput for `symbol`."""
        raise NotImplementedError

    def run(self, symbol: str, *, persist: bool = True, **kwargs) -> AgentOutput:
        """Analyze and (optionally) persist the output.

        Extra keyword arguments are forwarded to `analyze` so orchestration
        layers can pass run context (e.g. Industry Analyst data-preparation
        summaries) without coupling every agent to them.
        """
        output = self.analyze(symbol, **kwargs)
        if persist and self._output_repo is not None:
            self._output_repo.save(output)
        return output