from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from typing import Dict, Any

from schemas.agents import PsychologistAlert
from agents.deep_agents.graph_state import PsychologistState
from agents.orchestrator import GROQ_KEYS

# LLM General para resumir datos
llm = ChatGroq(tags=["psychologist_agent"], metadata={"agent_name": "psychologist_agent"}, 
    temperature=0.4,
    model_name="llama-3.1-8b-instant",
    api_key=GROQ_KEYS[0],
    max_retries=2
)

# LLM Estricto para el diagnóstico (Estructurado)
diagnostic_llm = ChatGroq(tags=["psychologist_agent"], metadata={"agent_name": "psychologist_agent"}, 
    temperature=0.0,
    model_name="llama-3.1-8b-instant",
    api_key=GROQ_KEYS[0],
    max_retries=2
).with_structured_output(PsychologistAlert)


def analyze_data_node(state: PsychologistState) -> Dict[str, Any]:
    """Nodo 1: Analiza la data en crudo y redacta un perfil conductual/académico."""
    
    prompt = (
        f"Analiza la situación del estudiante '{state['student_name']}' basado en los siguientes datos:\n"
        f"- Promedios: {state['grades']}\n"
        f"- Faltas Injustificadas: {state['absences']}\n"
        f"- Observaciones de docentes: {state['teacher_observations']}\n\n"
        f"Redacta un resumen clínico breve (máx 3 párrafos) destacando patrones de riesgo."
    )
    
    response = llm.invoke([
        SystemMessage(content="Eres un orientador psicopedagógico escolar muy perceptivo."),
        HumanMessage(content=prompt)
    ])
    
    return {"analysis_summary": response.content}


def risk_assessment_node(state: PsychologistState) -> Dict[str, Any]:
    """Nodo 2: Convierte el resumen en un diagnóstico estructurado (Bajo/Medio/Alto)."""
    
    summary = state["analysis_summary"]
    prompt = (
        f"Basado en el siguiente resumen de un estudiante, determina su nivel de riesgo de deserción o problemas severos.\n\n"
        f"RESUMEN:\n{summary}\n\n"
        f"Reglas estrictas:\n"
        f"- Asigna 'Alto' si hay alto ausentismo (>= 5 faltas), bajas notas simultáneas, o menciones a bullying/agresión/depresión.\n"
        f"- Asigna 'Medio' si el rendimiento está bajando o hay leves faltas de atención.\n"
        f"- Asigna 'Bajo' si el perfil es normal.\n"
    )
    
    alert: PsychologistAlert = diagnostic_llm.invoke([
        SystemMessage(content="Eres el Director de Psicología de la escuela. Debes ser preciso y estructurado."),
        HumanMessage(content=prompt)
    ])
    
    is_alert_triggered = alert.risk_level.upper() == "ALTO"
    
    return {
        "risk_level": alert.risk_level,
        "diagnostico": alert.diagnostico,
        "accion_recomendada": alert.accion_recomendada,
        "is_alert_triggered": is_alert_triggered
    }

def alert_routing_logic(state: PsychologistState) -> str:
    """Condición para enrutar en el Grafo (por ahora va al fin, pero podría enviar correos en el futuro)"""
    return END

# --- Construcción del Grafo LangGraph ---
workflow = StateGraph(PsychologistState)

workflow.add_node("analyze_data_node", analyze_data_node)
workflow.add_node("risk_assessment_node", risk_assessment_node)

workflow.set_entry_point("analyze_data_node")
workflow.add_edge("analyze_data_node", "risk_assessment_node")
workflow.add_conditional_edges(
    "risk_assessment_node",
    alert_routing_logic,
    {
        END: END
    }
)

# Compilar el grafo
psychologist_app = workflow.compile()
