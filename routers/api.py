"""
API Router del ERP Escolar — Endpoints REST + SSE Streaming.
"""
import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from core.timetabler import generate_timetables

from auth.security import TokenData, get_current_user, require_role, get_password_hash, get_current_user_optional
from schemas.mcp import ExpedienteAdmision, PagoMatricula, RegistroNota, AgendarCita, CursoCreate, TutorCreate, AsistenciaCreate, NotaCreate, BatchAsistencia, BatchNota, AgendarCitaRendimiento, SilaboCreate, SilaboUpdate
from schemas.sse import StreamChatRequest
from agents.orchestrator import ColegioOrchestrator
from core.antigravity import school_db, event_bus, agent_graph, telemetry_store, sse_manager
from core.tasks import procesar_admision_batch, celery_app
from models.database import get_db, UserDB, CursoDB, TutorDB, AlumnoDB, AsistenciaDB, NotaDB, CitaDB, HorarioDB, ObservacionDB, CajaDiariaDB, SilaboTemDB, CompetenciaMINEDUDB, CapacidadMINEDUDB, EstandarMINEDUDB, DesempenoMINEDUDB
from agents.subagents import ag_monitor


router = APIRouter()
orchestrator = ColegioOrchestrator(school_db, event_bus, agent_graph)
from agents.orchestrator import swarm_client

class ConfigMatricula(BaseModel):
    primaria: float
    secundaria: float
    cupos_aula_primaria: int = 30
    cupos_aula_secundaria: int = 30

@router.get("/config")
async def get_config():
    state = await school_db.get_state()
    return state.get("config_matricula", {
        "primaria": 500.0, 
        "secundaria": 700.0,
        "cupos_aula_primaria": 30,
        "cupos_aula_secundaria": 30
    })

@router.post("/admin/config")
async def set_config(config: ConfigMatricula, current_user: TokenData = Depends(require_role(["ADMIN"]))):
    state = await school_db.get_state()
    state["config_matricula"] = {
        "primaria": config.primaria, 
        "secundaria": config.secundaria,
        "cupos_aula_primaria": config.cupos_aula_primaria,
        "cupos_aula_secundaria": config.cupos_aula_secundaria
    }
    await school_db.set_state(state)
    return {"message": "Configuración de costos y cupos actualizada correctamente."}


# ======================================================================
# Chat endpoints
# ======================================================================



@router.post("/chat/stream")
async def chat_stream(msg: StreamChatRequest, current_user: Optional[TokenData] = Depends(get_current_user_optional), db: Session = Depends(get_db)):
    """
    Endpoint SSE: emite tokens progresivos al cliente.
    Protocol: event: {thinking|tool_call|token|done|error}
    """
    channel = sse_manager.create_channel(msg.session_id)

    # Determinar agente inicial y contexto según el rol
    from agents.subagents import ag_soporte, ag_admin, ag_evaluacion, ag_psicologo
    
    starting_agent = ag_soporte
    user_context = {}
    
    if current_user:
        user_context["user_role"] = current_user.role
        user_context["username"] = current_user.username
        
        if current_user.role == "ADMIN":
            starting_agent = ag_admin
        elif current_user.role == "DOCENTE":
            starting_agent = ag_evaluacion
            # Buscar si es tutor
            tutor_info = db.query(TutorDB).filter(TutorDB.docente_id == current_user.user_id).first()
            if tutor_info:
                user_context["es_tutor"] = True
                user_context["aula_tutor"] = f"{tutor_info.grado} {tutor_info.seccion} {tutor_info.nivel}"
                # Alumnos del aula
                alumnos_aula = db.query(AlumnoDB).filter(AlumnoDB.grado == tutor_info.grado, AlumnoDB.seccion == tutor_info.seccion, AlumnoDB.nivel == tutor_info.nivel).all()
                user_context["alumnos_tutoria"] = [{"id": a.id, "nombre": a.nombres} for a in alumnos_aula]
            
            # Cursos asignados
            cursos = db.query(CursoDB).filter(CursoDB.docente_id == current_user.user_id).all()
            user_context["cursos_asignados"] = [{"id": c.id, "nombre": c.nombre, "aula": f"{c.grado} {c.seccion} {c.nivel}"} for c in cursos]
            
        elif current_user.role == "PSICOLOGO":
            starting_agent = ag_psicologo
            citas = db.query(CitaDB).filter(CitaDB.psicologo_id == current_user.user_id).all()
            user_context["citas_asignadas"] = len(citas)
            
        elif current_user.role == "ALUMNO_PADRE":
            starting_agent = ag_soporte
            alumnos = db.query(AlumnoDB).filter(AlumnoDB.apoderado_id == current_user.user_id).all()
            user_context["hijos"] = [{"id": a.id, "nombre": a.nombres, "aula": f"{a.grado} {a.seccion} {a.nivel}"} for a in alumnos]

    async def event_generator():
        # Lanzar el procesamiento del chat en background
        task = asyncio.create_task(orchestrator.stream_chat(
            message=msg.message, 
            channel=channel, 
            history=msg.history,
            starting_agent=starting_agent,
            user_context=user_context
        ))

        try:
            async for event in channel:
                event_type = event.get("event", "")
                data = event.get("data", {})
                yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

                if event_type in ("done", "error"):
                    break
        except asyncio.CancelledError:
            task.cancel()
        finally:
            sse_manager.remove_channel(msg.session_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )





# ======================================================================
# SSE Global Events (alertas pedagógicas, eventos del bus, etc.)
# ======================================================================

@router.get("/events/subscribe")
async def subscribe_events():
    """
    Endpoint SSE global: el cliente se suscribe para recibir eventos
    del EventBus en tiempo real (ALERTA_PEDAGOGICA, etc.).
    """
    queue = sse_manager.subscribe_global()

    async def event_generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    event_type = event.get("event", "bus_event")
                    data = event.get("data", {})
                    yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive
                    yield f"event: ping\ndata: {{}}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            sse_manager.unsubscribe_global(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ======================================================================
# Admisiones
# ======================================================================

@router.post("/admision")
async def iniciar_admision(expediente: ExpedienteAdmision):
    return await orchestrator.procesar_admision(expediente)


@router.post("/admision/agendar_cita")
async def agendar_cita(data: AgendarCita):
    return await orchestrator.agendar_cita_psicologica(data)


@router.get("/admision/seguimiento/{codigo}")
async def seguimiento_expediente(codigo: str):
    state = await school_db.get_state()

    if codigo in state.get("enrolled_students", {}):
        return {"status": "encontrado", "data": state["enrolled_students"][codigo]}

    if codigo in state.get("observed_students", {}):
        return {"status": "encontrado", "data": state["observed_students"][codigo]}

    if codigo in state.get("rejected_students", {}):
        return {"status": "encontrado", "data": state["rejected_students"][codigo]}

    raise HTTPException(status_code=404, detail="Código de expediente no encontrado.")


# ======================================================================
# Psicología
# ======================================================================

@router.get("/psicologia/citas_rendimiento")
async def get_citas_rendimiento(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["PSICOLOGO", "ADMIN"]))
):
    citas = db.query(CitaDB).filter(CitaDB.motivo == "Rendimiento").all()
    # Para la demo, adjuntamos datos ficticios o extraemos de alumnos
    resultado = []
    for c in citas:
        al = db.query(AlumnoDB).filter(AlumnoDB.id == c.alumno_id).first()
        resultado.append({
            "id": c.id,
            "dia": c.dia,
            "hora": c.hora,
            "estado": c.estado,
            "alumno": al.nombres if al else "Desconocido"
        })
    return resultado

