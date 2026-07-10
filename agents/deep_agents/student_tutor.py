import os
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

llm = ChatGroq(tags=["student_tutor"], metadata={"agent_name": "student_tutor"}, 
    model_name="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY_1", os.getenv("GROQ_API_KEY")),
    temperature=0.5
)

async def ask_tutor(pregunta: str, perfil_alumno: str) -> str:
    """Chatbot Tutor Personalizado para el Alumno."""
    prompt = PromptTemplate.from_template(
        "Eres un 'Tutor Virtual Inteligente' para el colegio José María Arguedas.\n"
        "Estás hablando con un alumno. Su perfil (notas, debilidades) es el siguiente:\n"
        "{perfil}\n\n"
        "REGLAS:\n"
        "1. Sé muy empático, paciente y usa un lenguaje fácil de entender.\n"
        "2. No le des la respuesta directa a problemas matemáticos, guíalo paso a paso (Método Socrático).\n"
        "3. Anímalo si ves que sus notas en el perfil están bajas.\n\n"
        "Pregunta del alumno: {pregunta}"
    )
    chain = prompt | llm
    result = chain.invoke({"perfil": perfil_alumno, "pregunta": pregunta})
    return result.content
