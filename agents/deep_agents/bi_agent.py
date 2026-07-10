import os
import json
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from models.database import engine
from sqlalchemy import text

llm = ChatGroq(tags=["bi_agent"], metadata={"agent_name": "bi_agent"}, 
    model_name="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY_1", os.getenv("GROQ_API_KEY")),
    temperature=0
)

def get_database_schema():
    from sqlalchemy import inspect
    inspector = inspect(engine)
    schema_text = ""
    for table_name in inspector.get_table_names():
        columns = []
        for col in inspector.get_columns(table_name):
            columns.append(f"{col['name']} ({col['type']})")
        schema_text += f"Table: {table_name}\nColumns: {', '.join(columns)}\n\n"
    return schema_text

async def run_bi_query(question: str) -> str:
    """Ejecuta text-to-SQL de manera segura y retorna el análisis. Usa un agente autoreparador si hay errores SQL."""
    try:
        # Paso 1: Prompt base
        prompt_sql = PromptTemplate.from_template(
            "Eres un experto en PostgreSQL. Basado en el esquema:\n{schema}\n"
            "Genera SOLO la consulta SQL válida para responder a la pregunta. Nada de Markdown.\n"
            "IMPORTANTE: Si usas COUNT() u otra función de agregación junto con columnas normales, RECUERDA usar GROUP BY.\n"
            "CRÍTICO: Para filtrar texto (como estado='matriculado'), usa SIEMPRE 'ILIKE' en lugar de '=' para evitar problemas de mayúsculas/minúsculas.\n"
            "Pregunta: {question}"
        )
        query_generator = prompt_sql | llm
        
        max_retries = 3
        last_error = ""
        sql_query = ""
        rows = []
        
        for attempt in range(max_retries):
            if attempt == 0:
                sql_query = query_generator.invoke({"schema": get_database_schema(), "question": question}).content.strip()
            else:
                # Agente Refactorizador de SQL
                prompt_fix = PromptTemplate.from_template(
                    "Eres un experto en PostgreSQL. Tu consulta SQL anterior falló.\n"
                    "Esquema:\n{schema}\n\nConsulta fallida: {sql}\n\nError de BD: {error}\n\n"
                    "Genera SOLO la nueva consulta SQL corregida. Nada de explicaciones ni bloques Markdown."
                )
                sql_query = llm.invoke(prompt_fix.format(schema=get_database_schema(), sql=sql_query, error=last_error)).content.strip()
            
            sql_query = sql_query.replace("```sql", "").replace("```", "").strip()
            
            if "DROP" in sql_query.upper() or "DELETE" in sql_query.upper() or "UPDATE" in sql_query.upper() or "INSERT" in sql_query.upper():
                return "Error de Seguridad: Consulta prohibida."
                
            try:
                with engine.connect() as conn:
                    result = conn.execute(text(sql_query))
                    rows = [dict(row._mapping) for row in result]
                break  # Éxito, salir del loop
            except Exception as db_err:
                last_error = str(db_err)
                if attempt == max_retries - 1:
                    raise Exception(f"Fallo tras {max_retries} intentos. Último error: {last_error}")

        # Paso 3: Interpretar
        prompt_interpret = PromptTemplate.from_template(
            "Eres el Analista de Datos Oficial del Colegio.\n"
            "El usuario te hizo esta pregunta: '{question}'.\n"
            "La base de datos arrojó exactamente este resultado: {data}\n\n"
            "INSTRUCCIONES CRÍTICAS:\n"
            "1. Responde de manera DIRECTA, natural y profesional a la pregunta planteada.\n"
            "2. NO uses plantillas robóticas como 'Resumen Ejecutivo', 'Observaciones', 'Recomendaciones' o 'Conclusiones'.\n"
            "3. NO des consejos no solicitados ni digas que deben 'investigar' si los datos son pocos o muchos.\n"
            "4. Limítate a presentar los datos solicitados de forma clara, amigable y estructurada (usa viñetas si hay listas)."
        )
        interpreter = prompt_interpret | llm
        final_answer = interpreter.invoke({"question": question, "data": json.dumps(rows)}).content
        
        return final_answer
        
    except Exception as e:
        return f"Lo siento, no pude procesar la consulta de datos. {str(e)}"