@router.post("/admin/generar_horarios")
async def admin_generar_horarios(
    nivel: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    try:
        generate_timetables(db, target_nivel=nivel)
        msg = f"Horarios de {nivel} generados" if nivel else "Horarios generados"
        return {"message": f"{msg} óptimamente sin conflictos."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/horarios/{nivel}/{grado}/{seccion}")
async def obtener_horario_aula(
    nivel: str,
    grado: int,
    seccion: str,
    db: Session = Depends(get_db)
):
    horarios = db.query(HorarioDB).filter(
        HorarioDB.nivel == nivel,
        HorarioDB.grado == grado,
        HorarioDB.seccion == seccion
    ).all()
    
    resultado = []
    for h in horarios:
        curso = db.query(CursoDB).filter(CursoDB.id == h.curso_id).first()
        doc = db.query(UserDB).filter(UserDB.id == h.docente_id).first()
        resultado.append({
            "dia": h.dia,
            "hora_inicio": h.hora_inicio,
            "hora_fin": h.hora_fin,
            "curso": curso.nombre if curso else "Libre",
            "docente": doc.username if doc else "Sin Asignar"
        })
    return resultado

class CursoAsignacion(BaseModel):
    curso_id: int
    docente_id: int

class AsignacionDocentesBatch(BaseModel):
    asignaciones: List[CursoAsignacion]

class AsignacionInteligentePayload(BaseModel):
    nivel: str
    primaria_tutores: dict  # {"1-A": 12, "1-B": 15}
    primaria_especialistas: dict # {"Inglés": [3, 4], "Religión": [5]}
    secundaria_cursos: dict # {"Matemática": [6, 7]}

@router.get("/admin/cursos_aula/{nivel}/{grado}/{seccion}")
async def get_cursos_aula(
    nivel: str,
    grado: int,
    seccion: str,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    cursos = db.query(CursoDB).filter(
        CursoDB.nivel == nivel,
        CursoDB.grado == grado,
        CursoDB.seccion == seccion
    ).all()
    return cursos


# ======================================================================
# Sílabos (Nivel / Grado / Curso)
# ======================================================================

# Contenidos pedagógicos por defecto acorde al Currículo Nacional peruano (CN 2019)
_CONTENIDO_SILABO = {
    "PRIMARIA": {
        1: {
            "Comunicación": {"competencias": "Se comunica oralmente en su lengua materna|Lee diversos tipos de textos escritos|Escribe diversos tipos de textos", "capacidades": "Obtiene información del texto oral|Infiere e interpreta información del texto|Adecua, organiza y desarrolla sus ideas", "bimestre_1": "Identificación de sílabas|Vocales y consonantes básicas|Lectura de palabras simples", "bimestre_2": "Lectura de oraciones cortas|Escritura de palabras|Cuentos cortos y fábulas", "bimestre_3": "Comprensión de textos breves|Escritura de oraciones|Recitación y declamación", "bimestre_4": "Producción de textos simples|Síntesis de lecturas|Exposición oral breve", "sistema_evaluacion": "Escala literal: AD (Logro Destacado), A (Logro Esperado), B (En Proceso), C (En Inicio)"},
            "Matemática": {"competencias": "Resuelve problemas de cantidad|Resuelve problemas de forma, movimiento y localización|Resuelve problemas de gestión de datos", "capacidades": "Traduce cantidades a expresiones numéricas|Comunica su comprensión sobre los números|Usa estrategias y procedimientos de estimación", "bimestre_1": "Números del 0 al 10|Comparación de cantidades|Nociones espaciales básicas", "bimestre_2": "Números del 0 al 20|Suma y resta sin canje|Formas geométricas básicas", "bimestre_3": "Números hasta 50|Suma y resta con canje|Medidas de longitud no convencionales", "bimestre_4": "Números hasta 100|Doble y mitad|Resolución de problemas sencillos", "sistema_evaluacion": "Escala literal: AD, A, B, C"},
            "Personal Social": {"competencias": "Construye su identidad|Convive y participa democráticamente|Indaga mediante métodos científicos", "capacidades": "Se valora así mismo|Interacciona con cada persona|Problematiza situaciones del entorno", "bimestre_1": "Yo y mi familia|Mis emociones|Normas de convivencia en el aula", "bimestre_2": "Mi escuela y mi comunidad|Derechos del niño|Tradiciones de mi región", "bimestre_3": "El Perú y sus regiones|Cultura y diversidad|Participación ciudadana infantil", "bimestre_4": "Historia de mi comunidad|Cuidado del medio ambiente|Proyecto de vida", "sistema_evaluacion": "Escala literal: AD, A, B, C"},
            "Ciencia y Tecnología": {"competencias": "Indaga mediante métodos científicos|Explica el mundo fisiconatural|Diseña y construye soluciones tecnológicas", "bimestre_1": "Seres vivos y no vivos|Los sentidos|Cuidado del cuerpo", "bimestre_2": "Los animales|Las plantas|El agua y su importancia", "bimestre_3": "El suelo|La luz y el sonido|Experimentos simples", "bimestre_4": "El aire|Ecosistemas locales|Cuidado del medio ambiente", "sistema_evaluacion": "Escala literal: AD, A, B, C"},
        },
        2: {
            "Comunicación": {"competencias": "Se comunica oralmente|Lee diversos tipos de textos|Escribe diversos tipos de textos", "bimestre_1": "Comprensión lectora: texto narrativo|Escritura de oraciones compuestas|Uso de mayúsculas y punto", "bimestre_2": "Texto descriptivo|Diálogos y conversaciones|Vocabulario contextual", "bimestre_3": "Texto instructivo|Producción de un cuento corto|Planificación y revisión textual", "bimestre_4": "Texto informativo|Exposición oral estructurada|Carta y correo electrónico", "sistema_evaluacion": "Escala literal: AD, A, B, C"},
            "Matemática": {"competencias": "Resuelve problemas de cantidad|Resuelve problemas de regularidad|Resuelve problemas de forma y movimiento", "bimestre_1": "Números hasta 100|Suma y resta con reagrupación|Valor posicional", "bimestre_2": "Multiplicación como suma repetida|Figuras geométricas|Medidas de tiempo", "bimestre_3": "División básica|Fracciones simples|Medidas de masa", "bimestre_4": "Números hasta 1000|Resolución de problemas de dos pasos|Estadística inicial", "sistema_evaluacion": "Escala literal: AD, A, B, C"},
        },
        3: {
            "Comunicación": {"competencias": "Comunicación oral y escrita|Lectura crítica", "bimestre_1": "Texto narrativo: cuento y leyenda|Adjetivos y sustantivos", "bimestre_2": "Texto descriptivo y expositivo|Verbos en presente y pasado", "bimestre_3": "Texto argumentativo básico|Conectores de adición", "bimestre_4": "Producción de textos complejos|Ortografía", "sistema_evaluacion": "Escala literal: AD, A, B, C"},
            "Matemática": {"competencias": "Resuelve problemas de cantidad|Resuelve problemas de regularidad y equivalencia", "bimestre_1": "Números hasta 10 000|Multiplicación y división|Valor posicional ampliado", "bimestre_2": "Fracciones homógéneas|Perímetros de figuras", "bimestre_3": "Decimales básicos|Estadística: tablas y gráficas", "bimestre_4": "Resolución de problemas mixtos|Medidas de capacidad", "sistema_evaluacion": "Escala literal: AD, A, B, C"},
        },
        4: {
            "Comunicación": {"competencias": "Comunicación oral avanzada|Producción textual", "bimestre_1": "Tipología textual|Comprensión inferencial", "bimestre_2": "Texto argumentativo|Debate estructurado", "bimestre_3": "Producción de textos autónomos|Puntuación y tildación", "bimestre_4": "Discurso público|Literatura peruana infantil", "sistema_evaluacion": "Escala literal: AD, A, B, C"},
            "Matemática": {"competencias": "Resuelve problemas de cantidad|Estadística y probabilidad", "bimestre_1": "Números hasta un millón|Operaciones combinadas", "bimestre_2": "Fracciones heterógeneas|Decimales", "bimestre_3": "Área y perímetro|Figuras geométricas avanzadas", "bimestre_4": "Proporcionalidad directa|Probabilidad elemental", "sistema_evaluacion": "Escala literal: AD, A, B, C"},
        },
        5: {
            "Comunicación": {"competencias": "Comunicación integral|Comprensión crítica", "bimestre_1": "Análisis textual|Figuras literarias", "bimestre_2": "Texto periodístico y publicitario", "bimestre_3": "Producción creativa|Resumen y síntesis", "bimestre_4": "Literatura regional|Proyecto editorial de aula", "sistema_evaluacion": "Escala literal: AD, A, B, C"},
            "Matemática": {"competencias": "Pensamiento numérico y lógico", "bimestre_1": "Fracciones y decimales avanzados|Porcentajes", "bimestre_2": "Álgebra básica: ecuaciones simples", "bimestre_3": "Geometría plana avanzada|Transformaciones", "bimestre_4": "Estadística descriptiva|Problema de la vida real", "sistema_evaluacion": "Escala literal: AD, A, B, C"},
        },
        6: {
            "Comunicación": {"competencias": "Comunicación integral y crítica", "bimestre_1": "Obras literarias peruanas e hispanoamericanas", "bimestre_2": "Texto académico: informe y ensayo", "bimestre_3": "Discurso argumentativo|Oratoria", "bimestre_4": "Proyecto de lectura y escritura creativa", "sistema_evaluacion": "Escala literal: AD, A, B, C"},
            "Matemática": {"competencias": "Pensamiento matemático avanzado para secundaria", "bimestre_1": "Operaciones con fracciones complejas|Razón y proporción", "bimestre_2": "Introducción al álgebra|Variables y expresiones", "bimestre_3": "Geometría del espacio|Volumen", "bimestre_4": "Estadística y análisis de datos|Preparación para secundaria", "sistema_evaluacion": "Escala literal: AD, A, B, C"},
        },
    },
    "SECUNDARIA": {
        1: {
            "Comunicación": {"competencias": "Se comunica oralmente|Lee diversos tipos de textos|Escribe diversos tipos de textos", "capacidades": "Análisis crítico|Producción textual argumentativa", "bimestre_1": "Narrador y punto de vista|Género narrativo: cuento y novela", "bimestre_2": "Género poético|Figuras literarias", "bimestre_3": "Género dramático|Texto expositivo", "bimestre_4": "Texto argumentativo|Proyecto lector", "sistema_evaluacion": "Escala vigesimal: 00-20. Promedio ponderado de 4 criterios de evaluación"},
            "Matemática": {"competencias": "Resuelve problemas de cantidad|Resuelve problemas de regularidad|Resuelve problemas de gestión de datos", "capacidades": "Traduce cantidades|Comunica su comprensión|Usa estrategias de cálculo", "bimestre_1": "Números enteros y operaciones|Valor absoluto|Jerarquía de operaciones", "bimestre_2": "Divisibilidad y números primos|MCD y MCM|Fracciones y decimales", "bimestre_3": "Expresiones algebraicas|Ecuaciones de primer grado|Sistemas de ecuaciones", "bimestre_4": "Estadística descriptiva|Probabilidad|Geometría: figuras y áreas", "sistema_evaluacion": "Escala vigesimal 00-20"},
            "Historia, Geografía y Economía": {"competencias": "Construye interpretaciones históricas|Gestiona responsablemente el espacio y el ambiente", "bimestre_1": "Prehistoria: el origen del hombre|Mesopotamia y Egipto", "bimestre_2": "Grecia y Roma|Edad Media", "bimestre_3": "Renacimiento|Reformas religiosas|El mundo moderno", "bimestre_4": "Perú preinca e Inca|Geografía del Perú", "sistema_evaluacion": "Escala vigesimal 00-20"},
            "Ciencia y Tecnología": {"competencias": "Indaga mediante métodos científicos|Explica el mundo fisiconatural|Diseña soluciones tecnológicas", "bimestre_1": "Método científico|La célula: estructura y funciones", "bimestre_2": "Tejidos y órganos|Sistema digestivo y respiratorio", "bimestre_3": "Sistema nervioso|Reproducción celular", "bimestre_4": "Ecosistemas y biodiversidad|Química básica: átomos y moléculas", "sistema_evaluacion": "Escala vigesimal 00-20"},
            "Inglés": {"competencias": "Se comunica oralmente en inglés|Lee textos en inglés|Escribe textos en inglés", "bimestre_1": "Greetings, introductions|Present simple", "bimestre_2": "Everyday activities|Present continuous", "bimestre_3": "Past simple|Describing events", "bimestre_4": "Future tense|Writing a short paragraph", "sistema_evaluacion": "Escala vigesimal 00-20"},
        },
        2: {
            "Matemática": {"competencias": "Resuelve problemas de cantidad y regularidad|Estadística y probabilidad", "bimestre_1": "Potencias y raíces|Números racionales", "bimestre_2": "Polinomios y factorización|Productos notables", "bimestre_3": "Funciones lineales|Sistemas de ecuaciones", "bimestre_4": "Geometría: triángulos y cuadriláteros|Áreas y perímetros", "sistema_evaluacion": "Escala vigesimal 00-20"},
            "Comunicación": {"competencias": "Comunicación oral y escrita avanzada", "bimestre_1": "Texto periodístico|Crónica y reportaje", "bimestre_2": "Literatura peruana colonial|Barroco", "bimestre_3": "Romanticismo latinoamericano", "bimestre_4": "Ensayo y texto crítico", "sistema_evaluacion": "Escala vigesimal 00-20"},
            "Historia, Geografía y Economía": {"bimestre_1": "Conquista y virreynato del Perú", "bimestre_2": "Emancipación e Independencia", "bimestre_3": "República del Perú: siglo XIX", "bimestre_4": "Recursos naturales y economía peruana", "sistema_evaluacion": "Escala vigesimal 00-20"},
            "Ciencia y Tecnología": {"bimestre_1": "Fuerza y movimiento|Cinématica", "bimestre_2": "Dinámica|Leyes de Newton", "bimestre_3": "Energía y trabajo|Electromagnetismo básico", "bimestre_4": "Ondas y sonido|Proyecto tecnológico", "sistema_evaluacion": "Escala vigesimal 00-20"},
        },
        3: {
            "Matemática": {"bimestre_1": "Números reales|Álgebra: inecuaciones", "bimestre_2": "Funciones cuadráticas|Sistemas de inecuaciones", "bimestre_3": "Trigonometría: razones trigonométricas", "bimestre_4": "Geometría analítica: la recta|Cónicas básicas", "sistema_evaluacion": "Escala vigesimal 00-20"},
            "Comunicación": {"bimestre_1": "Modernismo hispanoamericano", "bimestre_2": "Vanguardismo|Cesar Vallejo", "bimestre_3": "Literatura del siglo XX en el Perú", "bimestre_4": "Texto académico: monografía", "sistema_evaluacion": "Escala vigesimal 00-20"},
            "Historia, Geografía y Economía": {"bimestre_1": "Perú en el siglo XX|La belle époque", "bimestre_2": "Guerras mundiales|Revoluciones del siglo XX", "bimestre_3": "Guerra Fría|Movimientos sociales", "bimestre_4": "Globalización|Perú contemporáneo", "sistema_evaluacion": "Escala vigesimal 00-20"},
            "Ciencia y Tecnología": {"bimestre_1": "Química inorgánica|Tabla periódica", "bimestre_2": "Enlace químico|Reacciones químicas", "bimestre_3": "Biología: genética y herencia", "bimestre_4": "Evolución|Biotecnología", "sistema_evaluacion": "Escala vigesimal 00-20"},
        },
        4: {
            "Matemática": {"bimestre_1": "Funciones exponenciales y logarítmicas", "bimestre_2": "Progresiones aritméticas y geométricas", "bimestre_3": "Combinatoria y probabilidad", "bimestre_4": "Estadística inferencial básica", "sistema_evaluacion": "Escala vigesimal 00-20"},
            "Comunicación": {"bimestre_1": "Literatura universal: novela", "bimestre_2": "Ensayo literario y crítica", "bimestre_3": "Narrativa latinoamericana contemporánea", "bimestre_4": "Proyecto de producción textual", "sistema_evaluacion": "Escala vigesimal 00-20"},
            "Historia, Geografía y Economía": {"bimestre_1": "Economía global|Mercados financieros", "bimestre_2": "Derechos humanos|Democracia y ciudadanía", "bimestre_3": "Conflictos del siglo XXI", "bimestre_4": "Desarrollo sostenible|Agenda 2030", "sistema_evaluacion": "Escala vigesimal 00-20"},
            "Ciencia y Tecnología": {"bimestre_1": "Física: movimiento circular y gravitación", "bimestre_2": "Termodinámica", "bimestre_3": "Química orgánica", "bimestre_4": "Tecnología y sociedad: ética científica", "sistema_evaluacion": "Escala vigesimal 00-20"},
        },
        5: {
            "Matemática": {"bimestre_1": "Cálculo diferencial elemental|Límites", "bimestre_2": "Derivadas y aplicaciones", "bimestre_3": "Vectores en el plano|Geometría del espacio", "bimestre_4": "Repaso ECE y preparación universitaria", "sistema_evaluacion": "Escala vigesimal 00-20"},
            "Comunicación": {"bimestre_1": "Literatura peruana del siglo XXI", "bimestre_2": "Textos académicos: tesis y abstract", "bimestre_3": "Orátoria y debate universitario", "bimestre_4": "Proyecto final: ensayo de opinión", "sistema_evaluacion": "Escala vigesimal 00-20"},
            "Historia, Geografía y Economía": {"bimestre_1": "Epistemología de la historia", "bimestre_2": "Perú en el contexto mundial actual", "bimestre_3": "Filosofía política|Estado y sociedad", "bimestre_4": "Proyecto ciudadano integrador", "sistema_evaluacion": "Escala vigesimal 00-20"},
            "Ciencia y Tecnología": {"bimestre_1": "Física moderna: relatividad e óptica", "bimestre_2": "Física nuclear|Radiactividad", "bimestre_3": "Biología molecular|ADN y biotecnología", "bimestre_4": "Proyecto de investigación científica", "sistema_evaluacion": "Escala vigesimal 00-20"},
        },
    },
}

def _seed_silabo_por_defecto(db: Session, nivel: str, grado: int, curso_nombre: str, docente_id: int = None) -> SilaboTemDB:
    """Crea un sílabo con contenido pedagogíco por defecto si no existe."""
    sistema_ev = "Escala literal: AD, A, B, C" if nivel == "PRIMARIA" else "Escala vigesimal: 00-20"
    
    silabo = SilaboTemDB(
        nivel=nivel,
        grado=grado,
        curso_nombre=curso_nombre,
        anno_escolar="2025",
        datos_informativos=f"I.E.P. José María Arguedas\nNivel: {nivel}\nGrado: {grado}°\nÁrea: {curso_nombre}",
        fundamentacion=f"Fundamentación del área de {curso_nombre}.",
        proposito=f"Propósito anual de {curso_nombre}.",
        competencias=f"Competencias base para {curso_nombre}.",
        capacidades=f"Capacidades para {curso_nombre}.",
        estandares=f"Estándares del ciclo para {curso_nombre}.",
        desempennos=f"Desempeños del {grado}° grado para {curso_nombre}.",
        enfoques="Enfoque de Derechos\nEnfoque Inclusivo\nEnfoque Intercultural\nEnfoque de Igualdad de Género\nEnfoque Ambiental",
        organizacion_unidades=f"Organización anual en 4 bimestres de {curso_nombre}.",
        contenidos=f"Contenidos principales de {curso_nombre}.",
        metodologia=f"Aprendizaje basado en competencias.",
        sistema_evaluacion=sistema_ev,
        materiales="Libro de texto del MINEDU\nCuaderno de trabajo\nMaterial concreto\nRecursos digitales",
        bibliografia="Currículo Nacional de la Educación Básica (2019)\nTextos de consulta.",
        docente_id=docente_id,
    )
    db.add(silabo)
    db.commit()
    db.refresh(silabo)
    return silabo


@router.get("/silabos")
async def listar_silabos(
    nivel: Optional[str] = None,
    grado: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["DOCENTE", "ADMIN"]))
):
    """Lista todos los sílabos. Los docentes solo ven los de su nivel."""
    query = db.query(SilaboTemDB)
    if nivel:
        query = query.filter(SilaboTemDB.nivel == nivel.upper())
    if grado:
        query = query.filter(SilaboTemDB.grado == grado)
    silabos = query.all()
    return [
        {
            "id": s.id, "nivel": s.nivel, "grado": s.grado,
            "curso_nombre": s.curso_nombre, "anno_escolar": s.anno_escolar,
            "updated_at": s.updated_at, "created_at": s.created_at,
            "docente_id": s.docente_id,
        }
        for s in silabos
    ]

def _serialize_silabo(s: SilaboTemDB):
    return {
        "id": s.id, "nivel": s.nivel, "grado": s.grado,
        "curso_nombre": s.curso_nombre, "anno_escolar": s.anno_escolar,
        "datos_informativos": s.datos_informativos,
        "fundamentacion": s.fundamentacion,
        "proposito": s.proposito,
        "competencias": s.competencias,
        "capacidades": s.capacidades,
        "estandares": s.estandares,
        "desempennos": s.desempennos,
        "enfoques": s.enfoques,
        "organizacion_unidades": s.organizacion_unidades,
        "contenidos": s.contenidos,
        "metodologia": s.metodologia,
        "sistema_evaluacion": s.sistema_evaluacion,
        "materiales": s.materiales,
        "bibliografia": s.bibliografia,
        "docente_id": s.docente_id,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
    }

@router.get("/silabos/por-curso")
async def obtener_silabo_por_curso(
    nivel: str,
    grado: int,
    curso_nombre: str,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["DOCENTE", "ADMIN"]))
):
    """
    Obtiene (o crea automáticamente) el sílabo de un curso específico.
    Si no existe, se genera con contenido pedagógico acorde al CN 2019.
    """
    s = db.query(SilaboTemDB).filter(
        SilaboTemDB.nivel == nivel.upper(),
        SilaboTemDB.grado == grado,
        SilaboTemDB.curso_nombre == curso_nombre,
    ).first()
    
    if not s:
        # Auto-generar con contenido del currículo nacional
        s = _seed_silabo_por_defecto(db, nivel.upper(), grado, curso_nombre, current_user.user_id)
    
    return _serialize_silabo(s)


