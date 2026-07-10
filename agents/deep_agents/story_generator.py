import os
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

llm = ChatGroq(tags=["story_generator"], metadata={"agent_name": "story_generator"}, 
    model_name="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY_1", os.getenv("GROQ_API_KEY")),
    temperature=0.7
)

async def generate_personalized_story(alumnos: list[str], valor: str, curso: str) -> str:
    """Genera un cuento didáctico usando los nombres de los alumnos."""
    nombres_alumnos = ", ".join(alumnos) if alumnos else "los alumnos de la clase"
    
    prompt = PromptTemplate.from_template(
        "Eres un premiado autor de cuentos infantiles educativos.\n"
        "Escribe un cuento corto (máximo 4 párrafos) para niños de primaria.\n"
        "El cuento debe enseñar sobre el valor de: {valor}.\n"
        "Los protagonistas del cuento DEBEN ser algunos de estos alumnos de la clase de {curso}: {alumnos}.\n"
        "Haz que la historia sea mágica, emocionante y que termine con una moraleja clara.\n\n"
        "Cuento:"
    )
    chain = prompt | llm
    result = chain.invoke({"valor": valor, "curso": curso, "alumnos": nombres_alumnos})
    return result.content
