import logging
from typing import Dict, Any, Literal
import json
import re

from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

from agents.deep_agents.graph_state import SilaboState
from agents.orchestrator import GROQ_KEYS

logger = logging.getLogger(__name__)

def _make_llm(temperature: float = 0.3, key_index: int = 0) -> ChatGroq:
    key = GROQ_KEYS[key_index % len(GROQ_KEYS)]
    return ChatGroq(tags=["silabo_generator"], metadata={"agent_name": "silabo_generator"}, 
        model_name="llama-3.1-8b-instant",
        api_key=key,
        temperature=temperature,
        max_retries=1,
    )

def _invoke_with_rotation(messages: list, temperature: float = 0.3) -> str:
    """Intenta llamar al LLM rotando por todas las API keys disponibles ante un 429."""
    last_error = None
    for i in range(len(GROQ_KEYS)):
        try:
            llm = _make_llm(temperature=temperature, key_index=i)
            response = llm.invoke(messages)
            
            # REGISTRO DE TOKENS EN TELEMETRÍA GLOBAL
            try:
                from core.antigravity import telemetry_store
                tokens = response.response_metadata.get('token_usage', {}).get('total_tokens', 0)
                if tokens > 0:
                    telemetry_store.log(latency=500.0, success=True, tokens=tokens, trace_id="silabo_gen")
            except Exception:
                pass
                
            return response.content
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate_limit" in err_str.lower():
                logger.warning(f"Key {i+1}/{len(GROQ_KEYS)} con rate limit, rotando...")
                last_error = e
                continue
            raise e
    raise last_error or Exception("Todas las API keys agotaron su cuota.")

def _extract_json(text: str) -> dict:
    """Extrae el primer bloque JSON de un texto, ignorando el resto."""
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    return {}

# ─────────────────────────────────────────────────────────────────────────────
# Nodo 1: DB Validation
# ─────────────────────────────────────────────────────────────────────────────
def db_validation_node(state: SilaboState) -> Dict[str, Any]:
    from models.database import SessionLocal, CompetenciaMINEDUDB, CapacidadMINEDUDB, EstandarMINEDUDB, DesempenoMINEDUDB
    db = SessionLocal()
    try:
        area_query = state['area']
        areas_to_check = ["Comunicación", "Matemática", "Personal Social", "Ciencia y Tecnología"] if area_query == "Áreas Integradas" else [area_query]

        competencias_str, capacidades_str, estandares_str, desempennos_str = [], [], [], []

        for ar in areas_to_check:
            comps = db.query(CompetenciaMINEDUDB).filter_by(nivel=state['nivel'], curso_nombre=ar).all()
            if not comps:
                # No abortar, solo generar nota de ausencia
                competencias_str.append(f"[{ar}] Competencias según el CNEB 2019 para {ar}.")
            else:
                for c in comps:
                    competencias_str.append(f"[{ar}] {c.descripcion}")
                    caps = db.query(CapacidadMINEDUDB).filter_by(competencia_id=c.id).all()
                    for cap in caps:
                        capacidades_str.append(f"[{ar}] {cap.descripcion}")

            ests = db.query(EstandarMINEDUDB).filter_by(nivel=state['nivel'], curso_nombre=ar).all()
            for e in ests:
                estandares_str.append(f"[{ar}] {e.descripcion}")

            deses = db.query(DesempenoMINEDUDB).filter_by(nivel=state['nivel'], grado=state['grado'], curso_nombre=ar).all()
            for d in deses:
                desempennos_str.append(f"[{ar}] {d.descripcion}")

        return {
            "competencias": "\n".join(competencias_str) or f"Competencias del CNEB para {state['area']}.",
            "capacidades": "\n".join(capacidades_str) or f"Capacidades para {state['area']}.",
            "estandares": "\n".join(estandares_str) or f"Estándares para {state['area']}.",
            "desempennos": "\n".join(desempennos_str) or f"Desempeños del {state['grado']}° grado.",
            "error_msg": None,
        }
    except Exception as e:
        return {"error_msg": f"Error BD: {str(e)}"}
    finally:
        db.close()

