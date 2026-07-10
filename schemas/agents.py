from pydantic import BaseModel, Field
from typing import List, Optional, Dict

# --- Esquemas para el Asistente de Planificación Docente ---

class TeacherPlanRequest(BaseModel):
    grade: str = Field(..., description="Grado académico (ej. 3ro Secundaria)")
    subject: str = Field(..., description="Materia o asignatura (ej. Matemática)")
    topic: str = Field(..., description="Tema a desarrollar en la sesión")

class TeacherPlanResponse(BaseModel):
    plan_content: str = Field(..., description="Contenido final de la sesión de aprendizaje")
    is_valid: bool = Field(..., description="Indica si pasó la evaluación crítica")
    feedback: str = Field(..., description="Feedback final o notas del agente crítico")
    retries: int = Field(..., description="Número de reintentos realizados")

# --- Esquemas para el Asistente de Informes de Progreso ---

class ProgressReportRequest(BaseModel):
    student_name: str = Field(..., description="Nombre del estudiante")
    grades_summary: dict = Field(..., description="Diccionario con las notas (ej. {'Matemáticas': 'C', 'Lenguaje': 'A'})")
    behavior_notes: str = Field(..., description="Anotaciones conductuales del tutor")

class ProgressReportResponse(BaseModel):
    report_content: str = Field(..., description="Informe redactado para el apoderado")
    is_valid: bool = Field(..., description="Indica si pasó la evaluación de empatía")
    feedback: str = Field(..., description="Feedback del crítico")
    retries: int = Field(..., description="Número de iteraciones")

# --- Structured Outputs para uso INTERNO de LangChain/LangGraph ---

class EvaluacionCurricular(BaseModel):
    """Esquema de salida forzada para el Nodo Crítico de Planificación"""
    is_valid: bool = Field(..., description="True si cumple con los requerimientos curriculares, False en caso contrario.")
    feedback: str = Field(..., description="Si is_valid=False, dar instrucciones claras al generador para corregir. Si es True, poner 'OK'.")

class EvaluacionTono(BaseModel):
    """Esquema de salida forzada para el Nodo Crítico de Informes"""
    is_constructive: bool = Field(..., description="True si el tono es constructivo, empático y aporta soluciones. False en caso contrario.")
    feedback: str = Field(..., description="Si is_constructive=False, instruir al generador sobre qué frases suavizar o qué soluciones añadir.")

# ==========================================
# MÓDULO 2: Automatización Conductual
# ==========================================

# --- Esquemas para el Agente Psicólogo Proactivo ---
class PsychologistEvalRequest(BaseModel):
    student_id: int
    student_name: str
    grades: Dict[str, float] = Field(..., description="Promedios por curso")
    absences: int = Field(..., description="Número de faltas injustificadas")
    teacher_observations: List[str] = Field(..., description="Observaciones conductuales de los docentes")

class PsychologistAlert(BaseModel):
    risk_level: str = Field(..., description="Nivel de riesgo: 'Bajo', 'Medio', o 'Alto'")
    diagnostico: str = Field(..., description="Breve diagnóstico de la situación académica y conductual")
    accion_recomendada: str = Field(..., description="Paso a paso a seguir (ej. Citar padres, Derivar a tutoría)")

# --- Esquemas para el Asignador Inteligente de Tutores ---
class ClassroomProfile(BaseModel):
    classroom_id: str = Field(..., description="Identificador del aula (ej. 1-A Primaria)")
    difficulty_level: str = Field(..., description="Nivel de dificultad disciplinaria o académica")
    needs: List[str] = Field(..., description="Necesidades específicas del aula")

class TeacherProfile(BaseModel):
    teacher_id: int
    name: str
    teaching_style: str = Field(..., description="Estilo docente (ej. Estricto, Empático, Dinámico)")
    strengths: List[str] = Field(..., description="Fortalezas del docente")

class TutorMatchRequest(BaseModel):
    classrooms: List[ClassroomProfile]
    teachers: List[TeacherProfile]

class TutorMatchResult(BaseModel):
    classroom_id: str
    teacher_id: int
    rationale: str = Field(..., description="Explicación del razonamiento (por qué es el match ideal)")

class TutorMatchResponse(BaseModel):
    matches: List[TutorMatchResult]
