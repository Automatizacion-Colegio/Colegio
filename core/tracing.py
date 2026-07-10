"""
Módulo de Observabilidad y Tracing.
Configura logging estructurado (JSON) para integrarse con Datadog/ELK,
y mantiene un contexto de trace_id usando contextvars.
"""
import logging
import json
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict

# ContextVar para propagar el trace_id a lo largo de la ejecución asíncrona
request_trace_id: ContextVar[str] = ContextVar("request_trace_id", default="NO_TRACE")


class JSONLogFormatter(logging.Formatter):
    """Formatter personalizado para emitir logs en formato JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": request_trace_id.get(),
            "module": record.module,
            "funcName": record.funcName,
            "lineNo": record.lineno,
        }
        
        # Añadir excepciones si existen
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
            
        # Añadir atributos extra (ej. kwargs pasados a logger.info(extra={"key": "val"}))
        if hasattr(record, "extra"):
            log_obj.update(getattr(record, "extra"))

        return json.dumps(log_obj, ensure_ascii=False)


def setup_logger(name: str = "erp_escolar") -> logging.Logger:
    """Configura e instancia el logger estructurado global."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Evitar handlers duplicados si se llama varias veces
    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(JSONLogFormatter())
        logger.addHandler(console_handler)
        
    return logger

# Instancia global
logger = setup_logger()

def get_trace_id() -> str:
    """Obtiene el trace_id del contexto actual."""
    return request_trace_id.get()

def set_trace_id(trace_id: str) -> None:
    """Establece el trace_id en el contexto actual."""
    request_trace_id.set(trace_id)

def log_audit_event(action: str, user_id: str, resource: str, status: str, details: str = ""):
    """
    Registra un evento de auditoría estricto.
    (Login, cambio de notas, admisión).
    """
    logger.info(
        f"Audit Event: {action}",
        extra={
            "audit": True,
            "action": action,
            "user_id": user_id,
            "resource": resource,
            "status": status,
            "details": details
        }
    )
