from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from typing import Dict, Any

from schemas.agents import TeacherPlanRequest, EvaluacionCurricular
from agents.deep_agents.graph_state import TeacherPlanState
from agents.orchestrator import GROQ_KEYS

# Inicializamos el LLM usando la primera llave del pool (podría extenderse a usar el rotador)
llm = ChatGroq(tags=["teacher_planner"], metadata={"agent_name": "teacher_planner"}, 
    temperature=0.7,
    model_name="llama-3.1-8b-instant",
    api_key=GROQ_KEYS[0],
    max_retries=2
)

# Inicializamos un LLM estricto (temperatura 0) para el Crítico
critic_llm = ChatGroq(tags=["teacher_planner"], metadata={"agent_name": "teacher_planner"}, 
    temperature=0.0,
    model_name="llama-3.1-8b-instant",
    api_key=GROQ_KEYS[0],
    max_retries=2
).with_structured_output(EvaluacionCurricular)


def plan_node(state: TeacherPlanState) -> Dict[str, Any]:
    """Nodo 1: Genera el primer borrador de la sesión"""
    prompt = (
        f"Eres un experto planificador docente. Crea una sesión estructurada para el grado: "
        f"{state['grade']}, materia: {state['subject']}, tema: {state['topic']}. "
        f"Incluye:\n"
        f"1. Objetivos\n"
        f"2. Desarrollo (Inicio, Desarrollo, Cierre)\n"
        f"3. Rúbrica de evaluación.\n\n"
        f"IMPORTANTE: Al final del documento, debes incluir una sección llamada '=== PROMPT MAESTRO PARA IA (Copiar y Pegar) ==='. "
        f"En esa sección, escribe un prompt optimizado y listo para que el docente lo copie y lo pegue en herramientas "
        f"como Gamma App, ChatGPT, Tome o Canva. Ese prompt maestro debe contener todo el resumen de la clase estructurado "
        f"y solicitar la creación de diapositivas visuales impactantes basándose en el contenido de esta sesión."
    )
    
    # Si hay feedback previo, significa que es un reintento
    if state.get("feedback"):
        prompt += f"\n\nATENCIÓN: Tuviste un error previo. Corrige según este feedback: {state['feedback']}"
        
    response = llm.invoke([SystemMessage(content="Eres un planificador docente de alto nivel."), HumanMessage(content=prompt)])
    
    return {
        "draft": response.content,
        "retry_count": state.get("retry_count", 0) + 1
    }


def critic_node(state: TeacherPlanState) -> Dict[str, Any]:
    """Nodo 2: Evalúa el borrador contra el currículo (crítico)"""
    draft = state["draft"]
    
    prompt = (
        f"Evalúa la siguiente planificación docente para {state['grade']} - {state['subject']}.\n\n"
        f"PLAN:\n{draft}\n\n"
        f"Verifica estrictamente que contenga: Objetivos medibles, fases claras (Inicio, Desarrollo, Cierre) "
        f"y una rúbrica de evaluación detallada. Devuelve tu evaluación."
    )
    
    evaluacion: EvaluacionCurricular = critic_llm.invoke([
        SystemMessage(content="Eres un riguroso coordinador académico evaluando planificaciones."),
        HumanMessage(content=prompt)
    ])
    
    return {
        "is_valid": evaluacion.is_valid,
        "feedback": evaluacion.feedback
    }


def routing_logic(state: TeacherPlanState) -> str:
    """Condición para enrutar en el Grafo"""
    if state["is_valid"]:
        return END
    
    # Prevenir bucles infinitos
    if state["retry_count"] >= 3:
        return END
        
    return "plan_node"


# --- Construcción del Grafo LangGraph ---
workflow = StateGraph(TeacherPlanState)

# Añadir nodos
workflow.add_node("plan_node", plan_node)
workflow.add_node("critic_node", critic_node)

# Definir el flujo (Edges)
workflow.set_entry_point("plan_node")
workflow.add_edge("plan_node", "critic_node")

# Edge condicional basado en la función routing_logic
workflow.add_conditional_edges(
    "critic_node",
    routing_logic,
    {
        "plan_node": "plan_node",
        END: END
    }
)

# Compilar el grafo
teacher_planner_app = workflow.compile()
