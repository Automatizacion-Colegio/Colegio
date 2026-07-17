"""
ColegioOrchestrator — Orquestador central del ERP Escolar utilizando OpenAI Swarm.
"""
import os
import uuid
import asyncio
from core.antigravity import SharedMemory, EventBus, AgentGraph, SSEChannel
from schemas.mcp import ExpedienteAdmision, PagoMatricula, RegistroNota
from agents.subagents import ag_soporte, ag_admin, ag_evaluacion, ag_psicologo
from fastapi import HTTPException
from swarm import Swarm
from openai import OpenAI
from langsmith.wrappers import wrap_openai
import contextvars

current_swarm_agent = contextvars.ContextVar("current_swarm_agent", default="unknown")

# Inicializamos el cliente base para Swarm
openai_client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.getenv("GROQ_API_KEY_1", os.getenv("GROQ_API_KEY", "gsk_fallback"))
)

# ====== GESTIÓN DE ROTACIÓN DE TOKENS GROQ ======
GROQ_KEYS = [
    os.getenv("GROQ_API_KEY_1"),
    os.getenv("GROQ_API_KEY_2"),
    os.getenv("GROQ_API_KEY_3"),
    os.getenv("GROQ_API_KEY_4"),
    os.getenv("GROQ_API_KEY_5"),
    os.getenv("GROQ_API_KEY_6"),
    os.getenv("GROQ_API_KEY_7"),
    os.getenv("GROQ_API_KEY_8"),
]
# Filtrar llaves vacías o nulas
GROQ_KEYS = [k for k in GROQ_KEYS if k and len(k) > 10]
if not GROQ_KEYS:
    GROQ_KEYS = [os.getenv("GROQ_API_KEY", "")]

current_key_idx = 0

# ====== GESTIÓN DE ROTACIÓN DE TOKENS GOOGLE ======
GOOGLE_KEYS = [
    os.getenv("GOOGLE_API_KEY_1"),
    os.getenv("GOOGLE_API_KEY_2"),
    os.getenv("GOOGLE_API_KEY_3"),
    os.getenv("GOOGLE_API_KEY_4"),
    os.getenv("GOOGLE_API_KEY_5"),
]
GOOGLE_KEYS = [k for k in GOOGLE_KEYS if k and len(k) > 10]
if not GOOGLE_KEYS:
    GOOGLE_KEYS = [os.getenv("GOOGLE_API_KEY", os.getenv("GOOGLE_AI_STUDIO_API_KEY", ""))]

current_google_key_idx = 0