@router.get("/silabos/{silabo_id}")
async def obtener_silabo(
    silabo_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["DOCENTE", "ADMIN"]))
):
    """Obtiene el detalle completo de un sílabo."""
    s = db.query(SilaboTemDB).filter(SilaboTemDB.id == silabo_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Sílabo no encontrado.")
    return _serialize_silabo(s)


@router.post("/silabos")
async def crear_silabo(
    data: SilaboCreate,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["DOCENTE", "ADMIN"]))
):
    """Crea un sílabo nuevo. Si ya existe para ese nivel/grado/curso lo rechaza."""
    existe = db.query(SilaboTemDB).filter(
        SilaboTemDB.nivel == data.nivel,
        SilaboTemDB.grado == data.grado,
        SilaboTemDB.curso_nombre == data.curso_nombre,
    ).first()
    if existe:
        raise HTTPException(status_code=400, detail="Ya existe un sílabo para ese nivel/grado/curso. Use el endpoint PUT para actualizarlo.")
    
    silabo = SilaboTemDB(
        nivel=data.nivel, grado=data.grado, curso_nombre=data.curso_nombre,
        anno_escolar=data.anno_escolar, competencias=data.competencias,
        capacidades=data.capacidades, desempennos=data.desempennos,
        enfoques=data.enfoques, bimestre_1=data.bimestre_1,
        bimestre_2=data.bimestre_2, bimestre_3=data.bimestre_3,
        bimestre_4=data.bimestre_4, sistema_evaluacion=data.sistema_evaluacion,
        materiales=data.materiales, docente_id=current_user.user_id,
    )
    db.add(silabo)
    db.commit()
    db.refresh(silabo)
    return {"message": "Sílabo creado exitosamente.", "id": silabo.id}


