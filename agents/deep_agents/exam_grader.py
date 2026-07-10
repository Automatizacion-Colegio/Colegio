import os
from pydantic import BaseModel, Field
from typing import Optional
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
import json

class ExamGradingResult(BaseModel):
    numero_orden: Optional[int] = Field(description="El número de orden del alumno encontrado en el texto. Puede ser un número como 05, 12, etc.")
    nota_sugerida: str = Field(description="La nota sugerida en base a la evaluación. Puede ser cualitativa (AD, A, B, C) o cuantitativa (0-20).")
    justificacion: str = Field(description="La justificación de la nota dirigida a la profesora.")
    feedback_estudiante: str = Field(description="Comentarios constructivos amigables dirigidos al alumno para que mejore.")

from core.antigravity import telemetry_store

def _update_telemetry_sync(tokens: int):
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_update_telemetry_async(tokens))
    except RuntimeError:
        asyncio.run(_update_telemetry_async(tokens))

async def _update_telemetry_async(tokens: int):
    try:
        state = await telemetry_store.get_state()
        state["calls"] = state.get("calls", 0) + 1
        state["success_calls"] = state.get("success_calls", 0) + 1
        state["total_tokens"] = state.get("total_tokens", 0) + tokens
        await telemetry_store.set_state(state)
    except Exception as e:
        print(f"Error updating telemetry in OCR: {e}")

async def grade_exam_with_ai(ocr_text: str, rubric: str) -> dict:
    """
    Evalúa el texto extraído del examen contra la rúbrica proporcionada por el docente.
    """
    llm = ChatGroq(tags=["exam_grader"], metadata={"agent_name": "exam_grader"}, 
        temperature=0.2,
        model_name="llama-3.1-8b-instant",
        groq_api_key=os.getenv("GROQ_API_KEY")
    )

    prompt = PromptTemplate(
        input_variables=["ocr_text", "rubric"],
        template="""Eres un experto asistente de profesores de escuela.
Acabamos de procesar una foto de un examen escolar escrito a mano usando OCR. El texto extraído puede tener errores ortográficos o saltos de línea raros debido a la naturaleza del reconocimiento óptico, así que debes ser tolerante y deducir la intención del estudiante.

Texto extraído del examen (OCR):
-----------------------
{ocr_text}
-----------------------

Rúbrica y respuestas correctas (indicadas por el profesor):
-----------------------
{rubric}
-----------------------

TU TAREA:
1. Intenta identificar el "Número de orden" del estudiante si está presente en el texto (ej: "N° orden: 5", "Orden 12"). Si no lo encuentras, devuelve null.
2. Compara el texto de las respuestas con la rúbrica/respuestas correctas.
3. Evalúa y calcula una nota sugerida. Si la rúbrica indica que es Primaria, usa el sistema cualitativo del MINEDU (AD, A, B, C). Si no se especifica o es Secundaria, usa el formato numérico (0 a 20).
4. Escribe una breve justificación técnica para el profesor.
5. Escribe un feedback constructivo y alentador para el estudiante.

Genera tu respuesta estrictamente en el siguiente formato JSON:
{{
  "numero_orden": 5, 
  "nota_sugerida": "16",
  "justificacion": "El alumno respondió bien la pregunta 1 y 2, pero falló en el cálculo de la pregunta 3.",
  "feedback_estudiante": "¡Buen trabajo, Carlos! Tienes muy claro el concepto de ecuaciones, pero revisa tus sumas en el último ejercicio."
}}

SOLO GENERA JSON VÁLIDO. NADA DE TEXTO ADICIONAL.
"""
    )

    chain = prompt | llm
    response = await chain.ainvoke({"ocr_text": ocr_text, "rubric": rubric})
    
    # Telemetry tracking for Admin dashboard
    try:
        usage = response.response_metadata.get("token_usage", {})
        total_tokens = usage.get("total_tokens", 0)
        await _update_telemetry_async(total_tokens)
    except Exception:
        pass
        
    
    content = response.content
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].strip()
        
    try:
        return json.loads(content)
    except Exception as e:
        print("Error parsing LLM response:", e)
        return {
            "numero_orden": None,
            "nota_sugerida": 0,
            "justificacion": f"Error al parsear la IA. Respuesta cruda: {response.content}",
            "feedback_estudiante": "No se pudo generar feedback."
        }
