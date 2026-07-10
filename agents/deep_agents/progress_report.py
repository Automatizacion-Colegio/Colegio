from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from typing import Dict, Any
import json

from schemas.agents import EvaluacionTono
from agents.deep_agents.graph_state import ProgressReportState
from agents.orchestrator import GROQ_KEYS

llm = ChatGroq(tags=["progress_report"], metadata={"agent_name": "progress_report"}, 
    temperature=0.7,
    model_name="llama-3.1-8b-instant",
    api_key=GROQ_KEYS[0],
    max_retries=2
)

critic_llm = ChatGroq(tags=["progress_report"], metadata={"agent_name": "progress_report"}, 
    temperature=0.0,
    model_name="llama-3.1-8b-instant",
    api_key=GROQ_KEYS[0],
    max_retries=2
).with_structured_output(EvaluacionTono)


def generate_report_node(state: ProgressReportState) -> Dict[str, Any]:
    """Nodo 1: Genera el borrador del informe al padre"""
    notas_str = json.dumps(state['grades_summary'], ensure_ascii=False)
    
    prompt = (
        f"Redacta un informe de progreso para los padres del estudiante {state['student_name']}.\n"
        f"Calificaciones actuales: {notas_str}\n"
        f"Notas del tutor (conducta): {state['behavior_notes']}\n"
        f"El informe debe ser empático pero claro respecto al rendimiento académico y conductual."
    )
    
    if state.get("feedback"):
        prompt += f"\n\nATENCIÓN: Tu borrador anterior no tuvo el tono correcto. Corrige esto: {state['feedback']}"
        
    response = llm.invoke([
        SystemMessage(content="Eres un tutor escolar redactando informes a padres."), 
        HumanMessage(content=prompt)
    ])
    
    return {
        "draft": response.content,
        "retry_count": state.get("retry_count", 0) + 1
    }


def critic_report_node(state: ProgressReportState) -> Dict[str, Any]:
    """Nodo 2: Evalúa el tono (crítico)"""
    draft = state["draft"]
    
    prompt = (
        f"Evalúa el siguiente informe para padres sobre un alumno:\n\n"
        f"INFORME:\n{draft}\n\n"
        f"Verifica estrictamente que: 1. El tono sea constructivo y no acusatorio. "
        f"2. Se incluyan soluciones prácticas (pasos a seguir) si hay calificaciones bajas o mala conducta. "
        f"Devuelve tu evaluación."
    )
    
    evaluacion: EvaluacionTono = critic_llm.invoke([
        SystemMessage(content="Eres el psicólogo del colegio auditando el tono de los comunicados."),
        HumanMessage(content=prompt)
    ])
    
    return {
        "is_valid": evaluacion.is_constructive,
        "feedback": evaluacion.feedback
    }


def report_routing_logic(state: ProgressReportState) -> str:
    """Condición para enrutar"""
    if state["is_valid"]:
        return END
    
    if state["retry_count"] >= 3:
        return END
        
    return "generate_report_node"


# --- Construcción del Grafo ---
workflow = StateGraph(ProgressReportState)

workflow.add_node("generate_report_node", generate_report_node)
workflow.add_node("critic_report_node", critic_report_node)

workflow.set_entry_point("generate_report_node")
workflow.add_edge("generate_report_node", "critic_report_node")

workflow.add_conditional_edges(
    "critic_report_node",
    report_routing_logic,
    {
        "generate_report_node": "generate_report_node",
        END: END
    }
)

progress_report_app = workflow.compile()