@router.put("/silabos/{silabo_id}")
async def actualizar_silabo(
    silabo_id: int,
    data: SilaboUpdate,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["DOCENTE", "ADMIN"]))
):
    """Actualiza los contenidos de un sílabo existente."""
    silabo = db.query(SilaboTemDB).filter(SilaboTemDB.id == silabo_id).first()
    if not silabo:
        raise HTTPException(status_code=404, detail="Sílabo no encontrado.")
    
    # Solo el docente propietario o admin puede editar
    if silabo.docente_id and silabo.docente_id != current_user.user_id and current_user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="No tienes permiso para editar este sílabo.")
    
    campos = ["competencias", "capacidades", "desempennos", "enfoques",
              "bimestre_1", "bimestre_2", "bimestre_3", "bimestre_4",
              "sistema_evaluacion", "materiales", "anno_escolar"]
    for campo in campos:
        valor = getattr(data, campo)
        if valor is not None:
            setattr(silabo, campo, valor)
    
    from datetime import datetime
    silabo.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    silabo.docente_id = current_user.user_id  # Quien edita queda como dueño
    db.commit()
    return {"message": "Sílabo actualizado exitosamente."}


@router.post("/admin/silabos/seed-todos")
async def seed_silabos_todos(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    """
    Admin: genera automáticamente sílabos base para todos los grados de
    Primaria (1-6) y Secundaria (1-5) usando el currículo nacional.
    Solo crea los que aún no existen.
    """
    created = 0
    skipped = 0
    
    # Obtener todos los cursos registrados en la BD
    todos_cursos = db.query(CursoDB).all()
    procesados = set()
    
    for c in todos_cursos:
        key = (c.nivel, c.grado, c.nombre)
        if key in procesados:
            continue
        procesados.add(key)
        
        existe = db.query(SilaboTemDB).filter(
            SilaboTemDB.nivel == c.nivel,
            SilaboTemDB.grado == c.grado,
            SilaboTemDB.curso_nombre == c.nombre,
        ).first()
        
        if not existe:
            _seed_silabo_por_defecto(db, c.nivel, c.grado, c.nombre)
            created += 1
        else:
            skipped += 1
    
    return {
        "message": f"Proceso completado: {created} sílabos generados, {skipped} ya existían.",
        "created": created,
        "skipped": skipped
    }

@router.post("/admin/cursos/asignar_docentes")
async def asignar_docentes_cursos(
    batch: AsignacionDocentesBatch,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    count = 0
    for asig in batch.asignaciones:
        curso = db.query(CursoDB).filter(CursoDB.id == asig.curso_id).first()
        if curso:
            curso.docente_id = asig.docente_id
            count += 1
    db.commit()
    return {"message": f"Se actualizaron {count} cursos exitosamente."}

@router.post("/admin/cursos/asignacion_inteligente")
async def asignacion_inteligente(
    payload: AsignacionInteligentePayload,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    cursos = db.query(CursoDB).filter(CursoDB.nivel == payload.nivel).all()
    
    # State tracking for round-robin distribution
    # keys: (nivel, course_name) -> index
    rr_idx = {}
    
    count = 0
    for c in cursos:
        if c.nivel == "PRIMARIA":
            # Check if it's a special course
            is_special = c.nombre in ["Inglés", "Educación Física", "Religión"]
            if is_special:
                docentes_ids = payload.primaria_especialistas.get(c.nombre, [])
                if docentes_ids:
                    key = ("PRIMARIA", c.nombre)
                    idx = rr_idx.get(key, 0)
                    c.docente_id = docentes_ids[idx % len(docentes_ids)]
                    rr_idx[key] = idx + 1
                    count += 1
                else:
                    c.docente_id = None
            else:
                # Core courses handled by Tutor
                tutor_key = f"{c.grado}-{c.seccion}"
                tutor_id = payload.primaria_tutores.get(tutor_key)
                c.docente_id = tutor_id if tutor_id else None
                if tutor_id:
                    count += 1
                    
        elif c.nivel == "SECUNDARIA":
            docentes_ids = payload.secundaria_cursos.get(c.nombre, [])
            if docentes_ids:
                key = ("SECUNDARIA", c.nombre)
                idx = rr_idx.get(key, 0)
                c.docente_id = docentes_ids[idx % len(docentes_ids)]
                rr_idx[key] = idx + 1
                count += 1
            else:
                c.docente_id = None
                
    if payload.nivel == "PRIMARIA":
        # Establecer la tutoría oficial para primaria en base a los tutores asignados
        for key, tutor_id in payload.primaria_tutores.items():
            if tutor_id:
                try:
                    grado_str, seccion = key.split('-')
                    grado = int(grado_str)
                    tutor_existente = db.query(TutorDB).filter(
                        TutorDB.nivel == "PRIMARIA",
                        TutorDB.grado == grado,
                        TutorDB.seccion == seccion
                    ).first()
                    if tutor_existente:
                        tutor_existente.docente_id = tutor_id
                    else:
                        nuevo_tutor = TutorDB(
                            docente_id=tutor_id,
                            nivel="PRIMARIA",
                            grado=grado,
                            seccion=seccion
                        )
                        db.add(nuevo_tutor)
                except Exception as e:
                    print(f"Error procesando tutoría de primaria para {key}: {e}")

    db.commit()
    
    if payload.nivel == "PRIMARIA":
        return {"message": f"Se distribuyeron automáticamente {count} cursos de Primaria y se establecieron los tutores oficiales."}
    else:
        return {"message": f"Se distribuyeron automáticamente {count} cursos de Secundaria."}

@router.get("/docente/mi_horario")
async def docente_mi_horario(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["DOCENTE", "ADMIN"]))
):
    horarios = db.query(HorarioDB).filter(HorarioDB.docente_id == current_user.user_id).all()
    return _format_horario(horarios, db)

@router.get("/admin/horarios/docente/{docente_id}")
async def admin_docente_horario(
    docente_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    horarios = db.query(HorarioDB).filter(HorarioDB.docente_id == docente_id).all()
    return _format_horario(horarios, db)

def _format_horario(horarios, db):
    resultado = []
    for h in horarios:
        curso = db.query(CursoDB).filter(CursoDB.id == h.curso_id).first()
        doc = db.query(UserDB).filter(UserDB.id == h.docente_id).first()
        resultado.append({
            "dia": h.dia,
            "hora_inicio": h.hora_inicio,
            "hora_fin": h.hora_fin,
            "curso": curso.nombre if curso else "Libre",
            "docente": doc.username if doc else "Sin Asignar",
            "aula": f"{h.grado}° {h.seccion} {h.nivel}"
        })
    return resultado

class AtenderCitaReq(BaseModel):
    informe: Optional[str] = None

@router.post("/psicologia/citas/{cita_id}/atender")
async def atender_cita_rendimiento(
    cita_id: int,
    req: AtenderCitaReq,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["PSICOLOGO", "ADMIN"]))
):
    cita = db.query(CitaDB).filter(CitaDB.id == cita_id).first()
    if not cita:
        raise HTTPException(status_code=404, detail="Cita no encontrada.")
    cita.estado = "Atendido"
    if req.informe:
        cita.informe = req.informe
    cita.psicologo_id = current_user.user_id
    db.commit()

    vectorizado = False
    if req.informe:
        try:
            from core.vector_store import vector_store
            import datetime
            vector_store.upsert_record(
                collection_name="historiales_psicologia",
                doc_id=f"cita_{cita.id}",
                content=req.informe,
                metadata={
                    "alumno_id": cita.alumno_id,
                    "psicologo_id": current_user.user_id,
                    "fecha": datetime.date.today().isoformat(),
                    "tipo": "Cita"
                }
            )
            vectorizado = True
        except Exception as e:
            import logging
            logging.error(f"Error al guardar embedding de cita {cita.id}: {e}")

    return {"message": "Cita marcada como Atendida exitosamente.", "vectorizacion": vectorizado}

@router.post("/psicologia/evaluar/{codigo_obs}")
async def evaluar_obs(
    codigo_obs: str,
    body: dict,
    current_user: TokenData = Depends(require_role(["PSICOLOGO", "ADMIN"]))
):
    decision = body.get("decision", "Aprobado")
    observacion = body.get("observacion", "")
    return await orchestrator.evaluar_psicologico(codigo_obs, decision, observacion)


# ======================================================================
# Caja / Pagos
# ======================================================================

