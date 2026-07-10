import os
from fastapi import APIRouter, HTTPException, status, UploadFile, File, Form, Depends
from sqlalchemy.orm import Session
from auth.security import TokenData, require_role
from models.database import get_db, CursoDB
import pytesseract
from PIL import Image
import io
import sys

if sys.platform.startswith('win'):
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

from schemas.agents import (
    TeacherPlanRequest, 
    TeacherPlanResponse, 
    ProgressReportRequest, 
    ProgressReportResponse,
    PsychologistEvalRequest,
    PsychologistAlert,
    TutorMatchRequest,
    TutorMatchResponse
)
from pydantic import BaseModel
from agents.deep_agents.teacher_planner import teacher_planner_app
from agents.deep_agents.progress_report import progress_report_app
from agents.deep_agents.psychologist_agent import psychologist_app
from agents.deep_agents.tutor_matcher import run_tutor_matcher
from agents.deep_agents.exam_grader import grade_exam_with_ai
from agents.deep_agents.bi_agent import run_bi_query
from agents.deep_agents.exam_generator import generate_exam
from agents.deep_agents.student_tutor import ask_tutor
from agents.deep_agents.story_generator import generate_personalized_story
from agents.deep_agents.vocational_agent import get_vocational_advice
from agents.deep_agents.medical_auditor import audit_medical_document
from agents.deep_agents.silabo_generator import generate_silabo

class BIRequest(BaseModel):
    question: str

class ExamGenRequest(BaseModel):
    tema: str
    dificultad: str
    num_preguntas: int = 5

class TutorRequest(BaseModel):
    pregunta: str
    perfil_alumno: str

class StoryRequest(BaseModel):
    curso_id: int
    valor_moral: str

class VocationalRequest(BaseModel):
    alumno_id: int
    intereses: str

router = APIRouter(prefix="/deep-agents", tags=["Deep Agents LangGraph"])

