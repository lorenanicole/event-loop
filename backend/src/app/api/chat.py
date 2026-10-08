"""Chat, greeting, and conversation lifecycle endpoints."""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.executor import ChatExecutor, sse_event_formatter
from shared.database import get_db

router = APIRouter()


class ChatStreamRequest(BaseModel):
    """Request body for the SSE chat endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"message": "comedy in Pilsen this weekend"},
                {"message": "plant workshops in Logan Square, Humboldt Park"},
                {"message": "free jazz tonight"},
                {
                    "message": "anything else that night?",
                    "thread_id": "3f9a1c84-7b2e-4d51-9a6f-1e2d3c4b5a60",
                },
            ]
        }
    )

    message: str = Field(
        ...,
        max_length=2000,
        description="A natural-language question about Chicago events.",
    )
    thread_id: str | None = Field(
        None,
        description="Thread id from a previous `complete` frame. Omit to start a new chat.",
    )


@router.post(
    "/chat/{thread_id}/close",
    summary="End a conversation",
    description="Marks a conversation finished. Idempotent; unknown thread ids are ignored.",
    responses={
        200: {
            "content": {
                "application/json": {"example": {"thread_id": "6782dca6-...", "closed": True}}
            }
        }
    },
)
async def close_chat_thread(thread_id: str, db: AsyncSession = Depends(get_db)):
    from app.chat.threads import close_thread

    try:
        changed = await close_thread(db, thread_id)
    except Exception:
        changed = False
    return {"thread_id": thread_id, "closed": changed}


@router.get(
    "/chat/greeting",
    summary="The assistant's opening message",
    description="Returns the current persona greeting, live event suggestions, and Chicago facts.",
    responses={
        200: {
            "description": "Markdown, ready to render.",
            "content": {
                "application/json": {
                    "example": {
                        "name": "Loopara",
                        "greeting": "🏙️ **Loopara** here - your Chicago events guide...",
                    }
                }
            },
        }
    },
)
async def chat_greeting(db: AsyncSession = Depends(get_db)):
    from app.chat.persona import ASSISTANT_NAME, data_facts, greeting, whats_on_tonight

    try:
        tonight = await whats_on_tonight(db)
    except Exception:
        tonight = None

    try:
        counted = await data_facts(db)
    except Exception:
        counted = []

    return {
        "name": ASSISTANT_NAME,
        "greeting": greeting(tonight=tonight, extra_facts=counted),
    }


@router.post(
    "/chat",
    summary="Ask Loopara (streaming)",
    description=(
        "Natural-language event discovery streamed as Server-Sent Events. "
        "Pass a prior thread_id to continue a conversation. Chat threads are "
        "bounded by turn and provider-reported token budgets."
    ),
    tags=["Chat"],
    responses={
        200: {
            "description": "An SSE stream (`text/event-stream`) ending with a response and complete frame.",
            "content": {
                "text/event-stream": {
                    "example": (
                        'event: response\\ndata: {"event":"response","data":'
                        '{"message":"There is a free comedy open mic tonight.","tokens":312}}\\n\\n'
                        'event: complete\\ndata: {"event":"complete","data":'
                        '{"thread_id":"a3f...","tokens_used":312}}\\n\\n'
                    )
                }
            },
        }
    },
)
async def chat_endpoint(request: ChatStreamRequest):
    async def event_generator():
        executor = ChatExecutor()
        async for event in executor.execute(request.message, thread_id=request.thread_id):
            yield sse_event_formatter(event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