@router.post("/caja/pagar")
async def pagar_matricula(
    pago: PagoMatricula,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    # Registrar pago
    resultado = await orchestrator.registrar_pago(pago)
    
    # Auto-crear cuenta de padre e insertar alumno si el expediente es válido
    alumno = db.query(AlumnoDB).filter(AlumnoDB.codigo_est == pago.codigo_est).first()
    state = await school_db.get_state()
    data_admision = state.get("enrolled_students", {}).get(pago.codigo_est)
    

    if data_admision:
        if not alumno:
            # Obtener limites de cupo (El número aplica como límite para CADA sección de ese nivel)
            config_mat = state.get("config_matricula", {})
            cupo_maximo = config_mat.get("cupos_aula_primaria", 30) if data_admision["nivel"] == "PRIMARIA" else config_mat.get("cupos_aula_secundaria", 30)
            
            # Contar alumnos en las secciones A y B del grado al que postula
            count_a = db.query(AlumnoDB).filter(AlumnoDB.nivel == data_admision["nivel"], AlumnoDB.grado == data_admision["grado"], AlumnoDB.seccion == "A").count()
            count_b = db.query(AlumnoDB).filter(AlumnoDB.nivel == data_admision["nivel"], AlumnoDB.grado == data_admision["grado"], AlumnoDB.seccion == "B").count()
            
            # Decidir sección verificando estrictamente el cupo de CADA sección
            if count_a < cupo_maximo and count_b < cupo_maximo:
                # Si ambas tienen espacio, balanceamos
                seccion_asignada = "A" if count_a <= count_b else "B"
            elif count_a < cupo_maximo:
                seccion_asignada = "A"
            elif count_b < cupo_maximo:
                seccion_asignada = "B"
            else:
                # Ambas secciones están llenas
                raise HTTPException(status_code=400, detail=f"No hay cupos disponibles. Todas las secciones (A y B) de {data_admision['grado']}° grado de {data_admision['nivel']} alcanzaron el límite máximo de {cupo_maximo} alumnos cada una.")

            # Crear registro de alumno en la base de datos SQL
            alumno = AlumnoDB(
                nombres=data_admision["nombres"],
                dni=data_admision["dni"],
                nivel=data_admision["nivel"],
                grado=data_admision["grado"],
                seccion=seccion_asignada,
                estado="Matriculado",
                codigo_est=pago.codigo_est
            )
            db.add(alumno)
            db.commit()
            db.refresh(alumno)
            
        if not alumno.apoderado_id:
            nombre_padre = data_admision.get("apoderado", "padre")
            padre_correo = data_admision.get("ap_correo", "iep.josemariaarguedas.1998@gmail.com")
            
            # Crear credenciales usando el primer nombre del padre
            username = nombre_padre.split(" ")[0].lower() + pago.codigo_est[-3:]
            
            # Verificar si ya existe para evitar errores
            existente = db.query(UserDB).filter(UserDB.username == username).first()
            if not existente:
                nuevo_padre = UserDB(
                    username=username,
                    hashed_password=get_password_hash("12345"), # Contraseña genérica temporal 12345
                    role="ALUMNO_PADRE"
                )
                db.add(nuevo_padre)
                db.commit()
                db.refresh(nuevo_padre)
                alumno.apoderado_id = nuevo_padre.id
                db.commit()
            else:
                alumno.apoderado_id = existente.id
                db.commit()
                
            resultado["credenciales"] = {
                "mensaje": "Cuenta de familia procesada. Se envió un correo.",
                "usuario": username,
                "password": "12345"
            }
            
            # Función interna para enviar correo de credenciales
            def mandar_correo_credenciales(usr, pwd, receiver_mail, nom_padre):
                import smtplib
                from email.mime.text import MIMEText
                from email.mime.multipart import MIMEMultipart
                import logging
                import os
                
                if not receiver_mail or "@" not in receiver_mail:
                    receiver_mail = "iep.josemariaarguedas.1998@gmail.com"
                app_password = os.getenv("SMTP_PASSWORD")
                if not app_password:
                    logging.error("SMTP_PASSWORD no configurado. No se enviará el correo de credenciales al apoderado.")
                    return
                
                sender_email = "iep.josemariaarguedas.1998@gmail.com"
                
                msg = MIMEMultipart()
                msg['From'] = sender_email
                msg['To'] = receiver_mail
                msg['Subject'] = "BIENVENIDO AL PORTAL DE FAMILIA - I.E.P. José María Arguedas"
                
                body = f"Estimado {nom_padre},\n\nEl pago de su matrícula se ha procesado con éxito. Se le ha creado o verificado su cuenta institucional para que pueda acceder al 'Portal de Familia' y revisar la libreta de notas de su hijo en tiempo real.\n\nTus credenciales de acceso son:\nUsuario: {usr}\nContraseña: {pwd}\n\nPor favor, ingresa a la plataforma del colegio utilizando estos datos.\n\nAtentamente,\nDirección y Caja."
                msg.attach(MIMEText(body, 'plain', 'utf-8'))
                
                try:
                    server = smtplib.SMTP('smtp.gmail.com', 587)
                    server.starttls()
                    server.login(sender_email, app_password)
                    server.send_message(msg)
                    server.quit()
                    print(f"✅ Correo de credenciales enviado exitosamente a {receiver_mail}")
                    logging.info(f"Correo de credenciales enviado a {receiver_mail}")
                except Exception as e:
                    print(f"❌ Error crítico enviando correo: {e}")
                    logging.error(f"Error enviando correo de credenciales: {e}")

            # Llamar a la función de manera SÍNCRONA para garantizar el envío
            # Esto pausará la respuesta ~1 segundo pero asegurará que el correo salga de Gmail
            mandar_correo_credenciales(username, "12345", padre_correo, nombre_padre)
                
            # Asignación automática de sección con Agente IA
            def asignar_seccion_con_agente(alumno_id: int):
                from models.database import SessionLocal
                from agents.subagents import ag_seccionador
                import logging
                
                local_db = SessionLocal()
                try:
                    al = local_db.query(AlumnoDB).filter(AlumnoDB.id == alumno_id).first()
                    if not al: return
                    
                    count_a = local_db.query(AlumnoDB).filter(AlumnoDB.nivel == al.nivel, AlumnoDB.grado == al.grado, AlumnoDB.seccion == "A").count()
                    count_b = local_db.query(AlumnoDB).filter(AlumnoDB.nivel == al.nivel, AlumnoDB.grado == al.grado, AlumnoDB.seccion == "B").count()
                    
                    resp = swarm_client.run(
                        agent=ag_seccionador,
                        messages=[{"role": "user", "content": f"Alumnos en A: {count_a}. Alumnos en B: {count_b}. ¿A qué sección asigno al nuevo alumno?"}]
                    )
                    
                    asignacion = resp.messages[-1]["content"].strip().upper()
                    if "A" in asignacion:
                        al.seccion = "A"
                    elif "B" in asignacion:
                        al.seccion = "B"
                    else:
                        al.seccion = "A" # Fallback
                        
                    local_db.commit()
                    logging.info(f"Agente IA asignó al alumno {al.nombres} a la sección {al.seccion} (A:{count_a}, B:{count_b})")
                except Exception as e:
                    logging.error(f"Error en Agente Seccionador: {e}")
                finally:
                    local_db.close()
                    
            background_tasks.add_task(asignar_seccion_con_agente, alumno.id)

    return resultado


# ======================================================================
# Docente / Notas
# ======================================================================

@router.get("/docente/cursos")
async def get_docente_cursos(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["DOCENTE"]))
):
    return db.query(CursoDB).filter(CursoDB.docente_id == current_user.user_id).all()

@router.get("/docente/tutorias")
async def get_docente_tutorias(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["DOCENTE"]))
):
    return db.query(TutorDB).filter(TutorDB.docente_id == current_user.user_id).all()

@router.get("/docente/alumnos")
async def get_alumnos_docente(
    curso_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["DOCENTE"]))
):
    if not curso_id:
        return []
    curso = db.query(CursoDB).filter(CursoDB.id == curso_id, CursoDB.docente_id == current_user.user_id).first()
    if not curso:
        raise HTTPException(status_code=403, detail="No tienes acceso a este curso.")
    
    alumnos = db.query(AlumnoDB).filter(
        AlumnoDB.nivel.ilike(curso.nivel),
        AlumnoDB.grado == curso.grado,
        AlumnoDB.seccion == curso.seccion
    ).all()
    return alumnos

@router.get("/tutor/alumnos_riesgo")
async def get_alumnos_riesgo_tutor(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["DOCENTE", "ADMIN"]))
):
    tutoria = db.query(TutorDB).filter(TutorDB.docente_id == current_user.user_id).first()
    if not tutoria:
        return []
        
    alumnos = db.query(AlumnoDB).filter(
        AlumnoDB.nivel.ilike(tutoria.nivel),
        AlumnoDB.grado == tutoria.grado,
        AlumnoDB.seccion == tutoria.seccion
    ).all()
    
    resultados = []
    for a in alumnos:
        notas = db.query(NotaDB).filter(NotaDB.alumno_id == a.id).all()
        # Calculamos riesgo básico si tienen muchas notas bajas
        # En primaria: muchas 'C'. En secundaria: muchas < 11
        riesgo = False
        if tutoria.nivel == 'PRIMARIA':
            notas_c = sum(1 for n in notas if n.valor_letra == 'C')
            if notas_c >= 2: riesgo = True
        else:
            notas_bajas = sum(1 for n in notas if n.valor_numerico is not None and n.valor_numerico < 11)
            if notas_bajas >= 2: riesgo = True
            
        resultados.append({
            "id": a.id,
            "nombres": a.nombres,
            "riesgo": riesgo,
            "dni": a.dni
        })
        
    return resultados

@router.post("/docente/asistencia/batch")
async def registrar_asistencia_batch(
    batch: BatchAsistencia,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["DOCENTE", "ADMIN"]))
):
    alumnos_modificados = set()
    for asis in batch.asistencias:
        nueva_asistencia = AsistenciaDB(
            alumno_id=asis.alumno_id,
            fecha=asis.fecha,
            estado=asis.estado
        )
        db.add(nueva_asistencia)
        alumnos_modificados.add(asis.alumno_id)
    db.commit()

    # Chequeo predictivo de inasistencia > 30%
    import asyncio
    from agents.subagents import ag_monitor
    from agents.orchestrator import swarm_client
    from core.antigravity import school_db
    
    for alumno_id in alumnos_modificados:
        todas = db.query(AsistenciaDB).filter(AsistenciaDB.alumno_id == alumno_id).all()
        total_dias = len(todas)
        faltas = len([a for a in todas if a.estado == 'Falta'])
        
        if total_dias > 0:
            pct_faltas = (faltas / total_dias) * 100
            if pct_faltas > 30.0:
                alumno = db.query(AlumnoDB).filter(AlumnoDB.id == alumno_id).first()
                if alumno:
                    async def fetch_state(): return await school_db.get_state()
                    state = asyncio.run(fetch_state())
                    ap_correo = "iep.josemariaarguedas.1998@gmail.com"
                    if alumno.codigo_est in state.get("enrolled_students", {}):
                        ap_correo = state["enrolled_students"][alumno.codigo_est].get("ap_correo", ap_correo)
                    
                    # Invocar agente IA para Riesgo de Deserción
                    resp = swarm_client.run(
                        agent=ag_monitor,
                        messages=[{"role": "user", "content": f"El alumno {alumno.nombres} ha sobrepasado el 30% de inasistencias ({pct_faltas}% de faltas). Genera una alerta crítica de deserción escolar para el director y un correo urgente para citar a su apoderado inmediatamente."}],
                        context_variables={"ap_correo": ap_correo}
                    )
                    informe = resp.messages[-1]["content"]
                    
                    alertas_ia = state.get("alertas_ia", [])
                    alertas_ia.append({"alumno": alumno.nombres, "reporte": informe, "tipo": "Deserción"})
                    asyncio.run(school_db.set_state({**state, "alertas_ia": alertas_ia}))

    return {"message": f"{len(batch.asistencias)} registros de asistencia guardados y analizados predictivamente."}

