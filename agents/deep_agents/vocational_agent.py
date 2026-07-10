import os
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

llm = ChatGroq(tags=["vocational_agent"], metadata={"agent_name": "vocational_agent"}, 
    model_name="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY_1", os.getenv("GROQ_API_KEY")),
    temperature=0.6
)

async def get_vocational_advice(perfil_academico: str, intereses_alumno: str) -> str:
    """Brinda orientación vocacional basada en notas reales y gustos del alumno."""
    prompt = PromptTemplate.from_template(
        "Eres un psicólogo vocacional sumamente empático, alentador y profesional.\n"
        "Un estudiante de secundaria te ha dicho qué quiere estudiar o qué le gusta.\n"
        "Tú tienes acceso a su perfil académico (sus promedios históricos en distintos cursos).\n\n"
        "Perfil Académico del Alumno:\n{perfil}\n\n"
        "Intereses declarados por el alumno:\n{intereses}\n\n"
        "TU TAREA:\n"
        "1. JAMÁS le digas 'tu carrera no es la correcta', 'estás equivocado' o palabras desmotivadoras.\n"
        "2. Si hay una discrepancia (ej. quiere ingeniería pero tiene bajas notas en ciencias/matemáticas y altas en letras), háblale con MUCHA DELICADEZA. Destaca lo maravilloso de sus fortalezas reales (las letras) y sugiérele suavemente explorar áreas relacionadas que aprovechen esos talentos innatos (ej. periodismo, derecho, diseño) sin cerrarle la puerta a su sueño inicial.\n"
        "3. Si hay afinidad total, aliéntalo a seguir por ese camino.\n"
        "4. Usa un tono cercano, como un mentor inspirador.\n\n"
        "Tu respuesta de orientación:"
    )
    chain = prompt | llm
    result = chain.invoke({"perfil": perfil_academico, "intereses": intereses_alumno})
    return result.content
