import os
from pydantic import BaseModel, Field
from typing import Optional
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate

class MedicalAuditResult(BaseModel):
    es_valido: bool = Field(description="Si el documento parece ser un comprobante médico, receta o boleta de hospital válido.")
    dias_reposo: int = Field(description="Número de días sugeridos de reposo. Si no dice, asume 1.")
    resumen_diagnostico: str = Field(description="Breve resumen del motivo médico o la especialidad.")

llm = ChatGroq(tags=["medical_auditor"], metadata={"agent_name": "medical_auditor"}, 
    model_name="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY_1", os.getenv("GROQ_API_KEY")),
    temperature=0
).with_structured_output(MedicalAuditResult)

async def audit_medical_document(ocr_text: str) -> MedicalAuditResult:
    """Extrae información médica de un texto OCR para justificar faltas."""
    prompt = PromptTemplate.from_template(
        "Eres un auditor médico escolar. Acabamos de escanear (OCR) una foto enviada por un padre. "
        "Puede ser una receta, un certificado de descanso médico, o incluso una boleta de consulta de un hospital/posta/clínica.\n"
        "Debes ser flexible: mientras sea un documento médico que evidencie atención o enfermedad, trátalo como válido.\n\n"
        "Texto OCR del documento:\n{texto}\n\n"
        "TU TAREA: Determinar si es válido, extraer los días de reposo (o deducir 1 si solo fue una consulta), y hacer un mini resumen."
    )
    chain = prompt | llm
    return chain.invoke({"texto": ocr_text})
