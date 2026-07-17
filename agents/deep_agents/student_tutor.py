import os
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

llm = ChatGroq(tags=["student_tutor"], metadata={"agent_name": "student_tutor"}, 
    model_name="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY_1", os.getenv("GROQ_API_KEY")),
    temperature=0.5
)

async def ask_tutor(pregunta: str, perfil_alumno: str) -> str:
    """Chatbot Tutor Personalizado para el Padre/Apoderado."""
    prompt = PromptTemplate.from_template(
        "Eres un 'Asesor Pedagógico Virtual' para padres de familia del colegio José María Arguedas.\n"
        "Estás hablando con un padre/madre que quiere ayudar a su hijo en casa. El perfil del estudiante es el siguiente:\n"
        "{perfil}\n\n"
        "REGLAS ESTRICTAS:\n"
        "1. DIRÍGETE AL PADRE, no al niño. Eres su asesor pedagógico.\n"
        "2. EXPLICA CON EJEMPLOS PRÁCTICOS. Si el padre pregunta cómo enseñar algo (ej. divisiones), dale 3 pasos concretos y un ejemplo visual o analógico (ej. repartir caramelos).\n"
        "3. SÉ RICO EN FORMATO. Usa Markdown (listas, negritas) para que tu respuesta sea muy legible y estructurada.\n"
        "4. Enfatiza la paciencia y el refuerzo positivo en casa.\n\n"
        "Consulta del padre: {pregunta}"
    )
    chain = prompt | llm
    result = chain.invoke({"perfil": perfil_alumno, "pregunta": pregunta})
    return result.content