def patched_create(*args, **kwargs):
    global current_key_idx
    global current_google_key_idx
    
    if "messages" in kwargs:
        for msg in kwargs["messages"]:
            if isinstance(msg, dict):
                allowed_keys = {"role", "content", "name", "tool_calls", "tool_call_id"}
                keys_to_remove = [k for k in msg.keys() if k not in allowed_keys]
                for k in keys_to_remove:
                    msg.pop(k, None)

    model_name = kwargs.get("model", "")
    is_gemma = model_name.startswith("gemma")
    
    agent_name = current_swarm_agent.get()
    
    if is_gemma:
        attempts = 0
        while attempts < len(GOOGLE_KEYS):
            try:
                raw_client = OpenAI(
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                    api_key=GOOGLE_KEYS[current_google_key_idx]
                )
                temp_client = wrap_openai(raw_client)
                
                response = temp_client.chat.completions.create(*args, **kwargs)
                
                if hasattr(response, "choices") and response.choices:
                    for choice in response.choices:
                        if hasattr(choice.message, "tool_calls") and choice.message.tool_calls:
                            for tc in choice.message.tool_calls:
                                if hasattr(tc, "function") and tc.function:
                                    if not tc.function.arguments or tc.function.arguments.strip() == "null":
                                        tc.function.arguments = "{}"
                                        
                if hasattr(response, "usage") and response.usage:
                    try:
                        from core.antigravity import telemetry_store
                        telemetry_store.log(latency=200.0, success=True, tokens=response.usage.total_tokens, trace_id="swarm_agent")
                    except Exception:
                        pass
                                        
                return response
            
            except Exception as e:
                err_str = str(e).lower()
                if "rate limit" in err_str or "429" in err_str or "quota" in err_str:
                    print(f"⚠️ Google API Key {current_google_key_idx + 1} agotada. Cambiando a la siguiente...")
                    attempts += 1
                    current_google_key_idx = (current_google_key_idx + 1) % len(GOOGLE_KEYS)
                else:
                    print(f"⚠️ [FALLBACK GEMINI->GROQ] Error llamando a Gemma ({e}). Cayendo a openai/gpt-oss-120b...")
                    kwargs["model"] = "openai/gpt-oss-120b"
                    is_gemma = False
                    break
        
        if is_gemma and attempts >= len(GOOGLE_KEYS):
            print("⚠️ [FALLBACK GEMINI->GROQ] Todas las llaves de Google agotadas. Cayendo a openai/gpt-oss-120b...")
            kwargs["model"] = "openai/gpt-oss-120b"
            is_gemma = False

    if not is_gemma:
        attempts = 0
        while attempts < len(GROQ_KEYS):
            if "AQUI_TU_KEY" in GROQ_KEYS[current_key_idx]:
                attempts += 1
                current_key_idx = (current_key_idx + 1) % len(GROQ_KEYS)
                continue
                
            try:
                raw_client = OpenAI(
                    base_url="https://api.groq.com/openai/v1",
                    api_key=GROQ_KEYS[current_key_idx]
                )
                temp_client = wrap_openai(raw_client)
                
                meta_dict = {"agent_name": agent_name, "provider": "groq"}
                tags_list = [agent_name]
                if kwargs.get("model") == "openai/gpt-oss-120b":
                    meta_dict["fallback"] = True
                    tags_list.append("fallback")

                response = temp_client.chat.completions.create(*args, **kwargs)
                
                if hasattr(response, "choices") and response.choices:
                    for choice in response.choices:
                        if hasattr(choice.message, "tool_calls") and choice.message.tool_calls:
                            for tc in choice.message.tool_calls:
                                if hasattr(tc, "function") and tc.function:
                                    if not tc.function.arguments or tc.function.arguments.strip() == "null":
                                        tc.function.arguments = "{}"
                
                if hasattr(response, "usage") and response.usage:
                    try:
                        from core.antigravity import telemetry_store
                        telemetry_store.log(latency=200.0, success=True, tokens=response.usage.total_tokens, trace_id="swarm_agent")
                    except Exception:
                        pass
                                        
                return response
            
            except Exception as e:
                err_str = str(e).lower()
                if "tool_use_failed" in err_str and "failed_generation" in err_str:
                    try:
                        import ast
                        import uuid
                        error_dict = ast.literal_eval(str(e).split(" - ", 1)[1])
                        failed_gen = error_dict.get("error", {}).get("failed_generation", "")
                        if failed_gen.startswith("<function="):
                            import re
                            match = re.search(r'<function=(\w+)\s+(.*?)</function>', failed_gen)
                            if match:
                                func_name = match.group(1)
                                func_args = match.group(2)
                                class MockFunction:
                                    def __init__(self, name, arguments):
                                        self.name = name
                                        self.arguments = arguments
                                class MockToolCall:
                                    def __init__(self, id, function):
                                        self.id = id
                                        self.type = "function"
                                        self.function = function
                                class MockMessage:
                                    def __init__(self, content, role, tool_calls):
                                        self.content = content
                                        self.role = role
                                        self.tool_calls = tool_calls
                                        self.function_call = None
                                        self.refusal = None
                                class MockChoice:
                                    def __init__(self, message):
                                        self.message = message
                                class MockResponse:
                                    def __init__(self, choices):
                                        self.choices = choices
                                mock_func = MockFunction(func_name, func_args)
                                mock_tc = MockToolCall("call_" + str(uuid.uuid4())[:8], mock_func)
                                mock_msg = MockMessage(None, "assistant", [mock_tc])
                                return MockResponse([MockChoice(mock_msg)])
                    except Exception:
                        pass
                
                if "rate limit" in err_str or "429" in err_str or "authentication" in err_str or "401" in err_str or "insufficient_quota" in err_str:
                    print(f"⚠️ Groq API Key {current_key_idx + 1} agotada o fallida. Cambiando a la siguiente...")
                    attempts += 1
                    current_key_idx = (current_key_idx + 1) % len(GROQ_KEYS)
                else:
                    raise e
                    
        print("🚨 Se agotaron los tokens en todas las API Keys. Desactivando asistente temporalmente.")
        class MockMessage:
            content = "Por el momento no está habilitado el asistente."
            role = "assistant"
            tool_calls = None
            function_call = None
            refusal = None
        class MockChoice:
            message = MockMessage()
        class MockResponse:
            choices = [MockChoice()]
        return MockResponse()

