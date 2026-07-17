import os
import random
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Cargar variables de entorno (.env) ANTES de importar dependencias pesadas (para LangSmith)
load_dotenv(".env.test")

# Rotar LangSmith para usar ambas llaves de forma balanceada
ls_keys = [
    os.getenv("LANGCHAIN_API_KEY_1"),
    os.getenv("LANGCHAIN_API_KEY_2"),
    os.getenv("LANGCHAIN_API_KEY_3"),
    os.getenv("LANGCHAIN_API_KEY_4"),
    os.getenv("LANGCHAIN_API_KEY_5"),
    os.getenv("LANGCHAIN_API_KEY_6")
]
ls_keys = [k for k in ls_keys if k]
if ls_keys:
    os.environ["LANGCHAIN_API_KEY"] = random.choice(ls_keys)

# Rotar Groq para los agentes Deep Agents que no usan el parche de orchestrator.py
groq_keys = [
    os.getenv("GROQ_API_KEY_1"), os.getenv("GROQ_API_KEY_2"),
    os.getenv("GROQ_API_KEY_3"), os.getenv("GROQ_API_KEY_4"),
    os.getenv("GROQ_API_KEY_5"), os.getenv("GROQ_API_KEY_6"),
    os.getenv("GROQ_API_KEY_7"), os.getenv("GROQ_API_KEY_8")
]
groq_keys = [k for k in groq_keys if k]
if groq_keys:
    os.environ["GROQ_API_KEY"] = random.choice(groq_keys)

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta
import time
import uuid
from routers.api import router as api_router
from routers.deep_agents import router as deep_agents_router
from routers.secretaria import router as secretaria_router
from auth.security import create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES, get_password_hash, TokenData, get_current_user
from models.database import init_db, get_db, SessionLocal, UserDB, AnioEscolarDB
from core.tracing import logger, set_trace_id, log_audit_event
import asyncio

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://colegio-frontend-zeta.vercel.app")


# ---------------------------------------------------------------------------
# Lifespan handler — reemplaza el deprecado @app.on_event("startup")
# Ejecuta la inicialización de BD y usuarios de prueba al arrancar el servidor.
# ---------------------------------------------------------------------------
def _startup_sync():
    init_db()
    db = SessionLocal()
    if not db.query(UserDB).filter(UserDB.username == "admin").first():
        db.add(UserDB(username="admin", hashed_password=get_password_hash("admin123"), role="ADMIN", nombre_completo="Administrador Sistema"))
        db.add(UserDB(username="docente1", hashed_password=get_password_hash("doc123"), role="DOCENTE", nombre_completo="Docente Prueba"))
        db.add(UserDB(username="psico1", hashed_password=get_password_hash("psico123"), role="PSICOLOGO", nombre_completo="Psicologo Prueba"))
        db.add(UserDB(username="padre1", hashed_password=get_password_hash("padre123"), role="ALUMNO_PADRE", nombre_completo="Padre Prueba"))
        db.add(UserDB(username="secretario1", hashed_password=get_password_hash("sec123"), role="SECRETARIO", nombre_completo="Secretario Prueba"))
        db.commit()
        
    if not db.query(AnioEscolarDB).filter(AnioEscolarDB.estado == "ACTIVO").first():
        db.add(AnioEscolarDB(anio=2026, estado="ACTIVO"))
        db.commit()
    db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan handler de FastAPI moderno (sustituye @app.on_event)."""
    _startup_sync()
    yield


# ---------------------------------------------------------------------------
# Aplicación FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(
    title="ERP I.E.P. José María Arguedas",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "Authorization", "Content-Type"],
)


@app.middleware("http")
async def add_process_time_header_and_trace(request, call_next):
    trace_id = str(uuid.uuid4())
    set_trace_id(trace_id)

    start_time = time.time()

    logger.info(f"Incoming request: {request.method} {request.url.path}")
    response = await call_next(request)

    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    response.headers["X-Trace-ID"] = trace_id

    logger.info(f"Request completed: {request.method} {request.url.path} - Status: {response.status_code} - Time: {process_time:.4f}s")
    return response


app.include_router(api_router, prefix="/api")
app.include_router(deep_agents_router, prefix="/api")
app.include_router(secretaria_router, prefix="/api")


@app.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db=Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.username == form_data.username).first()
    from auth.security import verify_password
    if not user or not verify_password(form_data.password, user.hashed_password):
        log_audit_event("LOGIN_FAILED", form_data.username, "auth", "ERROR", "Invalid credentials")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")

    if not user.is_active:
        log_audit_event("LOGIN_FAILED_SUSPENDED", form_data.username, "auth", "ERROR", "Account suspended")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cuenta suspendida temporalmente por el Administrador.")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role, "user_id": user.id}, expires_delta=access_token_expires
    )

    log_audit_event("LOGIN_SUCCESS", user.username, "auth", "SUCCESS", f"Role: {user.role}")
    return {"access_token": access_token, "token_type": "bearer", "role": user.role}

@app.get("/api/auth/verify")
async def verify_token(current_user: TokenData = Depends(get_current_user)):
    return {"status": "ok", "user_id": current_user.user_id, "role": current_user.role}



if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