@router.post("/teacher-plan", response_model=TeacherPlanResponse, status_code=status.HTTP_200_OK)
async def generate_teacher_plan(
    request: TeacherPlanRequest,
    current_user: TokenData = Depends(require_role(["DOCENTE", "ADMIN"]))
):
    """
    Inicia un flujo LangGraph para crear una sesión de clase.
    Usa el patrón de Crítico-Generador para asegurar el cumplimiento curricular.
    """
    initial_state = {
        "grade": request.grade,
        "subject": request.subject,
        "topic": request.topic,
        "draft": "",
        "feedback": "",
        "is_valid": False,
        "retry_count": 0
    }
    
    try:
        # Usamos ainvoke para no bloquear el event loop de FastAPI
        result = await teacher_planner_app.ainvoke(initial_state)
        
        return TeacherPlanResponse(
            plan_content=result.get("draft", ""),
            is_valid=result.get("is_valid", False),
            feedback=result.get("feedback", ""),
            retries=result.get("retry_count", 0)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el flujo LangGraph: {str(e)}")

@router.post("/progress-report", response_model=ProgressReportResponse, status_code=status.HTTP_200_OK)
async def generate_progress_report(
    request: ProgressReportRequest,
    current_user: TokenData = Depends(require_role(["DOCENTE", "PSICOLOGO", "ADMIN"]))
):
    """
    Genera un informe para padres iterando sobre el tono hasta que el agente
    psicólogo interno apruebe su asertividad y empatía.
    """
    initial_state = {
        "student_name": request.student_name,
        "grades_summary": request.grades_summary,
        "behavior_notes": request.behavior_notes,
        "draft": "",
        "feedback": "",
        "is_valid": False,
        "retry_count": 0
    }
    
    try:
        result = await progress_report_app.ainvoke(initial_state)
        
        return ProgressReportResponse(
            report_content=result.get("draft", ""),
            is_valid=result.get("is_valid", False),
            feedback=result.get("feedback", ""),
            retries=result.get("retry_count", 0)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el flujo de Informes: {str(e)}")

# ========================================================
# MÓDULO 2: Automatización Conductual y Asignador
# ========================================================

@router.post("/evaluate-student", response_model=PsychologistAlert, status_code=status.HTTP_200_OK)
async def evaluate_student_risk(
    request: PsychologistEvalRequest,
    current_user: TokenData = Depends(require_role(["PSICOLOGO", "ADMIN"]))
):
    """
    Despierta al Agente Psicólogo Proactivo para analizar las notas y conducta de un estudiante.
    Retorna una alerta estructurada con nivel de riesgo (Bajo/Medio/Alto).
    """
    initial_state = {
        "student_name": request.student_name,
        "grades": request.grades,
        "absences": request.absences,
        "teacher_observations": request.teacher_observations,
        "analysis_summary": "",
        "risk_level": "",
        "diagnostico": "",
        "accion_recomendada": "",
        "is_alert_triggered": False
    }
    
    try:
        result = await psychologist_app.ainvoke(initial_state)
        
        return PsychologistAlert(
            risk_level=result.get("risk_level", "Bajo"),
            diagnostico=result.get("diagnostico", ""),
            accion_recomendada=result.get("accion_recomendada", "")
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error evaluando al estudiante: {str(e)}")

@router.post("/smart-tutor-match", response_model=TutorMatchResponse, status_code=status.HTTP_200_OK)
async def smart_tutor_match(
    request: TutorMatchRequest,
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    """
    Ejecuta el Asignador Inteligente (Chain-of-Thought) para emparejar perfiles
    de docentes con las necesidades específicas de cada aula.
    """
    try:
        response = await run_tutor_matcher(request)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el asignador de tutores: {str(e)}")

# ========================================================
# MÓDULO 4: Corrector Automático (Visión/OCR)
# ========================================================

@router.post("/grade-exam", status_code=status.HTTP_200_OK)
async def grade_exam(
    rubric: str = Form(...),
    file: UploadFile = File(...),
    current_user: TokenData = Depends(require_role(["DOCENTE", "ADMIN"]))
):
    """
    Recibe una imagen (foto/pdf) de un examen, aplica OCR y envía 
    el texto a Groq Llama-3 para su evaluación contra la rúbrica.
    """
    try:
        # 1. Leer imagen
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes))
        
        # 2. OCR usando Tesseract
        try:
            ocr_text = pytesseract.image_to_string(image, lang='spa')
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error en OCR. ¿Tienes Tesseract instalado en Windows? {str(e)}")
            
        if not ocr_text.strip():
            raise HTTPException(status_code=400, detail="No se pudo extraer texto de la imagen.")
            
        # 3. Llamar al agente calificador (Groq)
        result = await grade_exam_with_ai(ocr_text, rubric)
        
        return {
            "success": True,
            "ocr_text_preview": ocr_text[:200] + "...",
            "grading": result
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando el examen: {str(e)}")

# ========================================================
# MÓDULO 5: BI, Generación de Exámenes y Tutor Estudiantil
# ========================================================

@router.post("/bi-query", status_code=status.HTTP_200_OK)
async def admin_bi_query(
    request: BIRequest,
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    try:
        response = await run_bi_query(request.question)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/generate-exam", status_code=status.HTTP_200_OK)
async def doc_generate_exam(
    request: ExamGenRequest,
    current_user: TokenData = Depends(require_role(["DOCENTE", "ADMIN"]))
):
    try:
        response = await generate_exam(request.tema, request.dificultad, request.num_preguntas)
        return {"exam_content": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/student-tutor", status_code=status.HTTP_200_OK)
async def tutor_chat(
    request: TutorRequest,
    current_user: TokenData = Depends(require_role(["ALUMNO_PADRE", "DOCENTE", "ADMIN"]))
):
    try:
        response = await ask_tutor(request.pregunta, request.perfil_alumno)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/generate-story", status_code=status.HTTP_200_OK)
async def doc_generate_story(
    request: StoryRequest, 
    db: Session = Depends(get_db), 
    current_user: TokenData = Depends(require_role(["DOCENTE", "ADMIN"]))
):
    try:
        from models.database import AlumnoDB, CursoDB
        
        curso = db.query(CursoDB).filter(CursoDB.id == request.curso_id).first()
        if not curso:
            raise HTTPException(status_code=404, detail="Curso no encontrado")
            
        alumnos_db = db.query(AlumnoDB).filter(AlumnoDB.grado == curso.grado, AlumnoDB.seccion == curso.seccion, AlumnoDB.nivel == curso.nivel).all()
        nombres = [a.nombres.split(" ")[0] for a in alumnos_db] # Solo primer nombre para el cuento
        
        response = await generate_personalized_story(nombres, request.valor_moral, curso.nombre)
        return {"story_content": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/vocational-advisor", status_code=status.HTTP_200_OK)
async def vocational_advisor(
    request: VocationalRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ALUMNO_PADRE", "DOCENTE", "ADMIN"]))
):
    try:
        from models.database import NotaDB, CursoDB
        # Recopilamos las notas reales del alumno para formar su perfil
        notas = db.query(NotaDB).filter(NotaDB.alumno_id == request.alumno_id).all()
        if not notas:
            perfil = "El alumno aún no tiene notas registradas, asume un perfil neutro."
        else:
            # Resumen rudimentario
            perfil = "Notas Históricas:\n"
            for n in notas:
                curso = db.query(CursoDB).filter(CursoDB.id == n.curso_id).first()
                if curso:
                    perfil += f"- {curso.nombre}: {n.valor_numerico if n.valor_numerico else n.valor_letra}\n"
        
        advice = await get_vocational_advice(perfil, request.intereses)
        return {"advice": advice}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/justify-absence", status_code=status.HTTP_200_OK)
async def justify_absence(
    alumno_id: int = Form(...),
    file: UploadFile = File(...),
    current_user: TokenData = Depends(require_role(["ALUMNO_PADRE", "ADMIN"]))
):
    try:
        from core.ocr_engine import extract_text_from_image
        image_bytes = await file.read()
        ocr_text = await extract_text_from_image(image_bytes)
        
        resultado = await audit_medical_document(ocr_text)
        # En una app real, aquí insertaríamos en AsistenciaDB el registro de Falta Justificada
        # Para el prototipo, devolvemos el análisis
        return {
            "valido": resultado.es_valido,
            "dias_reposo": resultado.dias_reposo,
            "resumen": resultado.resumen_diagnostico
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=f"Imagen inválida: {str(ve)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# SISTEMA MULTIAGENTE DE SÍLABOS (LangGraph)
# ============================================================

from typing import List as TypingList
import asyncio


class SilaboGenRequest(BaseModel):
    nivel: str          # "PRIMARIA" | "SECUNDARIA"
    grado: int          # 1-6 / 1-5
    area: str           # "Matemática", "Comunicación", ...
    anno_escolar: str = "2025"


class SilaboGenBatchRequest(BaseModel):
    nivel: str
    grado: int
    anno_escolar: str = "2025"


@router.post("/silabo/generar", tags=["Sílabos Multiagente"])
async def generar_silabo_individual(
    request: SilaboGenRequest,
    current_user: TokenData = Depends(require_role(["DOCENTE", "ADMIN"]))
):
    """
    Genera un sílabo completo para un área específica usando el pipeline
    LangGraph de 6 agentes especializados.

    Pipeline: ContextBuilder → CompetencyAgent → ChronogramAgent
              → EvaluationAgent → ValidatorAgent (retry loop) → PersistenceAgent
    """
    try:
        result = await generate_silabo(
            nivel=request.nivel,
            grado=request.grado,
            area=request.area,
            anno_escolar=request.anno_escolar,
            docente_id=current_user.user_id,
        )

        if result.get("error_msg"):
            raise HTTPException(status_code=500, detail=result["error_msg"])

        return {
            "success": True,
            "silabo_id": result.get("silabo_id"),
            "nivel": result["nivel"],
            "grado": result["grado"],
            "area": result["area"],
            "anno_escolar": result["anno_escolar"],
            "validacion_ok": result.get("validacion_ok"),
            "retry_count": result.get("retry_count", 0),
            "feedback_validacion": result.get("feedback_validacion", ""),
            "silabo": {
                "marco_curricular": result.get("marco_curricular", ""),
                "competencias": result.get("competencias", ""),
                "capacidades": result.get("capacidades", ""),
                "desempennos": result.get("desempennos", ""),
                "enfoques": result.get("enfoques", ""),
                "bimestre_1": result.get("bimestre_1", ""),
                "bimestre_2": result.get("bimestre_2", ""),
                "bimestre_3": result.get("bimestre_3", ""),
                "bimestre_4": result.get("bimestre_4", ""),
                "sistema_evaluacion": result.get("sistema_evaluacion", ""),
                "materiales": result.get("materiales", ""),
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el pipeline LangGraph: {str(e)}")


@router.post("/silabo/generar-grado", tags=["Sílabos Multiagente"])
async def generar_silabos_por_grado(
    request: SilaboGenBatchRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    """
    Genera automáticamente sílabos para TODOS los áreas de un grado específico
    usando el pipeline LangGraph. Los áreas se obtienen de los cursos
    registrados en la BD para ese nivel/grado.

    Ejecución PARALELA: todos los áreas del grado se procesan concurrentemente.
    """
    # Obtener áreas únicas del grado
    cursos = db.query(CursoDB).filter(
        CursoDB.nivel == request.nivel,
        CursoDB.grado == request.grado
    ).all()

    areas_unicas = list({c.nombre for c in cursos})
    if not areas_unicas:
        raise HTTPException(
            status_code=404,
            detail=f"No hay cursos registrados para {request.nivel} {request.grado}° grado."
        )

    # Ejecutar todos los pipelines concurrentemente
    async def _gen_area(area: str):
        try:
            result = await generate_silabo(
                nivel=request.nivel,
                grado=request.grado,
                area=area,
                anno_escolar=request.anno_escolar,
                docente_id=current_user.user_id,
            )
            return {
                "area": area,
                "silabo_id": result.get("silabo_id"),
                "validacion_ok": result.get("validacion_ok"),
                "retry_count": result.get("retry_count", 0),
                "error": result.get("error_msg"),
                "status": "OK" if not result.get("error_msg") else "ERROR"
            }
        except Exception as e:
            return {"area": area, "status": "ERROR", "error": str(e)}

    resultados = await asyncio.gather(*[_gen_area(area) for area in areas_unicas])

    exitosos = [r for r in resultados if r["status"] == "OK"]
    fallidos  = [r for r in resultados if r["status"] == "ERROR"]

    return {
        "nivel": request.nivel,
        "grado": request.grado,
        "total_areas": len(areas_unicas),
        "generados": len(exitosos),
        "fallidos": len(fallidos),
        "detalle": resultados
    }


@router.post("/silabo/generar-todos", tags=["Sílabos Multiagente"])
async def generar_todos_los_silabos(
    anno_escolar: str = "2025",
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    """
    Operación masiva: genera sílabos para TODOS los grados de Primaria (1°-6°)
    y Secundaria (1°-5°) usando el pipeline LangGraph multiagente.

    Estrategia: grado por grado en secuencia, áreas del grado en paralelo.
    Devuelve un resumen completo del proceso.
    """
    # Obtener todos los cursos únicos de la BD
    todos_cursos = db.query(CursoDB).all()
    # Agrupar por (nivel, grado, nombre_area) eliminando duplicados de sección
    combinaciones = list({(c.nivel, c.grado, c.nombre) for c in todos_cursos})

    if not combinaciones:
        raise HTTPException(
            status_code=404,
            detail="No hay cursos registrados. Configure el sistema de cursos primero."
        )

    # Agrupar por grado para procesar en paralelo por grado
    from collections import defaultdict
    grupos: dict = defaultdict(list)
    
    PRIMARY_CORE = ["Comunicación", "Matemática", "Ciencia y Tecnología", "Personal Social", "Arte y Cultura", "Plan Lector", "Tutoría", "Computación"]
    
    for nivel, grado, area in combinaciones:
        if nivel == "PRIMARIA" and area in PRIMARY_CORE:
            if "Áreas Integradas" not in grupos[(nivel, grado)]:
                grupos[(nivel, grado)].append("Áreas Integradas")
        else:
            grupos[(nivel, grado)].append(area)

    resumen = {
        "total_combinaciones": len(combinaciones),
        "generados": 0,
        "fallidos": 0,
        "detalle": []
    }

    # Procesar grado a grado (secuencial entre grados, paralelo dentro del grado)
    for (nivel, grado), areas in sorted(grupos.items()):

        async def _gen(niv, gr, ar):
            try:
                # Si es Áreas Integradas, le pasamos ese nombre especial al generator
                result = await generate_silabo(
                    nivel=niv, grado=gr, area=ar,
                    anno_escolar=anno_escolar,
                    docente_id=current_user.user_id
                )
                
                # Si generó Áreas Integradas, clonamos el registro para cada curso base
                # para que la UI docente pueda encontrarlos por su nombre exacto
                if ar == "Áreas Integradas" and result.get("silabo_id"):
                    # El PersistenceAgent ya lo guardó como "Áreas Integradas". 
                    # Clonaremos los campos.
                    from models.database import SilaboTemDB, SessionLocal
                    db_clon = SessionLocal()
                    try:
                        base = db_clon.query(SilaboTemDB).filter(SilaboTemDB.id == result["silabo_id"]).first()
                        if base:
                            for c_name in PRIMARY_CORE:
                                # Upsert para cada sub-área
                                ext = db_clon.query(SilaboTemDB).filter(
                                    SilaboTemDB.nivel == niv, SilaboTemDB.grado == gr, SilaboTemDB.curso_nombre == c_name
                                ).first()
                                if not ext:
                                    ext = SilaboTemDB(nivel=niv, grado=gr, curso_nombre=c_name)
                                    db_clon.add(ext)
                                ext.anno_escolar = base.anno_escolar
                                ext.datos_informativos = base.datos_informativos
                                ext.fundamentacion = base.fundamentacion
                                ext.proposito = base.proposito
                                ext.competencias = base.competencias
                                ext.capacidades = base.capacidades
                                ext.estandares = base.estandares
                                ext.desempennos = base.desempennos
                                ext.enfoques = base.enfoques
                                ext.organizacion_unidades = base.organizacion_unidades
                                ext.contenidos = base.contenidos
                                ext.metodologia = base.metodologia
                                ext.sistema_evaluacion = base.sistema_evaluacion
                                ext.materiales = base.materiales
                                ext.bibliografia = base.bibliografia
                            db_clon.commit()
                    except Exception as e_clon:
                        print(f"Error clonando areas integradas: {e_clon}")
                    finally:
                        db_clon.close()
                
                return {
                    "nivel": niv, "grado": gr, "area": ar,
                    "silabo_id": result.get("silabo_id"),
                    "validacion_ok": result.get("validacion_ok"),
                    "retries": result.get("retry_count", 0),
                    "status": "OK" if not result.get("error_msg") else "ERROR",
                    "error": result.get("error_msg")
                }
            except Exception as ex:
                return {
                    "nivel": niv, "grado": gr, "area": ar,
                    "status": "ERROR", "error": str(ex)
                }

        batch_results = await asyncio.gather(*[_gen(nivel, grado, ar) for ar in areas])

        for r in batch_results:
            resumen["detalle"].append(r)
            if r["status"] == "OK":
                resumen["generados"] += 1
            else:
                resumen["fallidos"] += 1

    return resumen