openai_client.chat.completions.create = patched_create

swarm_client = Swarm(client=openai_client)

original_get_chat_completion = swarm_client.get_chat_completion
def patched_get_chat_completion(agent, history, context_variables, model_override, stream, debug):
    token = current_swarm_agent.set(agent.name)
    try:
        return original_get_chat_completion(agent, history, context_variables, model_override, stream, debug)
    finally:
        current_swarm_agent.reset(token)

swarm_client.get_chat_completion = patched_get_chat_completion


class ColegioOrchestrator:
    def __init__(self, memory: SharedMemory, bus: EventBus, graph: AgentGraph):
        self.memory = memory
        self.bus = bus
        self.graph = graph

    def generar_codigo(self, tipo: str, count: int, extra: str = "") -> str:
        from models.database import SessionLocal, AlumnoDB
        db = SessionLocal()
        try:
            if tipo == "OBS":
                # Asumimos que OBS (observados) no estǭ en SQL pero usamos el count de JSON
                return f"OBS-2026-{count + 1:03d}"
            else:
                # Contamos cuántos alumnos ya hay en la BD para este nivel
                db_count = db.query(AlumnoDB).filter(AlumnoDB.nivel == extra).count()
                # Usamos el mayor entre la BD y el JSON en memoria para evitar repetir si se reinicia el servidor
                total = max(count, db_count)
                return f"EST-2026-{extra[:3].upper()}-{total + 1:03d}"
        except Exception as e:
            print(f"Error generando código: {e}")
            return f"{tipo}-2026-{extra[:3].upper()}-{count + 1:03d}"
        finally:
            db.close()

    async def stream_chat(self, message: str, channel: SSEChannel, history: list[dict] = None, starting_agent=None, user_context: dict = None) -> None:
        """
        Orquesta la respuesta de chat con streaming SSE usando OpenAI Swarm.
        """
        trace_id = str(uuid.uuid4())[:8]
        if history is None:
            history = []
        if starting_agent is None:
            starting_agent = ag_soporte
        if user_context is None:
            user_context = {}
            
        current_history = history + [{"role": "user", "content": message}]

        # --- FASE 2: CAPA DE CACHÉ CON REDIS ---
        cache = None
        try:
            import redis.asyncio as aioredis
            import re
            REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            cache = aioredis.from_url(REDIS_URL, decode_responses=True)
            await cache.ping()
        except ImportError:
            print("⚠️ Warning: redis.asyncio no está instalado. Instalalo con 'pip install redis'.")
            cache = None
        except Exception as e:
            print(f"⚠️ Warning: Redis no disponible. Caché deshabilitado. Error: {e}")
            cache = None

        normalized_msg = ""
        cache_key = ""
        # Consultamos caché solo si es el primer mensaje de la interacción
        if cache and len(history) == 0:
            normalized_msg = re.sub(r'[^\w\s]', '', message).lower().strip()
            cache_key = f"faq_cache:{normalized_msg}"
            try:
                cached_response = await cache.get(cache_key)
                if cached_response:
                    print(f"🟢 [CACHE HIT] Clave: {cache_key}")
                    words = cached_response.split(" ")
                    for i, word in enumerate(words):
                        token = word + (" " if i < len(words) - 1 else "")
                        await channel.send_token(token)
                        await asyncio.sleep(0.04)
                    await channel.send_done(trace_id)
                    return
                else:
                    print(f"🟡 [CACHE MISS] Clave: {cache_key}")
            except Exception as e:
                print(f"⚠️ Error accediendo a Redis: {e}")

        try:
            await channel.send_thinking("Swarm_Orchestrator", "coordinando_agentes")
            
            # Combinar memoria global con contexto del usuario
            context_vars = {"memory": self.memory}
            context_vars.update(user_context)

            def run_swarm():
                return swarm_client.run(
                    agent=starting_agent,
                    messages=current_history,
                    context_variables=context_vars,
                    debug=False
                )
            
            response = await asyncio.to_thread(run_swarm)
            
            # Simular streaming de la respuesta final de Swarm
            import json
            final_message = response.messages[-1]["content"] if response.messages else "No pude generar una respuesta."
            
            # --- FASE 2: GUARDADO INTELIGENTE POST-RESPUESTA ---
            if cache and len(history) == 0 and response.agent.name == "Agente_Soporte":
                last_msg = response.messages[-1]
                if not last_msg.get("tool_calls"):
                    try:
                        await cache.setex(cache_key, 86400, final_message)
                        print(f"💾 [CACHE SAVE] Clave: {cache_key} | TTL: 24h")
                    except Exception as e:
                        print(f"⚠️ Error guardando en Redis: {e}")

            # Interceptar alucinaciones JSON crudas (comunes en modelos locales cuando no saben cómo omitir tools)
            try:
                if final_message and final_message.strip().startswith("{") and final_message.strip().endswith("}"):
                    data = json.loads(final_message)
                    if "name" in data and "parameters" in data:
                        params = data["parameters"]
                        final_message = list(params.values())[0] if params else "¡Hola! ¿En qué puedo ayudarte?"
            except Exception:
                pass

            words = final_message.split(" ")
            for i, word in enumerate(words):
                token = word + (" " if i < len(words) - 1 else "")
                await channel.send_token(token)
                await asyncio.sleep(0.04)

            await channel.send_done(trace_id)
        except Exception as e:
            await channel.send_error(f"Error interno del orquestador Swarm: {str(e)}")



    async def procesar_admision(self, expediente: ExpedienteAdmision):
        estado = await self.memory.get_state()
        codigo_est = self.generar_codigo("EST", len(estado["enrolled_students"]), expediente.nivel)

        from models.database import SessionLocal, AdmisionDB
        db = SessionLocal()
        
        try:
            # Lógica de admisión automática
            if (expediente.conducta == "B" and expediente.promedio < 14) or expediente.conducta == "C":
                estado_proceso = "Requiere Cita Psicológica"
                mensaje = "Derivado a psicología por riesgo detectado. Por favor, selecciona una cita."
                status_ret = "requiere_cita"
            else:
                estado_proceso = "Admitido (Falta Pago)"
                monto = 500.0 if "primaria" in expediente.nivel.lower() else 700.0
                mensaje = f"Admitido por perfil óptimo. Tu cuota de matrícula es de S/ {monto}. Por favor, realiza el pago."
                status_ret = "admitido"

            # 1. Guardar en PostgreSQL para persistencia e interfaz de Secretaria
            nueva_admision = AdmisionDB(
                codigo_est=codigo_est,
                dni=expediente.dni,
                nombres=expediente.nombres,
                apellidos=expediente.apellidos,
                nivel=expediente.nivel,
                grado=expediente.grado,
                promedio=expediente.promedio,
                conducta=expediente.conducta,
                ap_nombre=expediente.ap_nombre,
                ap_correo=expediente.ap_correo,
                ap_telefono=expediente.ap_telefono,
                estado_proceso=estado_proceso
            )
            db.add(nueva_admision)
            db.commit()

            # 2. Mantener en JSON memory para compatibilidad con código antiguo
            estado["enrolled_students"][codigo_est] = {
                "dni": expediente.dni,
                "nombres": f"{expediente.nombres} {expediente.apellidos}",
                "nivel": expediente.nivel,
                "grado": expediente.grado,
                "apoderado": expediente.ap_nombre,
                "ap_correo": expediente.ap_correo,
                "estado_proceso": estado_proceso
            }
            await self.memory.set_state(estado)

            if status_ret == "requiere_cita":
                citas_disponibles = [c for c in estado["calendario_psicologia"] if not c["ocupado"]]
                if not citas_disponibles:
                    raise HTTPException(status_code=400, detail="No hay citas psicológicas disponibles.")
                return {"status": status_ret, "citas": citas_disponibles, "mensaje": mensaje, "codigo_est": codigo_est}
            else:
                return {"status": status_ret, "codigo_est": codigo_est, "mensaje": mensaje}
        finally:
            db.close()

    async def agendar_cita_psicologica(self, data):
        estado = await self.memory.get_state()
        codigo_obs = self.generar_codigo("OBS", len(estado.get("observed_students", {})), "")

        from models.database import SessionLocal, CitaDB
        db = SessionLocal()
        try:
            # Check if cita is taken in Postgres (permitiendo agendar si está Cancelado o Rechazado)
            ocupado = db.query(CitaDB).filter(
                CitaDB.dia == data.dia, 
                CitaDB.hora == data.hora,
                CitaDB.estado.notin_(["Cancelado", "Rechazado"])
            ).first()
            if ocupado:
                raise HTTPException(status_code=400, detail="El horario seleccionado ya no está disponible.")

            nueva_cita = CitaDB(
                codigo_obs=codigo_obs,
                motivo="Admisión",
                dia=data.dia,
                hora=data.hora,
                estado="Pendiente"
            )
            db.add(nueva_cita)
            db.commit()

            # Compatibilidad con JSON memory local
            for c in estado.get("calendario_psicologia", []):
                if c["dia"] == data.dia and c["hora"] == data.hora:
                    c["ocupado"] = True
                    c["codigo_obs"] = codigo_obs
                    break

            if "observed_students" not in estado:
                estado["observed_students"] = {}
            estado["observed_students"][codigo_obs] = {
                "dni": data.expediente.dni,
                "nombres": f"{data.expediente.nombres} {data.expediente.apellidos}",
                "nivel": data.expediente.nivel,
                "grado": data.expediente.grado,
                "apoderado": data.expediente.ap_nombre,
                "ap_correo": data.expediente.ap_correo,
                "estado_proceso": "En Observación",
                "datos_originales": data.expediente.model_dump()
            }
            await self.memory.set_state(estado)
            return {"status": "agendado", "codigo_obs": codigo_obs, "mensaje": "Cita confirmada en BD y código generado."}
        finally:
            db.close()

    async def evaluar_psicologico(self, codigo_obs: str, decision: str, observacion: str):
        estado = await self.memory.get_state()
        if codigo_obs not in estado.get("observed_students", {}):
            raise HTTPException(status_code=404, detail="Código OBS no encontrado")

        alumno = estado["observed_students"][codigo_obs]

        from models.database import SessionLocal, AdmisionDB, CitaDB
        db = SessionLocal()
        try:
            # 1. Actualizar CitaDB
            cita = db.query(CitaDB).filter(CitaDB.codigo_obs == codigo_obs).first()
            if cita:
                cita.estado = "Atendido"
                db.commit()

            # 2. Actualizar AdmisionDB y recuperar codigo_est original
            admision = db.query(AdmisionDB).filter(AdmisionDB.dni == alumno.get("dni")).first()
            if not admision:
                codigo_est = self.generar_codigo("EST", len(estado.get("enrolled_students", {})), alumno["nivel"])
            else:
                codigo_est = admision.codigo_est

            if decision == "Aprobado":
                if admision:
                    admision.estado_proceso = "Admitido (Falta Pago)"
                    db.commit()
                    
                if "enrolled_students" not in estado:
                    estado["enrolled_students"] = {}
                    
                estado["enrolled_students"][codigo_est] = {
                    "dni": alumno.get("dni", ""),
                    "nombres": alumno["nombres"],
                    "nivel": alumno["nivel"],
                    "grado": alumno["grado"],
                    "apoderado": alumno.get("apoderado", ""),
                    "ap_correo": alumno.get("ap_correo", ""),
                    "estado_proceso": "Admitido (Falta Pago)"
                }
                del estado["observed_students"][codigo_obs]
                await self.memory.set_state(estado)
                
                # ENVIAR CORREO AL APODERADO CON EL CÓDIGO DE ESTUDIANTE
                ap_correo = alumno.get("ap_correo")
                if ap_correo:
                    try:
                        import smtplib
                        from email.mime.text import MIMEText
                        from email.mime.multipart import MIMEMultipart
                        import os
                        
                        app_password = os.getenv("SMTP_PASSWORD")
                        sender_email = "iep.josemariaarguedas.1998@gmail.com"
                        
                        msg = MIMEMultipart()
                        msg['From'] = sender_email
                        msg['To'] = ap_correo
                        msg['Subject'] = "RESULTADO DE EVALUACIÓN PSICOLÓGICA - I.E.P. José María Arguedas"
                        
                        monto = 500.0 if "primaria" in alumno["nivel"].lower() else 700.0
                        cuerpo = f"Estimado apoderado de {alumno['nombres']},\n\nNos complace informarle que la evaluación psicológica ha sido favorable y el estudiante ha sido ADMITIDO.\n\nPara completar la matrícula, debe realizar el pago de la cuota de S/ {monto}.\nSu Código de Estudiante para realizar el pago en el chat es: {codigo_est}\n\nPor favor, regrese al chat de admisión, escriba 'Quiero pagar mi matrícula' y proporcione su código {codigo_est}.\n\nAtentamente,\nDepartamento de Psicología."
                        msg.attach(MIMEText(cuerpo, 'plain', 'utf-8'))
                        
                        if app_password:
                            server = smtplib.SMTP('smtp.gmail.com', 587)
                            server.starttls()
                            server.login(sender_email, app_password)
                            server.send_message(msg)
                            server.quit()
                    except Exception as e:
                        print("Error enviando correo de aprobacion psicologica:", e)

                return {"status": "aprobado", "codigo_est": codigo_est, "mensaje": f"Aprobado. Obs: {observacion}"}
            else:
                if admision:
                    admision.estado_proceso = "Rechazado"
                    db.commit()
                    
                if "rejected_students" not in estado:
                    estado["rejected_students"] = {}
                    
                estado["rejected_students"][codigo_obs] = {
                    "nombres": alumno["nombres"],
                    "dni": alumno.get("dni", ""),
                    "motivo": observacion or "Rechazado en Entrevista Psicológica",
                    "estado_proceso": "Rechazado"
                }
                del estado["observed_students"][codigo_obs]
                await self.memory.set_state(estado)
                return {"status": "rechazado", "mensaje": f"Rechazado. Motivo: {observacion}"}
        finally:
            db.close()

    async def registrar_pago(self, pago: PagoMatricula):
        estado = await self.memory.get_state()
        if pago.codigo_est not in estado["enrolled_students"]:
            raise HTTPException(status_code=404, detail="Estudiante no encontrado.")

        alumno = estado["enrolled_students"][pago.codigo_est]
        if alumno["estado_proceso"] != "Admitido (Falta Pago)":
            raise HTTPException(status_code=400, detail=f"El estudiante no está habilitado para matrícula. Estado actual: {alumno['estado_proceso']}")

        # Reemplazado Swarm por un condicional directo para que no demore el pago
        monto_requerido = 500.0 if "primaria" in alumno["nivel"].lower() else 700.0

        if pago.monto_pagado < monto_requerido:
            raise HTTPException(status_code=400, detail=f"Monto insuficiente. Requiere S/ {monto_requerido}")

        alumno["estado_proceso"] = "Matriculado"
        estado["enrolled_students"][pago.codigo_est] = alumno
        await self.memory.set_state(estado)
        
        # Persistir el cambio de estado en AdmisionDB
        from models.database import SessionLocal, AdmisionDB
        db = SessionLocal()
        try:
            adm = db.query(AdmisionDB).filter(AdmisionDB.codigo_est == pago.codigo_est).first()
            if adm:
                adm.estado_proceso = "Matriculado"
                db.commit()
        finally:
            db.close()
            
        return {"status": "success", "mensaje": "Matrícula completada exitosamente."}

    async def registrar_nota(self, registro: RegistroNota):
        estado = await self.memory.get_state()

        if registro.codigo_est not in estado["enrolled_students"]:
            raise HTTPException(status_code=404, detail="Estudiante no existe.")

        alumno = estado["enrolled_students"][registro.codigo_est]
        if alumno["estado_proceso"] != "Matriculado":
            raise HTTPException(status_code=400, detail="Conflicto de Estado: Estudiante no tiene matrícula activa.")

        # Evaluador Académico usando Swarm
        def eval_academic():
            return swarm_client.run(
                agent=ag_evaluacion,
                messages=[{"role": "user", "content": f"El alumno ha sacado {registro.nota} en el curso {registro.curso}. Evalúa si se requiere tutoría y emite una recomendación."}]
            )
        eval_res = await asyncio.to_thread(eval_academic)
        respuesta_eval = eval_res.messages[-1]["content"]
        
        alerta = "tutor" in respuesta_eval.lower() or "alerta" in respuesta_eval.lower()

        if alerta:
            await self.bus.publish(
                "ALERTA_PEDAGOGICA",
                f"{alumno['nombres']} - Riesgo en {registro.curso} (Nota: {registro.nota}). Recomendación IA: {respuesta_eval}"
            )

        from models.database import SessionLocal, NotaDB, AlumnoDB, CursoDB
        db = SessionLocal()
        try:
            # 1. Guardar en PostgreSQL para persistencia
            al = db.query(AlumnoDB).filter(AlumnoDB.codigo_est == registro.codigo_est).first()
            if not al:
                raise HTTPException(status_code=404, detail="Estudiante no existe en BD.")
                
            c = db.query(CursoDB).filter(CursoDB.nombre == registro.curso, CursoDB.nivel == al.nivel).first()
            if not c:
                c = db.query(CursoDB).filter(CursoDB.nombre == registro.curso).first()
                if not c:
                    raise HTTPException(status_code=404, detail=f"Curso '{registro.curso}' no encontrado.")
                    
            nueva_nota = NotaDB(
                alumno_id=al.id,
                curso_id=c.id,
                docente_id=registro.docente_id or 1,
                criterio="Asignado por IA",
                semana="1",
                valor_numerico=registro.nota,
                observacion=respuesta_eval
            )
            db.add(nueva_nota)
            db.commit()

            # 2. Mantener en JSON memory para compatibilidad con código antiguo
            if registro.codigo_est not in estado["notas_trimestrales"]:
                estado["notas_trimestrales"][registro.codigo_est] = {}
            if registro.curso not in estado["notas_trimestrales"][registro.codigo_est]:
                estado["notas_trimestrales"][registro.codigo_est][registro.curso] = []

            estado["notas_trimestrales"][registro.codigo_est][registro.curso].append(registro.nota)
            await self.memory.set_state(estado)
        finally:
            db.close()

        return {"status": "success", "alerta": alerta, "recomendacion": respuesta_eval}
