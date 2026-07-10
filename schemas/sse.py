"""
Schemas para el protocolo SSE (Server-Sent Events).
Define los tipos de evento que el backend emite al frontend en streaming.
"""
from pydantic import BaseModel, Field
from typing import Optional, Literal
from uuid import uuid4
import json


class SSEEvent(BaseModel):
    """Modelo canónico de un evento SSE emitido por un agente."""
    event_type: Literal["thinking", "tool_call", "token", "error", "done"]
    data: dict

    def to_sse(self) -> str:
        """Serializa el evento al formato SSE estándar (text/event-stream)."""
        payload = json.dumps(self.data, ensure_ascii=False)
        return f"event: {self.event_type}\ndata: {payload}\n\n"


class StreamChatRequest(BaseModel):
    """Request body para el endpoint de chat con streaming."""
    message: str = Field(..., min_length=1, max_length=2000)
    history: Optional[list[dict]] = Field(default_factory=list)
    session_id: Optional[str] = Field(default_factory=lambda: str(uuid4()))