@router.post("/docente/notas/batch")
async def subir_notas_batch(
    batch: BatchNota,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["DOCENTE", "ADMIN"]))
):
    # Agrupar por curso_id para no hacer queries redundantes si vienen muchas notas del mismo curso
    cursos_cacheados = {}

    for registro in batch.notas:
        curso_id = registro.curso_id
        if curso_id not in cursos_cacheados:
            curso = db.query(CursoDB).filter(CursoDB.id == curso_id).first()
            if not curso:
                raise HTTPException(status_code=404, detail=f"Curso {curso_id} no encontrado.")
            # Si el usuario NO es admin, verificamos que sea el dueño del curso
            if current_user.role != "ADMIN" and curso.docente_id != current_user.user_id:
                raise HTTPException(status_code=403, detail="No tienes permiso para calificar este curso.")
            cursos_cacheados[curso_id] = curso

        nueva_nota = NotaDB(
            alumno_id=registro.alumno_id,
            curso_id=registro.curso_id,
            docente_id=current_user.user_id,
            criterio=registro.criterio,
            semana=registro.semana,
            valor_numerico=registro.valor_numerico,
            valor_letra=registro.valor_letra,
            observacion=registro.observacion
        )
        db.add(nueva_nota)
    db.commit()
    return {"message": f"{len(batch.notas)} calificaciones registradas exitosamente."}

class ObservacionTutorReq(BaseModel):
    alumno_id: int
    texto: str

@router.post("/docente/observacion")
async def agregar_observacion_tutor(
    req: ObservacionTutorReq,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["DOCENTE", "ADMIN"]))
):
    from datetime import datetime
    nueva_obs = ObservacionDB(
        alumno_id=req.alumno_id,
        docente_id=current_user.user_id,
        fecha=datetime.now().strftime("%d/%m/%Y"),
        texto=req.texto
    )
    db.add(nueva_obs)
    db.commit()
    db.refresh(nueva_obs)
    
    # [RADAR ANTIBULLYING E IA CENTINELA]
    from agents.deep_agents.antibullying_agent import analizar_observacion
    import asyncio
    
    # Análisis sincrónico o asíncrono para detectar riesgo
    try:
        # Se ejecuta de forma síncrona aquí usando await ya que estamos en una función async
        analisis = await analizar_observacion(req.texto)
        if analisis.es_peligro:
            # Crear una cita de urgencia para el psicólogo
            cita_urgencia = CitaDB(
                alumno_id=req.alumno_id,
                motivo=f"🚨 ALERTA IA ANTIBULLYING ({analisis.nivel_urgencia}): {analisis.justificacion}",
                dia=datetime.now().strftime("%d/%m/%Y"),
                hora="URGENCIA",
                estado="Pendiente"
            )
            db.add(cita_urgencia)
            db.commit()
    except Exception as e:
        print("Error en Radar Antibullying:", e)

    vectorizado = False
    try:
        from core.vector_store import vector_store
        import datetime as dt
        vector_store.upsert_record(
            collection_name="historiales_psicologia",
            doc_id=f"observacion_{nueva_obs.id}",
            content=req.texto,
            metadata={
                "alumno_id": req.alumno_id,
                "docente_id": current_user.user_id,
                "fecha": dt.date.today().isoformat(),
                "tipo": "Observacion Docente"
            }
        )
        vectorizado = True
    except Exception as e:
        import logging
        logging.error(f"Error al guardar embedding de observacion {nueva_obs.id}: {e}")

    return {"message": "Observación enviada al Portal de Familia y analizada por la IA Centinela.", "vectorizacion": vectorizado}

@router.get("/tutor/horarios_disponibles")
async def tutor_horarios_disponibles(db: Session = Depends(get_db)):
    dias_laborables = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
    horas_posibles = ["14:00", "15:00", "16:00", "17:00"]
    
    citas_ocupadas = db.query(CitaDB).all()
    ocupados = {(c.dia, c.hora) for c in citas_ocupadas if c.estado != "Cancelado"}
    
    disponibles = []
    for dia in dias_laborables:
        horas_dia = []
        for hora in horas_posibles:
            if (dia, hora) not in ocupados:
                horas_dia.append(hora)
        if horas_dia:
            disponibles.append({"dia": dia, "horas": horas_dia})
            
    return disponibles

@router.post("/tutor/citas")
async def agendar_cita_tutor(
    cita: AgendarCitaRendimiento,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["DOCENTE", "ADMIN"]))
):
    # Validar colision
    existente = db.query(CitaDB).filter(
        CitaDB.dia == cita.dia, 
        CitaDB.hora == cita.hora,
        CitaDB.estado != "Cancelado"
    ).first()
    
    if existente:
        raise HTTPException(status_code=400, detail="El horario seleccionado ya está ocupado.")
        
    nueva_cita = CitaDB(
        alumno_id=cita.alumno_id,
        motivo="Rendimiento",
        tutor_id=current_user.user_id,
        dia=cita.dia,
        hora=cita.hora,
        estado="Pendiente"
    )
    db.add(nueva_cita)
    db.commit()

    # Monitoreo IA Background
    def chequear_reincidencia(alumno_id: int):
        from models.database import SessionLocal
        local_db = SessionLocal()
        try:
            total_citas = local_db.query(CitaDB).filter(CitaDB.alumno_id == alumno_id, CitaDB.motivo == "Rendimiento").count()
            if total_citas >= 3: # Reincidente (3 veces)
                alumno = local_db.query(AlumnoDB).filter(AlumnoDB.id == alumno_id).first()
                if alumno:
                    import asyncio
                    async def fetch_state():
                        return await school_db.get_state()
                    state = asyncio.run(fetch_state())
                    ap_correo = "iep.josemariaarguedas.1998@gmail.com"
                    if alumno.codigo_est in state.get("enrolled_students", {}):
                        ap_correo = state["enrolled_students"][alumno.codigo_est].get("ap_correo", ap_correo)

                    # Invocar agente monitor
                    resp = swarm_client.run(
                        agent=ag_monitor,
                        messages=[{"role": "user", "content": f"El alumno {alumno.nombres} ya tiene {total_citas} citas de rendimiento este mes. Genera el reporte para la directora y envía el correo urgente al padre indicándole que ingrese al portal porque el caso de {alumno.nombres} es crítico."}],
                        context_variables={"ap_correo": ap_correo}
                    )
                    informe = resp.messages[-1]["content"]
                    # Guardar alerta en state
                    import asyncio
                    async def save_alert():
                        state = await school_db.get_state()
                        if "alertas_ia" not in state:
                            state["alertas_ia"] = []
                        state["alertas_ia"].append({
                            "alumno": alumno.nombres,
                            "alumno_id": alumno.id,
                            "apoderado_id": alumno.apoderado_id,
                            "citas": total_citas,
                            "reporte": informe
                        })
                        await school_db.set_state(state)
                    asyncio.run(save_alert())
        finally:
            local_db.close()

    background_tasks.add_task(chequear_reincidencia, cita.alumno_id)
    return {"message": "Cita tripartita agendada con Psicología."}



# ======================================================================
# Familia / Padres
# ======================================================================

@router.get("/padre/libreta")
async def get_padre_libreta(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ALUMNO_PADRE"]))
):
    # Encontrar hijos
    alumnos = db.query(AlumnoDB).filter(AlumnoDB.apoderado_id == current_user.user_id).all()
    if not alumnos:
        raise HTTPException(status_code=404, detail="No se encontraron alumnos asociados a esta cuenta.")
        
    alumno = alumnos[0] # Tomamos el primero para la demo
    
    # Extraer notas
    notas = db.query(NotaDB).filter(NotaDB.alumno_id == alumno.id).all()
    
    # Procesar la libreta consolidando por curso
    libreta_dict = {}
    for n in notas:
        curso = db.query(CursoDB).filter(CursoDB.id == n.curso_id).first()
        nombre_curso = curso.nombre if curso else f"Curso {n.curso_id}"
        if nombre_curso not in libreta_dict:
            libreta_dict[nombre_curso] = {"curso": nombre_curso, "criterios": {}}
        
        # Guardar valor letra o numerico
        val = n.valor_letra if n.valor_letra else str(n.valor_numerico)
        libreta_dict[nombre_curso]["criterios"][n.criterio.lower()] = val
        
    state = await school_db.get_state()
    alertas_ia = [a for a in state.get("alertas_ia", []) if a.get("apoderado_id") == current_user.user_id]
        
    tutor_db = db.query(TutorDB).filter(
        TutorDB.nivel.ilike(alumno.nivel),
        TutorDB.grado == alumno.grado,
        TutorDB.seccion == alumno.seccion
    ).first()
    
    tutor_nombre = "No Asignado"
    if tutor_db:
        tutor_user = db.query(UserDB).filter(UserDB.id == tutor_db.docente_id).first()
        if tutor_user: tutor_nombre = tutor_user.username
        
    asistencias_db = db.query(AsistenciaDB).filter(AsistenciaDB.alumno_id == alumno.id).all()
    asistencias = [{"fecha": a.fecha, "estado": a.estado} for a in asistencias_db]

    total_dias = len(asistencias_db)
    faltas = len([a for a in asistencias_db if a.estado == 'Falta'])
    pct_faltas = (faltas / total_dias * 100) if total_dias > 0 else 0

    observaciones_db = db.query(ObservacionDB).filter(ObservacionDB.alumno_id == alumno.id).all()
    observaciones = []
    for o in observaciones_db:
        doc = db.query(UserDB).filter(UserDB.id == o.docente_id).first()
        observaciones.append({
            "id": o.id,
            "fecha": o.fecha,
            "texto": o.texto,
            "docente": doc.username if doc else "Docente"
        })

    citas_pendientes = db.query(CitaDB).filter(CitaDB.alumno_id == alumno.id, CitaDB.estado == "Pendiente", CitaDB.motivo == "Rendimiento").all()
        
    horarios = db.query(HorarioDB).filter(
        HorarioDB.nivel == alumno.nivel.upper(),
        HorarioDB.grado == alumno.grado,
        HorarioDB.seccion == alumno.seccion
    ).all()
    
    horario_lista = []
    for h in horarios:
        curso = db.query(CursoDB).filter(CursoDB.id == h.curso_id).first()
        doc = db.query(UserDB).filter(UserDB.id == h.docente_id).first() if h.docente_id else None
        horario_lista.append({
            "dia": h.dia,
            "hora_inicio": h.hora_inicio,
            "hora_fin": h.hora_fin,
            "curso": curso.nombre if curso else "ESTUDIO LIBRE",
            "docente": doc.username if doc else "Sin Asignar"
        })

    return {
        "alumno": {
            "nombres": alumno.nombres,
            "nivel": alumno.nivel,
            "grado": alumno.grado,
            "seccion": alumno.seccion,
            "tutor": tutor_nombre
        },
        "libreta": list(libreta_dict.values()),
        "horario": horario_lista,
        "asistencias": asistencias,
        "porcentaje_inasistencia": pct_faltas,
        "observaciones": observaciones,
        "citas_psicologia": [{"dia": c.dia, "hora": c.hora, "motivo": c.motivo} for c in citas_pendientes],
        "alertas_ia": alertas_ia
    }

