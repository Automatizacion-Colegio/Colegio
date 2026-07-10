from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from typing import Dict, Any

from schemas.agents import TutorMatchRequest, TutorMatchResponse
from agents.orchestrator import GROQ_KEYS
import json

# Usaremos un modelo más avanzado si es necesario, pero Llama 3 70B es excelente para Chain-of-Thought
matcher_llm = ChatGroq(tags=["tutor_matcher"], metadata={"agent_name": "tutor_matcher"}, 
    temperature=0.1, # Muy baja temperatura para decisiones deterministas
    model_name="llama-3.1-8b-instant",
    api_key=GROQ_KEYS[0],
    max_retries=2
).with_structured_output(TutorMatchResponse)


async def run_tutor_matcher(request: TutorMatchRequest) -> TutorMatchResponse:
    """
    Ejecuta el asignador inteligente usando el patrón Chain-of-Thought (en el prompt).
    """
    classrooms_str = json.dumps([c.model_dump() for c in request.classrooms], ensure_ascii=False)
    teachers_str = json.dumps([t.model_dump() for t in request.teachers], ensure_ascii=False)
    
    prompt = (
        f"Eres el Director Académico. Tu tarea es asignar el mejor tutor posible a cada aula.\n\n"
        f"AULAS:\n{classrooms_str}\n\n"
        f"DOCENTES DISPONIBLES:\n{teachers_str}\n\n"
        f"Instrucciones de Razonamiento (Chain of Thought):\n"
        f"1. Analiza el 'difficulty_level' y 'needs' de cada aula.\n"
        f"2. Busca qué 'teaching_style' o 'strengths' del docente empatan mejor (Ej: Aula difícil -> Docente Estricto o con experiencia en manejo conductual).\n"
        f"3. Un docente NO puede estar asignado a dos aulas simultáneamente. Debes asignar a todos los que puedas.\n"
        f"4. Proporciona una explicación ('rationale') muy clara de por qué decidiste emparejarlos.\n\n"
        f"Devuelve la respuesta estrictamente en el formato JSON solicitado."
    )
    
    # ainvoke para no bloquear FastAPI
    response: TutorMatchResponse = await matcher_llm.ainvoke([
        SystemMessage(content="Eres un sistema de asignación escolar inteligente y altamente lógico."),
        HumanMessage(content=prompt)
    ])
    
    return response
