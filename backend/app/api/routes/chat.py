from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query

from app.api.deps import Services, services
from app.schemas.chat import ChatAnswer, ChatContext, ChatRequest, TodayFeed

router = APIRouter(prefix="/api")
Svc = Annotated[Services, Depends(services)]


@router.post("/chat")
async def chat(svc: Svc, req: Annotated[ChatRequest, Body()]) -> ChatAnswer:
    """Answer a question from the app's own data. Each answer names the tool that produced it
    and the facts it rests on; the language model may only rephrase what the engine computed."""
    return await svc.chat.ask(req)


@router.get("/chat/starters")
async def starters(
    svc: Svc,
    path: Annotated[str | None, Query(max_length=200)] = None,
    symbol: Annotated[str | None, Query(max_length=40)] = None,
) -> list[str]:
    """Questions worth asking from where the user is standing."""
    return svc.chat.starters(ChatContext(path=path, symbol=symbol))


@router.get("/today")
async def today(svc: Svc) -> TodayFeed:
    """What deserves attention right now, and the user's progress through the basics."""
    return await svc.today.feed()