# ======================================================================
# Admin
# ======================================================================

@router.get("/admin/telemetry")
async def get_telemetry(current_user: TokenData = Depends(require_role(["ADMIN"]))):
    return telemetry_store.model_dump()

@router.get("/admin/docentes")
async def list_docentes(db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["ADMIN"]))):
    return db.query(UserDB).filter(UserDB.role == "DOCENTE").all()

@router.get("/admin/citas_historial")
async def historial_citas_admin(db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["ADMIN", "PSICOLOGO"]))):
    citas = db.query(CitaDB).all()
    resultado = []
    for c in citas:
        al = db.query(AlumnoDB).filter(AlumnoDB.id == c.alumno_id).first()
        resultado.append({
            "id": c.id,
            "motivo": c.motivo,
            "dia": c.dia,
            "hora": c.hora,
            "estado": c.estado,
            "alumno": al.nombres if al else "Desconocido"
        })
    return resultado



@router.get("/admin/state")
async def get_state(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ADMIN", "PSICOLOGO", "DOCENTE"]))
):
    state = await school_db.get_state()
    # Inyectar alumnos de la base de datos SQL para que no desaparezcan del panel si se reinicia el JSON
    db_students = db.query(AlumnoDB).all()
    if "enrolled_students" not in state:
        state["enrolled_students"] = {}
        
    for al in db_students:
        state["enrolled_students"][al.codigo_est] = {
            "nombres": al.nombres,
            "dni": al.dni,
            "nivel": al.nivel,
            "grado": al.grado,
            "seccion": al.seccion,
            "estado_proceso": al.estado,
            "apoderado": "Apoderado Registrado", # Placeholder since we didn't join UserDB, enough for dashboard
            "ap_correo": ""
        }
    return state

@router.post("/admin/cursos/asignacion_primaria_ia")
async def asignacion_primaria_ia(db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["ADMIN"]))):
    import json
    from langchain_groq import ChatGroq
    from langchain_core.prompts import PromptTemplate

    docentes = db.query(UserDB).filter(UserDB.role == "DOCENTE", UserDB.nivel_asignado == "PRIMARIA").all()
    if not docentes:
        return {"tutores": {}, "especialistas": {}}
    
    docentes_info = [{"id": d.id, "nombre": d.username} for d in docentes]
    
    prompt = PromptTemplate.from_template("""Eres un asistente escolar de IA.
Tienes la siguiente lista de docentes de primaria:
{docentes}

Tu tarea es:
1. Asignar 1 tutor único a cada una de las siguientes aulas: 1-A, 1-B, 2-A, 2-B, 3-A, 3-B, 4-A, 4-B, 5-A, 5-B, 6-A, 6-B. (12 aulas = 12 docentes únicos).
2. Asignar 1 o 2 docentes (distintos a los 12 seleccionados) a los cursos especiales rotativos: 'Inglés', 'Educación Física', 'Religión'. Intenta usar a los docentes restantes.

Responde ÚNICAMENTE con un JSON en el siguiente formato, sin markdown ni comillas especiales:
{{
  "tutores": {{
    "1-A": ID_DOCENTE,
    "1-B": ID_DOCENTE
  }},
  "especialistas": {{
    "Inglés": [ID_DOCENTE],
    "Educación Física": [ID_DOCENTE],
    "Religión": [ID_DOCENTE]
  }}
}}
""")
    
    try:
        llm = ChatGroq(tags=["api"], metadata={"agent_name": "api"}, model="llama-3.1-8b-instant", temperature=0.1)
        chain = prompt | llm
        response = await chain.ainvoke({"docentes": json.dumps(docentes_info)})
        raw_json = response.content.replace('```json', '').replace('```', '').strip()
        data = json.loads(raw_json)
        return data
    except Exception as e:
        print(f"Error IA: {e}")
        return {"tutores": {}, "especialistas": {}}

@router.get("/admin/cursos_list")
async def list_cursos_admin(db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["ADMIN"]))):
    cursos = db.query(CursoDB).all()
    return [{"id": c.id, "nombre": c.nombre, "nivel": c.nivel, "grado": c.grado, "seccion": c.seccion or "A", "docente_id": c.docente_id} for c in cursos]


class BatchAdmisionRequest(BaseModel):
    archivos_ids: list[str]

