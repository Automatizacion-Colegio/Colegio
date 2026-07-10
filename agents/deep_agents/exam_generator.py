import os
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

llm = ChatGroq(tags=["exam_generator"], metadata={"agent_name": "exam_generator"}, 
    model_name="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY_1", os.getenv("GROQ_API_KEY")),
    temperature=0.3
)

async def generate_exam(tema: str, dificultad: str, num_preguntas: int = 5) -> str:
    """Genera un examen basado en el tema proporcionado usando LLM."""
    prompt = PromptTemplate.from_template(
        "Eres un profesor experto en pedagogía. Necesitas crear un examen sobre el siguiente tema:\n"
        "TEMA: {tema}\n"
        "DIFICULTAD: {dificultad}\n"
        "NÚMERO DE PREGUNTAS: {num_preguntas}\n\n"
        "Reglas:\n"
        "1. Crea preguntas de opción múltiple (A, B, C, D).\n"
        "2. Añade 1 o 2 preguntas de desarrollo corto al final.\n"
        "3. Al final del examen, en una sección separada, incluye la HOJA DE RESPUESTAS y la rúbrica de calificación.\n"
        "Formatea todo en Markdown profesional, ideal para imprimir."
    )
    chain = prompt | llm
    result = chain.invoke({"tema": tema, "dificultad": dificultad, "num_preguntas": num_preguntas})
    return result.content