# ─────────────────────────────────────────────────────────────────────────────
# Nodo 2: Pedagogical + Planning Agent (todo en uno para reducir llamadas API)
# ─────────────────────────────────────────────────────────────────────────────
def generation_agent_node(state: SilaboState) -> Dict[str, Any]:
    if state.get("error_msg"):
        return {}

    nivel = state['nivel']
    grado = state['grado']
    area = state['area']
    anno = state['anno_escolar']
    competencias = state.get('competencias', '')[:800]

    prompt = f"""Genera un sílabo anual EBR del Perú para:
- Área: {area}
- Nivel: {nivel}
- Grado: {grado}°
- Año: {anno}
- Competencias base: {competencias}

Responde ÚNICAMENTE con un objeto JSON válido con estas claves exactas (sin texto antes ni después):
{{
  "datos_informativos": "I.E.P. José María Arguedas | Área: {area} | Nivel: {nivel} | Grado: {grado}° | Año: {anno} | Horas semanales: 4",
  "fundamentacion": "texto de 2-3 párrafos sobre la naturaleza del área",
  "proposito": "texto con el propósito anual de aprendizaje",
  "enfoques": "Enfoque de Derechos, Enfoque Inclusivo, Enfoque Intercultural",
  "organizacion_unidades": "Unidad 1 (Mar-Abr): Título\\nUnidad 2 (May-Jun): Título\\nUnidad 3 (Ago-Sep): Título\\nUnidad 4 (Oct-Nov): Título",
  "contenidos": "Temas principales del área por unidad",
  "metodologia": "Descripción de la metodología activa basada en competencias",
  "sistema_evaluacion": "{'Escala literal AD/A/B/C' if nivel == 'PRIMARIA' else 'Escala vigesimal 0-20'}. Instrumentos: listas de cotejo, rúbricas, pruebas.",
  "materiales": "Libro MINEDU, cuaderno de trabajo, material concreto, recursos TIC",
  "bibliografia": "Currículo Nacional 2019 (MINEDU), Textos escolares oficiales"
}}"""

    try:
        content = _invoke_with_rotation([
            SystemMessage(content="Eres un especialista curricular del MINEDU Perú. Solo respondes con JSON válido."),
            HumanMessage(content=prompt)
        ], temperature=0.3)
        data = _extract_json(content)

        if not data:
            # Fallback si el LLM no generó JSON
            data = {}

        return {
            "datos_informativos": data.get("datos_informativos", f"I.E.P. José María Arguedas | {area} | {nivel} | {grado}° | {anno}"),
            "fundamentacion": data.get("fundamentacion", f"El área de {area} desarrolla competencias esenciales para la formación integral del estudiante de {nivel}, alineadas al CNEB 2019."),
            "proposito": data.get("proposito", f"Al finalizar el año, el estudiante de {grado}° de {nivel} desarrollará las competencias del área de {area} establecidas en el CNEB."),
            "enfoques": data.get("enfoques", "Enfoque de Derechos\nEnfoque Inclusivo o de Atención a la Diversidad\nEnfoque Intercultural\nEnfoque de Igualdad de Género\nEnfoque Ambiental"),
            "organizacion_unidades": data.get("organizacion_unidades", f"Unidad 1 (Mar-Abr)\nUnidad 2 (May-Jun)\nUnidad 3 (Ago-Sep)\nUnidad 4 (Oct-Nov)"),
            "contenidos": data.get("contenidos", f"Contenidos seleccionados para {area} - {grado}° de {nivel}."),
            "metodologia": data.get("metodologia", "Aprendizaje basado en competencias. Trabajo colaborativo, proyectos de aula, retroalimentación formativa."),
            "sistema_evaluacion": data.get("sistema_evaluacion", "Escala literal AD/A/B/C" if nivel == "PRIMARIA" else "Escala vigesimal 0-20. Rúbricas y pruebas escritas."),
            "materiales": data.get("materiales", "Libro de texto MINEDU\nCuaderno de trabajo\nMaterial concreto\nRecursos digitales y TIC"),
            "bibliografia": data.get("bibliografia", "Currículo Nacional de la Educación Básica - MINEDU (2019)\nTextos escolares oficiales del grado"),
            "validacion_ok": True,
        }
    except Exception as e:
        logger.error(f"Error en generation_agent: {e}")
        return {"error_msg": f"Error generando sílabo: {str(e)[:200]}"}

