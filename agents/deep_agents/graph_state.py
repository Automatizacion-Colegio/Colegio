from typing import TypedDict, List, Dict, Any, Optional


class TeacherPlanState(TypedDict):
    """Estado compartido para el flujo de LangGraph de Planificación Docente"""
    grade: str
    subject: str
    topic: str

    # Internal Variables
    draft: str
    feedback: str
    is_valid: bool
    retry_count: int


class ProgressReportState(TypedDict):
    """Estado compartido para el flujo de LangGraph de Informes de Progreso"""
    student_name: str
    grades_summary: Dict[str, Any]
    behavior_notes: str

    # Internal Variables
    draft: str
    feedback: str
    is_valid: bool
    retry_count: int


class PsychologistState(TypedDict):
    """Estado compartido para el flujo del Agente Psicólogo"""
    student_name: str
    grades: Dict[str, float]
    absences: int
    teacher_observations: List[str]

    # Internal Variables
    analysis_summary: str
    risk_level: str
    diagnostico: str
    accion_recomendada: str
    is_alert_triggered: bool


# ============================================================
#  Estado del sistema multiagente de generación de Sílabos
# ============================================================

class SilaboState(TypedDict):
    # ── Input ──────────────────────────────────────────────
    nivel: str
    grado: int
    area: str
    anno_escolar: str
    docente_id: Optional[int]

    # ── 14 Secciones del Sílabo MINEDU ─────────────────────
    datos_informativos: str
    fundamentacion: str
    proposito: str
    competencias: str
    capacidades: str
    estandares: str
    desempennos: str
    enfoques: str
    organizacion_unidades: str
    contenidos: str
    metodologia: str
    sistema_evaluacion: str
    materiales: str
    bibliografia: str

    # ── Estado del Pipeline ────────────────────────────────
    validacion_ok: bool
    feedback_validacion: str
    retry_count: int
    silabo_id: Optional[int]
    error_msg: Optional[str]
