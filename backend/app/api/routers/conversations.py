import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.conversation.graph import answer
from app.agents.conversation.tools import ConversationContext
from app.db.models import Conversation, Message
from app.db.session import AsyncSessionLocal, get_session
from app.schemas.conversation import (
    ConversationCreate,
    ConversationDetailOut,
    ConversationOut,
    MessageCreate,
    MessageOut,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.post("", response_model=ConversationOut, status_code=201)
async def create(body: ConversationCreate, session: AsyncSession = Depends(get_session)):
    conversation = Conversation(experiment_id=body.experiment_id, title=body.title)
    session.add(conversation)
    await session.flush()
    return conversation


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    experiment_id: uuid.UUID | None = Query(None), session: AsyncSession = Depends(get_session)
):
    stmt = select(Conversation).order_by(Conversation.created_at.desc())
    if experiment_id:
        stmt = stmt.where(Conversation.experiment_id == experiment_id)
    return (await session.execute(stmt)).scalars().all()


@router.get("/{conversation_id}", response_model=ConversationDetailOut)
async def get_conversation(
    conversation_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    messages = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
    ).scalars().all()
    return ConversationDetailOut(
        id=conversation.id, experiment_id=conversation.experiment_id,
        title=conversation.title, created_at=conversation.created_at,
        messages=[MessageOut.model_validate(m) for m in messages],
    )


@router.post("/{conversation_id}/messages", response_model=MessageOut)
async def post_message(
    conversation_id: uuid.UUID,
    body: MessageCreate,
    session: AsyncSession = Depends(get_session),
):
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    if conversation.experiment_id is None:
        raise HTTPException(
            status_code=400, detail="this conversation is not attached to an experiment"
        )

    prior = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
    ).scalars().all()

    session.add(Message(conversation_id=conversation_id, role="user", content=body.content))
    await session.flush()

    result = await answer(
        question=body.content,
        history=[{"role": m.role, "content": m.content} for m in prior],
        ctx=ConversationContext(
            experiment_id=conversation.experiment_id, session_factory=AsyncSessionLocal
        ),
    )

    # `view` is a viewer directive, not a lookup: it survives on the message so a
    # reloaded conversation can still put the images back where the answer left them.
    tool_calls: dict = {"used": result["tool_calls_made"]}
    if result.get("view"):
        tool_calls["view"] = result["view"]

    reply = Message(
        conversation_id=conversation_id,
        role="assistant",
        content=result["content"],
        tool_calls=tool_calls,
    )
    session.add(reply)
    await session.flush()
    return reply