# ─────────────────────────────────────────────────────────────────────────────
# Nodo 3: Persistence Agent
# ─────────────────────────────────────────────────────────────────────────────
def persistence_agent_node(state: SilaboState) -> Dict[str, Any]:
    if state.get("error_msg"):
        return {"silabo_id": None}
    try:
        from core.utils import ahora_lima
        from models.database import SessionLocal, SilaboTemDB

        db = SessionLocal()
        try:
            existente = db.query(SilaboTemDB).filter(
                SilaboTemDB.nivel == state["nivel"],
                SilaboTemDB.grado == state["grado"],
                SilaboTemDB.curso_nombre == state["area"],
            ).first()

            now_str = ahora_lima().strftime("%Y-%m-%d %H:%M")
            fields = {
                "anno_escolar": state["anno_escolar"],
                "datos_informativos": state.get("datos_informativos", ""),
                "fundamentacion": state.get("fundamentacion", ""),
                "proposito": state.get("proposito", ""),
                "competencias": state.get("competencias", ""),
                "capacidades": state.get("capacidades", ""),
                "estandares": state.get("estandares", ""),
                "desempennos": state.get("desempennos", ""),
                "enfoques": state.get("enfoques", ""),
                "organizacion_unidades": state.get("organizacion_unidades", ""),
                "contenidos": state.get("contenidos", ""),
                "metodologia": state.get("metodologia", ""),
                "sistema_evaluacion": state.get("sistema_evaluacion", ""),
                "materiales": state.get("materiales", ""),
                "bibliografia": state.get("bibliografia", ""),
                "docente_id": state.get("docente_id"),
            }

            for k, v in fields.items():
                if isinstance(v, (dict, list)):
                    fields[k] = json.dumps(v, ensure_ascii=False)

            if existente:
                for k, v in fields.items():
                    setattr(existente, k, v)
                existente.updated_at = now_str
                db.commit()
                silabo_id = existente.id
            else:
                nuevo = SilaboTemDB(
                    nivel=state["nivel"],
                    grado=state["grado"],
                    curso_nombre=state["area"],
                    created_at=now_str,
                    **fields,
                )
                db.add(nuevo)
                db.commit()
                db.refresh(nuevo)
                silabo_id = nuevo.id

            return {"silabo_id": silabo_id, "error_msg": None}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"PersistenceAgent error: {e}")
        return {"silabo_id": None, "error_msg": str(e)}

# ─────────────────────────────────────────────────────────────────────────────
# Grafo
# ─────────────────────────────────────────────────────────────────────────────
def route_errors(state: SilaboState) -> Literal["generation_agent", "persistence_agent"]:
    if state.get("error_msg"):
        return "persistence_agent"
    return "generation_agent"

def build_silabo_graph() -> StateGraph:
    workflow = StateGraph(SilaboState)
    workflow.add_node("db_validation", db_validation_node)
    workflow.add_node("generation_agent", generation_agent_node)
    workflow.add_node("persistence_agent", persistence_agent_node)

    workflow.set_entry_point("db_validation")
    workflow.add_conditional_edges("db_validation", route_errors, {
        "generation_agent": "generation_agent",
        "persistence_agent": "persistence_agent",
    })
    workflow.add_edge("generation_agent", "persistence_agent")
    workflow.add_edge("persistence_agent", END)
    return workflow.compile()

silabo_generator_app = build_silabo_graph()

async def generate_silabo(
    nivel: str, grado: int, area: str, anno_escolar: str = "2025", docente_id: int = None
) -> Dict[str, Any]:
    initial_state = {
        "nivel": nivel.upper(), "grado": grado, "area": area,
        "anno_escolar": anno_escolar, "docente_id": docente_id,
        "error_msg": None, "validacion_ok": False,
    }
    return await silabo_generator_app.ainvoke(initial_state)
