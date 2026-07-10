"""
Antigravity Framework v2 — Event Bus con SSE Streaming.
Provee: Telemetry, SharedMemory, EventBus, SSEChannel, SSEManager, AgentGraph.
"""
import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Callable, Optional, Literal
from pydantic import BaseModel
from core.tracing import logger, log_audit_event, get_trace_id


# ---------------------------------------------------------------------------
# Telemetry (mejorada con trace_id)
# ---------------------------------------------------------------------------
class Telemetry(BaseModel):
    calls: int = 0
    total_latency_ms: float = 0.0
    success_calls: int = 0
    failed_calls: int = 0
    total_tokens: int = 0
    tokens_quota: int = 1000000  # Cuota por defecto (ej. 1 millón)
    token_percentage: float = 0.0

    def log(self, latency: float, success: bool, tokens: int, trace_id: str = ""):
        self.calls += 1
        self.total_latency_ms += latency
        if success:
            self.success_calls += 1
        else:
            self.failed_calls += 1
        self.total_tokens += tokens
        self.token_percentage = (self.total_tokens / self.tokens_quota) * 100.0 if self.tokens_quota > 0 else 0.0
        print(f"[METRICS] trace={trace_id} | Latency: {latency:.2f}ms | Success: {success} | Tokens: {tokens} ({self.token_percentage:.2f}%)")


telemetry_store = Telemetry()


# ---------------------------------------------------------------------------
# SharedMemory (sin cambios funcionales)
# ---------------------------------------------------------------------------
class SharedMemory:
    def __init__(self, name: str):
        self.name = name
        self.state: Dict[str, Any] = {
            "enrolled_students": {},
            "observed_students": {},
            "rejected_students": {},
            "profesores": {},
            "notas_trimestrales": {},
            "event_logs": [],
            "calendario_psicologia": [
                {"dia": "Lunes", "hora": "08:00 AM", "ocupado": False, "codigo_obs": None},
                {"dia": "Lunes", "hora": "10:00 AM", "ocupado": False, "codigo_obs": None},
                {"dia": "Martes", "hora": "09:00 AM", "ocupado": False, "codigo_obs": None},
                {"dia": "Miércoles", "hora": "08:00 AM", "ocupado": False, "codigo_obs": None},
                {"dia": "Jueves", "hora": "11:00 AM", "ocupado": False, "codigo_obs": None},
                {"dia": "Viernes", "hora": "09:00 AM", "ocupado": False, "codigo_obs": None}
            ]
        }
        self.lock = asyncio.Lock()

    async def get_state(self) -> Dict[str, Any]:
        async with self.lock:
            return self.state.copy()

    async def set_state(self, new_state: Dict[str, Any]):
        async with self.lock:
            self.state = new_state


