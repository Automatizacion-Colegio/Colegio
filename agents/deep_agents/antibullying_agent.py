import os
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field

class AnalisisSentimiento(BaseModel):
    es_peligro: bool = Field(description="True si detecta indicios de bullying, depresión, violencia o aislamiento extremo. False en caso contrario.")
    justificacion: str = Field(description="Explicación clínica breve de por qué se considera o no un peligro.")
    nivel_urgencia: str = Field(description="ALTO, MEDIO, BAJO, o NULO.")

llm = ChatGroq(tags=["antibullying_agent"], metadata={"agent_name": "antibullying_agent"}, 
    model_name="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY_1", os.getenv("GROQ_API_KEY")),
    temperature=0
).with_structured_output(AnalisisSentimiento)

async def analizar_observacion(texto: str) -> AnalisisSentimiento:
    """Analiza una observación docente en busca de banderas rojas psicológicas."""
    prompt = PromptTemplate.from_template(
        "Eres un psicólogo clínico escolar experto en prevención de bullying y salud mental infantil.\n"
        "Analiza la siguiente nota escrita por un profesor sobre un alumno y determina si hay riesgo inminente.\n"
        "Si menciona golpes, llanto excesivo, burlas repetitivas, aislamiento social severo o auto-lesiones, debes marcar es_peligro=True.\n\n"
        "Nota del profesor:\n{texto}"
    )
    chain = prompt | llm
    resultado = chain.invoke({"texto": texto})
    return resultado
