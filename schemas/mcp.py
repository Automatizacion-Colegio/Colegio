from pydantic import BaseModel, Field
from typing import Optional, List, Literal

# MCP Protocol schemas
class MCPRequest(BaseModel):
    agent_id: str
    action: str
    payload: dict

class MCPResponse(BaseModel):
    status: Literal["success", "error"]
    data: Optional[dict] = None
    message: Optional[str] = None

class ExpedienteAdmision(BaseModel):
    dni: str = Field(..., min_length=8, max_length=8)
    nombres: str
    apellidos: str
    nivel: Literal["Primaria", "Secundaria"]
    grado: int
    promedio: float = Field(..., ge=0, le=20)
    conducta: Literal["A", "B", "C"]
    ap_nombre: str
    ap_correo: str
    ap_telefono: str = Field(..., min_length=9, max_length=9)

class AgendarCita(BaseModel):
    expediente: ExpedienteAdmision
    dia: str
    hora: str

class EvaluacionPsicologica(BaseModel):
    codigo_obs: str
    decision: Literal["Aprobado", "Rechazado"]
    observacion: str

class PagoMatricula(BaseModel):
    codigo_est: str
    monto_pagado: float

class RegistroNota(BaseModel):
    codigo_est: str
    curso: str
    nota: float = Field(..., ge=0, le=20)
    docente_id: Optional[int] = None  # Corregido: era id_docente: str (inconsistente con NotaDB)

class EvaluacionAcademica(BaseModel):
    nota: float
    curso: str

class EvaluacionResponse(BaseModel):
    alerta_pedagogica: bool
    recomendacion: str

class CursoCreate(BaseModel):
    nombre: str
    nivel: Literal["PRIMARIA", "SECUNDARIA"]
    grados: List[int]
    docente_id: Optional[int] = None

class AsignarDocenteRequest(BaseModel):
    docente_id: Optional[int] = None

class AulaPrimariaCreate(BaseModel):
    grado: int
    seccion: str
    docente_id: Optional[int] = None

class TutorCreate(BaseModel):
    docente_id: int
    nivel: Literal["PRIMARIA", "SECUNDARIA"]
    grado: int
    seccion: str

class AsistenciaCreate(BaseModel):
    alumno_id: int
    fecha: str
    estado: Literal["Presente", "Falta", "Tardanza"]

class NotaCreate(BaseModel):
    alumno_id: int
    curso_id: int
    criterio: Literal["Tareas", "Participacion", "Practicas", "Examen"]
    semana: str
    valor_numerico: Optional[float] = None
    valor_letra: Optional[str] = None
    observacion: Optional[str] = None

class CitaCreate(BaseModel):
    alumno_id: Optional[int] = None
    motivo: Literal["Admisión", "Rendimiento"]
    dia: str
    hora: str

class BatchAsistencia(BaseModel):
    asistencias: List[AsistenciaCreate]

class BatchNota(BaseModel):
    notas: List[NotaCreate]

class AgendarCitaRendimiento(BaseModel):
    alumno_id: int
    dia: str
    hora: str


# ======================================================================
# Schemas para Sílabos
# ======================================================================

class SilaboCreate(BaseModel):
    nivel: Literal["PRIMARIA", "SECUNDARIA"]
    grado: int
    curso_nombre: str
    anno_escolar: str = "2025"
    # Campos legacy (bimestral)
    bimestre_1: Optional[str] = None
    bimestre_2: Optional[str] = None
    bimestre_3: Optional[str] = None
    bimestre_4: Optional[str] = None
    # Campos del sílabo completo CNEB (generados por IA o cargados manualmente)
    datos_informativos: Optional[str] = None
    fundamentacion: Optional[str] = None
    proposito: Optional[str] = None
    organizacion_unidades: Optional[str] = None
    contenidos: Optional[str] = None
    metodologia: Optional[str] = None
    bibliografia: Optional[str] = None
    estandares: Optional[str] = None
    # Campos transversales
    competencias: Optional[str] = None
    capacidades: Optional[str] = None
    desempennos: Optional[str] = None
    enfoques: Optional[str] = None
    sistema_evaluacion: Optional[str] = None
    materiales: Optional[str] = None

class SilaboUpdate(BaseModel):
    competencias: Optional[str] = None
    capacidades: Optional[str] = None
    desempennos: Optional[str] = None
    enfoques: Optional[str] = None
    bimestre_1: Optional[str] = None
    bimestre_2: Optional[str] = None
    bimestre_3: Optional[str] = None
    bimestre_4: Optional[str] = None
    sistema_evaluacion: Optional[str] = None
    materiales: Optional[str] = None
    anno_escolar: Optional[str] = None