# ---------------------------------------------------------------------------
# SSEChannel — Cola asíncrona por sesión para streaming de eventos
# ---------------------------------------------------------------------------
class SSEChannel:
    """Canal SSE individual. Cada sesión de chat tiene uno."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._closed: bool = False

    async def send(self, event_type: str, data: dict) -> None:
        """Envía un evento genérico al canal."""
        if not self._closed:
            await self.queue.put({"event": event_type, "data": data})

    async def send_token(self, content: str) -> None:
        """Envía un token de texto progresivo."""
        await self.send("token", {"content": content})

    async def send_thinking(self, agent: str, status: str = "reasoning") -> None:
        """Indica que un agente está razonando."""
        await self.send("thinking", {"agent": agent, "status": status})

    async def send_tool_call(self, agent: str, tool: str, args: Optional[dict] = None) -> None:
        """Indica que un agente está usando una herramienta."""
        await self.send("tool_call", {"agent": agent, "tool": tool, "args": args or {}})

    async def send_done(self, trace_id: str, finish_reason: str = "stop") -> None:
        """Señal de finalización del stream."""
        await self.send("done", {"finish_reason": finish_reason, "trace_id": trace_id})
        self._closed = True

    async def send_error(self, message: str) -> None:
        """Envía un error y cierra el canal."""
        await self.send("error", {"message": message})
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def __aiter__(self):
        return self

    async def __anext__(self) -> Dict[str, Any]:
        if self._closed and self.queue.empty():
            raise StopAsyncIteration
        try:
            event = await asyncio.wait_for(self.queue.get(), timeout=30.0)
            if event["event"] in ("done", "error"):
                self._closed = True
            return event
        except asyncio.TimeoutError:
            # Keepalive para evitar timeout del navegador
            return {"event": "ping", "data": {}}


# ---------------------------------------------------------------------------
# SSEManager — Gestiona canales activos y suscriptores globales
# ---------------------------------------------------------------------------
class SSEManager:
    """Singleton que gestiona todos los canales SSE activos."""

    def __init__(self):
        self._channels: Dict[str, SSEChannel] = {}
        self._global_subscribers: List[asyncio.Queue[Dict[str, Any]]] = []

    def create_channel(self, session_id: str) -> SSEChannel:
        """Crea un nuevo canal SSE para una sesión."""
        channel = SSEChannel(session_id)
        self._channels[session_id] = channel
        return channel

    def get_channel(self, session_id: str) -> Optional[SSEChannel]:
        """Obtiene un canal existente por session_id."""
        return self._channels.get(session_id)

    def remove_channel(self, session_id: str) -> None:
        """Elimina un canal finalizado."""
        self._channels.pop(session_id, None)

    def subscribe_global(self) -> asyncio.Queue[Dict[str, Any]]:
        """Suscribe un cliente al feed global de eventos (alertas, etc.)."""
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._global_subscribers.append(queue)
        return queue

    def unsubscribe_global(self, queue: asyncio.Queue[Dict[str, Any]]) -> None:
        """Desuscribe un cliente del feed global."""
        self._global_subscribers = [q for q in self._global_subscribers if q is not queue]

    async def broadcast_global(self, event_type: str, data: dict) -> None:
        """Emite un evento a todos los suscriptores globales."""
        for queue in self._global_subscribers:
            await queue.put({"event": event_type, "data": data})


# ---------------------------------------------------------------------------
# EventBus v2 — Ahora también emite al SSEManager
# ---------------------------------------------------------------------------
class EventBus:
    def __init__(self, name: str, memory: SharedMemory, sse_manager: Optional[SSEManager] = None):
        self.name = name
        self.memory = memory
        self.sse_manager = sse_manager
        self.subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable):
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(callback)

    def set_sse_manager(self, manager: SSEManager) -> None:
        """Inyecta el SSEManager después de la construcción."""
        self.sse_manager = manager

    async def publish(self, event_type: str, data: Any):
        # Persistir en SharedMemory
        state = await self.memory.get_state()
        state["event_logs"].append(f"[{event_type}] {data}")
        await self.memory.set_state(state)
        
        logger.info(f"EventBus publish: {event_type}", extra={"event_type": event_type, "event_data": str(data)})

        # Notificar suscriptores internos
        if event_type in self.subscribers:
            for callback in self.subscribers[event_type]:
                asyncio.create_task(callback(data))

        # Broadcast a clientes SSE globales
        if self.sse_manager:
            await self.sse_manager.broadcast_global(
                event_type="bus_event",
                data={"bus_event_type": event_type, "payload": str(data)}
            )


# ---------------------------------------------------------------------------
# AgentGraph (mejorado con trace_id)
# ---------------------------------------------------------------------------
class AgentGraph:
    def __init__(self, topology: str):
        self.topology = topology
        self.nodes: List[Any] = []

    def add_nodes(self, nodes: List[Any]):
        self.nodes.extend(nodes)

    async def execute_node(self, agent: Any, payload: Dict[str, Any], trace_id: str = "") -> Any:
        start_time = time.time()
        
        # Usar el trace_id global si no se pasa uno específico
        actual_trace_id = trace_id or get_trace_id()
        logger.info(f"Executing Agent Node: {agent.name}", extra={"agent": agent.name, "trace_id": actual_trace_id})
        
        await asyncio.sleep(0.5)  # Simulate network latency
        try:
            result = await agent.run(payload)
            latency = (time.time() - start_time) * 1000
            telemetry_store.log(latency, success=True, tokens=150, trace_id=actual_trace_id)
            logger.info(f"Agent Node {agent.name} success", extra={"latency_ms": latency, "agent": agent.name})
            return result
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            telemetry_store.log(latency, success=False, tokens=50, trace_id=actual_trace_id)
            logger.error(f"Agent Node {agent.name} failed: {e}", extra={"latency_ms": latency, "agent": agent.name, "error": str(e)})
            raise e


# ---------------------------------------------------------------------------
# Singletons para inyección de dependencias
# ---------------------------------------------------------------------------
from core.vector_store import vector_store

school_db = SharedMemory(name="Base_Datos_Escolar_Unificada")
sse_manager = SSEManager()
event_bus = EventBus(name="School_Event_Bus", memory=school_db, sse_manager=sse_manager)
agent_graph = AgentGraph(topology="star")