@router.post("/admin/tasks/batch-admision")
async def trigger_batch_admision(
    req: BatchAdmisionRequest,
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    """Encola una tarea pesada en Celery (ej. procesar 100 PDFs de admisión)."""
    task = procesar_admision_batch.delay(req.archivos_ids)
    return {"message": "Tarea encolada", "task_id": task.id}

@router.get("/admin/tasks/status/{task_id}")
async def get_task_status(
    task_id: str,
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    """Verifica el estado de una tarea pesada en Celery."""
    result = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None
    }


class UserCreate(BaseModel):
    username: str
    password: str
    role: str
    nivel_asignado: Optional[str] = None


@router.post("/admin/users")
async def create_user(
    user: UserCreate,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    if user.role not in ["DOCENTE", "PSICOLOGO", "SECRETARIO"]:
        raise HTTPException(status_code=400, detail="Rol inválido. Solo DOCENTE, PSICOLOGO o SECRETARIO.")
    if db.query(UserDB).filter(UserDB.username == user.username).first():
        raise HTTPException(status_code=400, detail="El usuario ya existe.")
    new_user = UserDB(
        username=user.username,
        hashed_password=get_password_hash(user.password),
        role=user.role,
        nivel_asignado=user.nivel_asignado
    )
    db.add(new_user)
    db.commit()
    return {"message": f"Cuenta {user.username} ({user.role}) creada con éxito."}

@router.get("/admin/users")
async def get_users(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    users = db.query(UserDB).filter(UserDB.role.in_(["DOCENTE", "PSICOLOGO", "SECRETARIO"])).all()
    return [{"id": u.id, "username": u.username, "role": u.role, "is_active": u.is_active, "nivel_asignado": u.nivel_asignado} for u in users]

@router.post("/admin/users/{user_id}/toggle_status")
async def toggle_user_status(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
        
    if user.is_active and user.role == "SECRETARIO":
        caja_abierta = db.query(CajaDiariaDB).filter(
            CajaDiariaDB.secretario_id == user.id,
            CajaDiariaDB.estado == "Abierta"
        ).first()
        if caja_abierta:
            raise HTTPException(status_code=400, detail="No se puede suspender al secretario porque tiene la caja abierta. Pídale que cierre la caja primero.")
            
    user.is_active = not user.is_active
    db.commit()
    return {"message": f"Usuario {user.username} {'activado' if user.is_active else 'suspendido'} correctamente."}


@router.post("/admin/cursos")
async def create_curso(
    curso: CursoCreate,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    creados = []
    omitidos = []

    for grado in curso.grados:
        # Buscar todas las secciones que existen en ese nivel/grado
        secciones_existentes = (
            db.query(CursoDB.seccion)
            .filter(CursoDB.nivel == curso.nivel, CursoDB.grado == grado)
            .distinct()
            .all()
        )
        secciones = [s[0] for s in secciones_existentes] if secciones_existentes else ["A"]

        for seccion in secciones:
            # Validar duplicado
            existe = db.query(CursoDB).filter(
                CursoDB.nombre == curso.nombre,
                CursoDB.nivel == curso.nivel,
                CursoDB.grado == grado,
                CursoDB.seccion == seccion
            ).first()

            if existe:
                omitidos.append(f"{grado}°{seccion}")
                continue

            nuevo = CursoDB(
                nombre=curso.nombre,
                nivel=curso.nivel,
                grado=grado,
                seccion=seccion,
                docente_id=curso.docente_id
            )
            db.add(nuevo)
            creados.append(f"{grado}°{seccion}")

    db.commit()

    if not creados:
        raise HTTPException(
            status_code=400,
            detail=f"El curso '{curso.nombre}' ya existe en todas las combinaciones seleccionadas: {', '.join(omitidos)}"
        )

    resumen = f"Curso '{curso.nombre}' creado en: {', '.join(creados)}."
    if omitidos:
        resumen += f" Omitidos por duplicado: {', '.join(omitidos)}."
    return {"message": resumen}

from schemas.mcp import AulaPrimariaCreate, AsignarDocenteRequest

@router.patch("/admin/cursos/{curso_id}/asignar-docente", tags=["Admin"])
def asignar_docente_curso(
    curso_id: int, 
    request: AsignarDocenteRequest, 
    db: Session = Depends(get_db), 
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    curso = db.query(CursoDB).filter(CursoDB.id == curso_id).first()
    if not curso:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    
    if request.docente_id is not None:
        docente = db.query(UserDB).filter(UserDB.id == request.docente_id, UserDB.role == "DOCENTE").first()
        if not docente:
            raise HTTPException(status_code=404, detail="Docente no encontrado o inválido")
            
    curso.docente_id = request.docente_id
    db.commit()
    return {"status": "success", "message": "Docente asignado correctamente al curso"}

@router.post("/admin/aula_primaria")
async def create_aula_primaria(
    aula: AulaPrimariaCreate,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    # Cursos base
    cursos_base = ["Matemática", "Comunicación", "Ciencias Naturales", "Personal Social"]
    for c in cursos_base:
        nuevo_curso = CursoDB(
            nombre=c,
            nivel="PRIMARIA",
            grado=aula.grado,
            seccion=aula.seccion,
            docente_id=aula.docente_id
        )
        db.add(nuevo_curso)
    
    # Asignar tutor automáticamente
    tutor_existente = db.query(TutorDB).filter(
        TutorDB.docente_id == aula.docente_id,
        TutorDB.nivel == "PRIMARIA",
        TutorDB.grado == aula.grado,
        TutorDB.seccion == aula.seccion
    ).first()
    
    if not tutor_existente:
        nuevo_tutor = TutorDB(
            docente_id=aula.docente_id,
            nivel="PRIMARIA",
            grado=aula.grado,
            seccion=aula.seccion
        )
        db.add(nuevo_tutor)
        
    db.commit()
    return {"message": f"Aula de Primaria asignada. Se generaron 4 cursos y la tutoría automáticamente."}

@router.post("/admin/tutores")
async def create_tutor(
    tutor: TutorCreate,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["ADMIN"]))
):
    # Validar que el docente no sea ya tutor de otra sección
    tutor_existente = db.query(TutorDB).filter(TutorDB.docente_id == tutor.docente_id).first()
    if tutor_existente:
        raise HTTPException(status_code=400, detail=f"Este docente ya es tutor de la sección {tutor_existente.grado}º {tutor_existente.seccion} {tutor_existente.nivel}.")
        
    # Validar que el aula no tenga ya un tutor
    aula_existente = db.query(TutorDB).filter(
        TutorDB.nivel == tutor.nivel,
        TutorDB.grado == tutor.grado,
        TutorDB.seccion == tutor.seccion
    ).first()
    if aula_existente:
        raise HTTPException(status_code=400, detail=f"El aula {tutor.grado}º {tutor.seccion} {tutor.nivel} ya tiene un tutor asignado.")

    nuevo = TutorDB(
        docente_id=tutor.docente_id,
        nivel=tutor.nivel,
        grado=tutor.grado,
        seccion=tutor.seccion
    )
    db.add(nuevo)
    db.commit()
    return {"message": "Tutor asignado con éxito."}

@router.get("/admin/tutores_asignados")
async def list_tutores_asignados(db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["ADMIN"]))):
    tutores = db.query(TutorDB).all()
    resultado = []
    for t in tutores:
        doc = db.query(UserDB).filter(UserDB.id == t.docente_id).first()
        if doc:
            resultado.append({
                "id": t.id,
                "docente": doc.username,
                "nivel": t.nivel,
                "grado": t.grado,
                "seccion": t.seccion
            })
    return {"tutores": resultado}

@router.post("/admin/cierre_escolar")
async def cierre_escolar(db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["ADMIN"]))):
    alumnos = db.query(AlumnoDB).all()
    
    for alumno in alumnos:
        # Calcular promedio
        notas = db.query(NotaDB).filter(NotaDB.alumno_id == alumno.id).all()
        promedio = 0.0
        
        if not notas:
            alumno.promedio_final = 0.0
            alumno.estado = "Repitente"
        else:
            if alumno.nivel == "PRIMARIA":
                # Primaria usa letras. Simplificamos: A=15, B=12, C=10, AD=18
                sum_letras = 0
                count_letras = 0
                for n in notas:
                    if n.valor_letra:
                        count_letras += 1
                        if n.valor_letra == "AD": sum_letras += 18
                        elif n.valor_letra == "A": sum_letras += 15
                        elif n.valor_letra == "B": sum_letras += 12
                        else: sum_letras += 10
                promedio = sum_letras / count_letras if count_letras > 0 else 0
            else:
                # Secundaria: Calculamos con base en promedios numéricos
                # Simplificación: promedio aritmético de las notas del estudiante. En realidad NotaDB guarda JSON.
                # Como NotaDB en el backend original almacena "valor_letra" o criterios en la tabla original o en state:
                # Pero la estructura usa `valor_letra` en db o `criterios` en DB/state.
                sum_num = 0
                count_num = 0
                for n in notas:
                    if n.valor_letra:
                        try:
                            sum_num += float(n.valor_letra)
                            count_num += 1
                        except:
                            pass
                promedio = sum_num / count_num if count_num > 0 else 0.0
                
            alumno.promedio_final = round(promedio, 2)
            if promedio >= 11.0:
                alumno.estado = "Aprobado"
                # Enviar correo de diploma
                if alumno.apoderado_id:
                    apoderado = db.query(UserDB).filter(UserDB.id == alumno.apoderado_id).first()
                    if apoderado and apoderado.email:
                        msg = f"DIPLOMA DE EXCELENCIA\n\nEstimado apoderado, felicitamos a su menor hijo {alumno.nombres} por haber aprobado el año escolar satisfactoriamente con un promedio de {alumno.promedio_final}."
                        try:
                            import smtplib
                            from email.mime.text import MIMEText
                            from email.mime.multipart import MIMEMultipart
                            s = smtplib.SMTP('smtp.gmail.com', 587)
                            s.starttls()
                            s.login("iep.josemariaarguedas.1998@gmail.com", "bpxo yoxl aaqe jbpt")
                            correo = MIMEMultipart()
                            correo['From'] = "iep.josemariaarguedas.1998@gmail.com"
                            correo['To'] = apoderado.email
                            correo['Subject'] = "Diploma de Fin de Año"
                            correo.attach(MIMEText(msg, 'plain'))
                            s.send_message(correo)
                            s.quit()
                        except Exception as e:
                            print("Error enviando correo de fin de año:", e)
            else:
                alumno.estado = "Repitente"
                if alumno.apoderado_id:
                    apoderado = db.query(UserDB).filter(UserDB.id == alumno.apoderado_id).first()
                    if apoderado and apoderado.email:
                        msg = f"REPORTE ACADÉMICO\n\nEstimado apoderado, se le informa que su menor hijo {alumno.nombres} no ha superado el promedio mínimo (promedio final: {alumno.promedio_final}) y repite de año."
                        try:
                            import smtplib
                            from email.mime.text import MIMEText
                            from email.mime.multipart import MIMEMultipart
                            s = smtplib.SMTP('smtp.gmail.com', 587)
                            s.starttls()
                            s.login("iep.josemariaarguedas.1998@gmail.com", "bpxo yoxl aaqe jbpt")
                            correo = MIMEMultipart()
                            correo['From'] = "iep.josemariaarguedas.1998@gmail.com"
                            correo['To'] = apoderado.email
                            correo['Subject'] = "Reporte Académico de Fin de Año"
                            correo.attach(MIMEText(msg, 'plain'))
                            s.send_message(correo)
                            s.quit()
                        except Exception as e:
                            print("Error enviando correo de fin de año:", e)
    # Limpieza de tutores y horarios
    db.query(HorarioDB).delete()
    db.query(TutorDB).delete()
    
    # También limpiar asignaciones de cursos a docentes
    cursos = db.query(CursoDB).all()
    for c in cursos:
        c.docente_id = None

    db.commit()
    return {"message": "Cierre de año ejecutado. Promedios calculados, estados actualizados, horarios y tutores reiniciados."}

# ======================================================================
# API MINEDU (Catálogo Curricular Nacional)
# ======================================================================

@router.get("/minedu_competencias")
async def get_minedu_competencias(
    curso: Optional[str] = None,
    nivel: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(CompetenciaMINEDUDB)
    if curso:
        query = query.filter(CompetenciaMINEDUDB.curso_nombre.ilike(f"%{curso}%"))
    if nivel:
        query = query.filter(CompetenciaMINEDUDB.nivel.ilike(f"%{nivel}%"))
    resultados = query.all()
    return [{"id": c.id, "nivel": c.nivel, "curso_nombre": c.curso_nombre, "descripcion": c.descripcion} for c in resultados]

@router.get("/minedu_capacidades")
async def get_minedu_capacidades(
    competencia_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(CapacidadMINEDUDB)
    if competencia_id:
        query = query.filter(CapacidadMINEDUDB.competencia_id == competencia_id)
    resultados = query.all()
    return [{"id": c.id, "competencia_id": c.competencia_id, "descripcion": c.descripcion} for c in resultados]

@router.get("/minedu_estandares")
async def get_minedu_estandares(
    curso: Optional[str] = None,
    nivel: Optional[str] = None,
    ciclo: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(EstandarMINEDUDB)
    if curso:
        query = query.filter(EstandarMINEDUDB.curso_nombre.ilike(f"%{curso}%"))
    if nivel:
        query = query.filter(EstandarMINEDUDB.nivel.ilike(f"%{nivel}%"))
    if ciclo:
        query = query.filter(EstandarMINEDUDB.ciclo.ilike(f"%{ciclo}%"))
    resultados = query.all()
    return [{"id": e.id, "nivel": e.nivel, "ciclo": e.ciclo, "curso_nombre": e.curso_nombre, "descripcion": e.descripcion} for e in resultados]

@router.get("/minedu_desempenos")
async def get_minedu_desempenos(
    curso: Optional[str] = None,
    nivel: Optional[str] = None,
    grado: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(DesempenoMINEDUDB)
    if curso:
        query = query.filter(DesempenoMINEDUDB.curso_nombre.ilike(f"%{curso}%"))
    if nivel:
        query = query.filter(DesempenoMINEDUDB.nivel.ilike(f"%{nivel}%"))
    if grado:
        query = query.filter(DesempenoMINEDUDB.grado == grado)
    resultados = query.all()
    return [{"id": d.id, "nivel": d.nivel, "grado": d.grado, "curso_nombre": d.curso_nombre, "descripcion": d.descripcion} for d in resultados]
