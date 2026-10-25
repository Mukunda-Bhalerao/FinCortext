from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import Services, services
from app.schemas.insights import AIStatus, AskAnswer, AskRequest

router = APIRouter(prefix="/api/assistant")
Svc = Annotated[Services, Depends(services)]


@router.get("/status")
async def status(svc: Svc) -> AIStatus:
    return svc.assistant.status()


@router.post("/ask")
async def ask(svc: Svc, req: AskRequest) -> AskAnswer:
    """Answer a question from computed facts only, citing them; may propose a scenario."""
    return await svc.assistant.ask(req)
