"""Agent endpoints — thin handlers over AgentService."""

from __future__ import annotations

from fastapi import APIRouter

from app.services.container import get_container

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post("/{agent_id}/{symbol}/run")
def run_agent(agent_id: str, symbol: str) -> dict:
    """Run an implemented agent and persist the output.

    Firm/Industry/Sentiment return the standardized AgentOutput; Macro
    returns the market-wide MacroOutput; Portfolio runs all four analysts
    for the symbol and returns the synthesis view. Unimplemented agents
    are rejected with an explicit 404 domain error — never fake results.
    """
    container = get_container()
    output = container.agent_service.run_agent(agent_id, symbol)
    return output.model_dump()


@router.get("/outputs")
def list_outputs(agent_id: str | None = None, symbol: str | None = None, limit: int = 50) -> dict:
    """Agent output history (standardized contract, persisted)."""
    container = get_container()
    rows = container.agent_service.list_outputs(agent_id, symbol, limit)
    return {"count": len(rows), "outputs": rows}