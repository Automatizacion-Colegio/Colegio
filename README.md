<div align="center">

# 🎓 ERP Escolar AI — Backend

**Plataforma educativa de próxima generación impulsada por Agentes IA autónomos, RAG y LLMs**

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangChain](https://img.shields.io/badge/LangChain-LangGraph-1C3C3C?logo=langchain&logoColor=white)](https://langchain.com/)
[![Groq](https://img.shields.io/badge/LLM-Groq%20%7C%20Gemini-F55036?logo=groq&logoColor=white)](https://groq.com/)
[![PostgreSQL](https://img.shields.io/badge/DB-PostgreSQL%20%2B%20pgvector-336791?logo=postgresql&logoColor=white)](https://neon.tech/)
[![Redis](https://img.shields.io/badge/Cache-Redis-DC382D?logo=redis&logoColor=white)](https://redis.io/)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

</div>

---

## 📋 Tabla de Contenidos

- [Descripción](#-descripción)
- [Arquitectura del Sistema](#-arquitectura-del-sistema)
- [Stack de IA y Automatización](#-stack-de-ia-y-automatización)
- [Stack Tecnológico](#-stack-tecnológico)
- [Módulos del Sistema](#-módulos-del-sistema)
- [Seguridad](#-seguridad)
- [API Endpoints](#-api-endpoints)
- [Variables de Entorno](#-variables-de-entorno)
- [Instalación y Ejecución Local](#-instalación-y-ejecución-local)
- [CI/CD Pipeline](#-cicd-pipeline)
- [Estructura del Proyecto](#-estructura-del-proyecto)

---

## 📖 Descripción

**ERP Escolar AI Backend** es el núcleo lógico de un sistema de gestión escolar inteligente para la I.E.P. José María Arguedas. Construido en **Python + FastAPI**, va más allá de las operaciones CRUD tradicionales al incorporar un ecosistema completo de **IA generativa y automatización**:

- 🤖 **Agentes autónomos** orquestados con **LangGraph** que razonan, buscan contexto y actúan.
- 🔍 **RAG (Retrieval-Augmented Generation)** con **PGVector** para consultas semánticas sobre historiales de alumnos.
- 🧠 **LLMs** de última generación (Groq/Llama, Google Gemini) para informes, análisis psicológico y sílabos.
- 🌐 **MCP (Multi-Channel Processing / Swarm)** para enrutar mensajes al agente correcto según el rol del usuario.
- 🟥 **Redis como caché semántica** para reutilizar respuestas frecuentes del chatbot y reducir hasta un 80% el consumo de tokens.
- ⚙️ **Celery + Redis** para procesamiento de tareas pesadas en background (batch, reportes nocturnos).
- 📊 **BI Agent** que traduce preguntas en lenguaje natural a consultas SQL sobre la base de datos escolar.

---

## 🏗️ Arquitectura del Sistema

```text
┌──────────────────────────────────────────────────────────────────┐
│                         CLIENTES                                 │
│           React + Vite (Vercel) — 5 Paneles por Rol              │
│     Admin / Docente / Psicólogo / Padre / Secretaría             │
└────────────────────────────┬─────────────────────────────────────┘
                             │ HTTPS / REST + SSE Streaming
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Google Cloud Run                              │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │               ERP Escolar AI (FastAPI)                     │  │
│  │                                                            │  │
│  │  ┌──────────────┐    ┌──────────────────────────────────┐  │  │
│  │  │  Middlewares │    │      MCP Router / Swarm          │  │  │
│  │  │  CORS/TraceID│───▶│  ag_soporte / ag_psicologo /    │  │  │
│  │  └──────────────┘    │  ag_evaluacion / ag_docente      │  │  │
│  │                      └─────────────┬────────────────────┘  │  │
│  │                      ┌─────────────▼────────────────────┐  │  │
│  │                      │   Redis Semantic Cache Layer     │  │  │
│  │                      │  HIT → 0 tokens, respuesta       │  │  │
│  │                      │  instantánea (TTL: 24h)          │  │  │
│  │                      └─────────────┬────────────────────┘  │  │
│  │                                    │ CACHE MISS             │  │
│  │  ┌─────────────────────────────────▼────────────────────┐  │  │
│  │  │              Deep Agents (LangGraph)                 │  │  │
│  │  │  Psicólogo │ BI Agent │ Sílabo │ Examen │ Justific.  │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────┬────────────────┬────────────────┬─────────────────────────┬────────┐
       │                │                │                         │
       ▼                ▼                ▼                         ▼
  Neon (PgSQL)        Redis          LLMs API                  Cloudinary
  + pgvector     Cache + Celery     Groq / Gemini              Imágenes y
  (RAG Store)    Broker/Backend     LangSmith Traces           Vouchers OCR
```

---

## 🤖 Stack de IA y Automatización

### 🟥 Redis — Caché Semántica para Ahorro de Tokens

Redis actúa como una **capa de caché semántica** delante del LLM. Es uno de los mecanismos más importantes del sistema en términos de **coste operativo**.

```text
Usuario: "¿Cuál es el costo de matrícula de Primaria?"
       │
       ▼
  Orchestrator normaliza → "cual es el costo de matricula de primaria"
       │
       ▼
  Redis GET  →  faq_cache:<mensaje_normalizado>
       │
       ├─▶ CACHE HIT  ✅ → Respuesta en <50ms, consume 0 tokens LLM
       │                    TTL: 24 horas (86400s)
       │
       └─▶ CACHE MISS ❌ → Llama al LLM (Groq/Swarm)
                            └─▶ Redis SETEX faq_cache:<key> 86400 <respuesta>
                                 (se guarda para las próximas 24h)
```

**Reglas de caché inteligentes:**
- ✅ Solo cachea el **primer mensaje** de la sesión (sin historial previo).
- ✅ Solo cachea si respondió `Agente_Soporte` (preguntas FAQ del colegio).
- ❌ No cachea si la respuesta incluyó `tool_calls` (datos dinámicos como notas o precios en tiempo real).
- 🔤 Las claves se **normalizan** (minúsculas, sin puntuación) para maximizar los CACHE HIT.

**Impacto en costos:** En un colegio con decenas de padres preguntando lo mismo (horarios, costos, fechas), esto puede reducir el consumo de tokens del LLM en un **60-80%** en horas pico.

**Archivo clave:** `agents/orchestrator.py` — líneas ~276-342

---

### ⚙️ Celery + Redis — Cola de Tareas Asíncronas

Redis también funciona como **broker de mensajes** para Celery:

| Tarea Celery | Función |
|---|---|
| `procesar_admision_batch` | Procesa lotes de PDFs de admisión fuera del request |
| `generar_reportes_nocturnos` | Reportes académicos programados (Celery Beat) |

```text
POST /api/admin/tareas/batch
  └─▶ Celery encola en Redis
        └─▶ Worker procesa en background
              └─▶ GET /api/admin/tareas/{id}/estado → consulta resultado
```

**Archivo clave:** `core/tasks.py`

---

### 🔗 LangChain & LangGraph — Orquestación de Agentes

**LangGraph** crea **grafos de estado** donde cada nodo es un agente especialista:

```text
LangGraph Psychologist Flow:
  START
    └─▶ [nodo_analisis]      → Lee historial RAG del alumno desde PGVector
          └─▶ [nodo_riesgo]  → Evalúa nivel: BAJO / MEDIO / ALTO
                └─▶ [nodo_recomendacion] → Genera plan de acción
  END
```

**LangChain** se usa para: chains de prompt→LLM→parser, retrievers PGVector y memoria conversacional por sesión.

**Archivos clave:**
- `agents/orchestrator.py` — Grafo principal LangGraph
- `agents/subagents.py` — Agentes Swarm + tools (MCP)
- `agents/deep_agents/psychologist_agent.py` — Grafo psicólogo

---

### 🧠 LLMs Integrados (Groq + Google Gemini)

| Proveedor | Modelo | Uso Principal |
|---|---|---|
| **Groq** | `llama-3.1-8b-instant` | Chat rápido, resúmenes, OCR parsing |
| **Groq** | `llama-3.3-70b-versatile` | Análisis psicológico, BI queries complejas |
| **Google Gemini** | `gemini-2.0-flash` | Generación de sílabos CNEB, exámenes |

**Rotación de keys:** Variables `GROQ_API_KEY_1` al `_8` distribuyen la carga y evitan límites de cuota.

---

### 🔍 RAG — Retrieval-Augmented Generation con PGVector

```text
1. INGESTA (al atender cita psicológica o registrar observación docente):
   Texto del informe
     └─▶ Embedding (Google text-embedding-004)
           └─▶ PGVector (colección: "historiales_psicologia")
                 Metadata: { alumno_id, fecha, psicologo_id / docente_id }

2. CONSULTA (agente psicólogo recibe pregunta):
   "¿Qué comportamiento tuvo Luis García este mes?"
     └─▶ Embedding de la pregunta
           └─▶ Búsqueda semántica PGVector
                 WHERE metadata.alumno_id = <id>   ← Filtro específico por alumno
                 └─▶ Top-3 fragmentos relevantes inyectados al LLM
                       └─▶ Respuesta precisa y contextualizada
```

**Archivo clave:** `core/vector_store.py`

---

### 🌐 MCP — Multi-Channel Processing (Swarm Router)

```text
Usuario: "Mi hijo faltó ayer por enfermedad"
       │
       ▼
  [Swarm Router] detecta intención + rol del JWT
       │
       ├─▶ ag_soporte      → FAQs, costos, información general
       ├─▶ ag_psicologo    → Conducta, bienestar, reportes psicológicos
       ├─▶ ag_evaluacion   → Notas, rendimiento, comparativas
       └─▶ ag_docente      → Horarios, alumnos del aula, observaciones
```

**Archivo clave:** `agents/subagents.py`

---

### 📊 BI Agent — Business Intelligence con NL2SQL

```text
"¿Cuántos alumnos de Secundaria tienen más de 3 faltas este mes?"
    └─▶ [BI Agent LLM] genera SQL dinámico
          └─▶ Ejecuta sobre Postgres (Neon)
                └─▶ "12 alumnos de Secundaria tienen más de 3 faltas en julio."
```

**Endpoint:** `POST /api/deep-agents/bi-query`

---

### 📄 Deep Agents — Tareas IA Especializadas

| Agente | Endpoint | Función |
|---|---|---|
| **Psicólogo IA** | `POST /psicologia/chat` | Análisis conductual con RAG + LangGraph |
| **Generador de Sílabos** | `POST /deep-agents/silabo/generar` | Sílabos 14 secciones alineados al CNEB |
| **Generador de Exámenes** | `POST /deep-agents/generate-exam` | Exámenes con taxonomía de Bloom por grado |
| **Justificador de Faltas** | `POST /deep-agents/justify-absence` | OCR de certificado médico + registro en BD |
| **BI Query** | `POST /deep-agents/bi-query` | NL2SQL sobre la BD del colegio |
| **Orientación Vocacional** | `POST /deep-agents/vocational-guidance` | Perfil del alumno + recomendación de carrera |
| **Plan Docente** | `POST /deep-agents/teacher-plan` | Plan de clase semanal por área curricular |

---

### 🔭 LangSmith — Trazabilidad de IA en Producción

Cada invocación LLM o cadena LangChain se registra en **LangSmith** para:
- Ver el prompt exacto enviado al modelo.
- Medir latencia por nodo del grafo LangGraph.
- Detectar alucinaciones o respuestas fuera de contexto.
- Monitorear consumo de tokens por sesión.

---

## 🛠️ Stack Tecnológico

| Categoría | Tecnología | Rol |
|---|---|---|
| **Lenguaje** | Python 3.11+ | — |
| **Framework Web** | FastAPI 0.109+ | API REST + SSE Streaming |
| **Servidor ASGI** | Uvicorn | Servidor de producción |
| **Base de Datos SQL** | PostgreSQL (Neon) | Datos transaccionales |
| **Migraciones de BD** | Alembic | Control de versiones del esquema SQL |
| **ORM** | SQLAlchemy 2.0 | Mapeo objeto-relacional |
| **Base de Datos Vectorial** | pgvector + langchain-postgres | Embeddings RAG |
| **Orquestación IA** | LangGraph + LangChain | Grafos de agentes y cadenas |
| **LLMs** | Groq (Llama 3.1/3.3) + Google Gemini | Inferencia generativa |
| **Agentes / Swarm** | OpenAI Swarm (MCP) | Enrutamiento multi-agente |
| **Embeddings** | Google text-embedding-004 | Vectorización de documentos |
| **Trazabilidad IA** | LangSmith | Monitoreo de agentes en producción |
| **Caché Semántica** | Redis (redis.asyncio) | Ahorro de tokens en FAQs frecuentes |
| **Cola de Tareas** | Celery + Redis | Tareas asíncronas en background |
| **Almacenamiento de Imágenes** | Cloudinary | CDN y hosting para fotos, vouchers y firmas |
| **OCR** | Pytesseract + Pillow | Lectura de documentos médicos y vouchers |
| **Seguridad / Auth** | Python-jose + Passlib + bcrypt | JWT + RBAC |
| **Testing** | Pytest + Flake8 | Pruebas unitarias e integración en CI |
| **Despliegue** | Google Cloud Run | Serverless con auto-scaling |
| **CI/CD** | GitHub Actions | Test + Deploy automático en push a `main` |

---

## 📦 Módulos del Sistema

### 🤖 Agentes IA (`agents/`)
Grafos **LangGraph** y agentes **Swarm**. Cada agente tiene sus propias `tools` (funciones Python invocables) y acceso controlado al RAG vectorial.

### 👥 Autenticación (`auth/`)
Roles: `ADMIN`, `DOCENTE`, `PSICOLOGO`, `ALUMNO_PADRE`, `SECRETARIO`. JWT con expiración y RBAC mediante dependencias FastAPI.

### 🏛️ Secretaría (`routers/secretaria.py`)
Caja Diaria, OCR de vouchers, Panel de Admisiones y correos de cobranza redactados por IA.

### 🧠 Deep Agents (`routers/deep_agents.py`)
Sílabos CNEB, exámenes, justificación de faltas con OCR, orientación vocacional y análisis BI.

### 🗄️ Núcleo (`core/`)
- `vector_store.py` — PGVector RAG con filtros de metadata por alumno.
- `antigravity.py` — SharedMemory, EventBus SSE, AgentGraph y telemetría.
- `tracing.py` — Logs JSON estructurados y X-Trace-ID por request.
- `ocr_engine.py` — Motor OCR con validación previa de imágenes.
- `tasks.py` — Tareas Celery para procesamiento batch.

---

## 🔐 Seguridad

- **JWT + RBAC**: Cada endpoint valida el rol del token.
- **bcrypt**: Contraseñas hasheadas con sal aleatoria.
- **Prompt Injection Prevention**: Filtros en prompts antes de enviar al LLM.
- **Data Isolation**: El agente psicólogo solo accede al historial del alumno de la cita activa.
- **X-Trace-ID**: UUID único por request para auditoría completa.
- **OCR Validation**: Imágenes validadas con `PIL.Image.open()` antes del procesamiento.

### 🛡️ Auditoría de Arquitectura y Seguridad (Julio 2026)
Como parte del proceso de mejora continua, se realizó una auditoría completa de arquitectura resolviendo vulnerabilidades y deudas técnicas en 5 bloques clave:
1. **Saneamiento del Split-Brain (Persistencia SQL vs LLM RAM):** Las herramientas del LLM (`registrar_nota`, `agendar_cita_psicologica`, `evaluar_psicologico`, `registrar_pago`) ahora escriben transaccionalmente directo a Postgres en lugar de modificar memoria efímera, asegurando 100% de integridad relacional en admisiones y matrículas.
2. **Vectorización Sincronizada:** La indexación de historiales psicológicos en `PGVector` fue acoplada al `db.commit()` de la cita para garantizar que la memoria a largo plazo de la IA no se desincronice de la BD transaccional.
3. **Especialización de Docentes:** Se implementó restricción estricta de especialidad y nivel (PRIMARIA/SECUNDARIA) en la creación de docentes, integrando esta validación dinámicamente en el algoritmo del `timetabler.py`.
4. **Seguridad y Control de Roles Cruzados (IDOR Fix):** Se parcheó una vulnerabilidad IDOR en `/vocational-advisor` garantizando que un padre (`ALUMNO_PADRE`) solo pueda procesar análisis basados en las notas de sus propios hijos. Se verificó que todos los endpoints de *Deep Agents* tengan `Depends(require_role(...))` estricto.
5. **Limpieza UI e Integridad de BD:** Se eliminó la exposición cruda de la memoria del LLM (Raw JSON) del dashboard administrativo y se purgó la base de datos de registros huérfanos producto de pruebas sin persistencia.
6. **Migraciones y CI/CD (Agosto 2026):** Se implementó `Alembic` para el control de versiones seguro de las tablas, protegiendo explícitamente los *vector stores* de LangChain. Se unificó el pipeline de GitHub Actions introduciendo una capa de testing estricto (`pytest` + `flake8` sobre un contenedor `pgvector` temporal) que frena el pase a producción si se detecta cualquier falla técnica.

---

## 🌐 API Endpoints

| Router | Prefijo | Descripción |
|---|---|---|
| `Token` | `/token` | Login y generación de JWT |
| `API General` | `/api` | Alumnos, notas, asistencia, citas, cursos, MINEDU |
| `Secretaría` | `/api/secretaria` | Caja, admisiones, OCR de vouchers |
| `Padres/Apoderados` | `/api/padre` | Encuesta de ratificación de vacantes, matrículas y apoderados |
| `Deep Agents` | `/api/deep-agents` | IA pesada: sílabos, exámenes, BI, psicólogo |


---

## ⚙️ Variables de Entorno

Copia `.env.example` a `.env` y completa los valores.

### Base de Datos y Caché
| Variable | Descripción | Requerida |
|---|---|---|
| `DATABASE_URL` | String de conexión PostgreSQL (Neon) | ✅ |
| `REDIS_URL` | Conexión Redis (caché semántica + broker) | ✅ |
| `CELERY_BROKER_URL` | Broker Celery (Redis) | ✅ |
| `CELERY_RESULT_BACKEND` | Backend de resultados Celery | ✅ |

### LLMs y IA
| Variable | Descripción | Requerida |
|---|---|---|
| `GROQ_API_KEY` | Key principal Groq (Llama) | ✅ |
| `GROQ_API_KEY_1` al `_8` | Keys secundarias (rotación de cuota) | Opcional |
| `GOOGLE_API_KEY` | Google AI Studio (Gemini + Embeddings) | ✅ |
| `LANGCHAIN_API_KEY` | LangSmith trazabilidad de agentes | Opcional |
| `LANGCHAIN_TRACING_V2` | Activar/desactivar trazas LangSmith | Opcional |

### Seguridad y App
| Variable | Descripción | Requerida |
|---|---|---|
| `JWT_SECRET` | Llave maestra de firma de tokens | ✅ |
| `FRONTEND_URL` | URL del frontend (para CORS) | ✅ |
| `CLOUDINARY_URL` | Credenciales de Cloudinary (API Key/Secret) | ✅ |
| `SMTP_PASSWORD` | Contraseña SMTP para correos | Opcional |

---

## 🚀 Instalación y Ejecución Local

### Prerrequisitos
- Python 3.11+
- PostgreSQL local con extensión `pgvector`
- Redis Server local
- Tesseract OCR instalado

### 1. Clonar y crear entorno virtual
```bash
git clone https://github.com/Automatizacion-Colegio/Colegio.git
cd Colegio
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3. Configurar base de datos local
```bash
psql -U postgres -c "CREATE DATABASE erp_db;"
psql -U postgres -d erp_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 4. Configurar `.env`
```bash
cp .env.example .env
# Edita .env con tus credenciales
```

### 5. Ejecutar migraciones (Alembic)
```bash
alembic upgrade head
```

### 6. Levantar el servidor
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

> Al iniciar por primera vez, Alembic se encarga de estructurar las tablas (`ConfiguracionGlobalDB`, `PadreFamiliarDB`, etc.).

### 7. Documentación interactiva
```
http://localhost:8000/docs
```

---

## 🔄 CI/CD Pipeline

```text
Push a main
  └─▶ GitHub Actions (deploy.yml)
        ├─▶ 🧪 Validar y Testear Código
        │     ├─▶ Linting (flake8)
        │     └─▶ Pytest (Levanta un contenedor local de pgvector)
        │           [Si falla, se aborta el despliegue a GCP]
        └─▶ 🚀 Desplegar a Cloud Run
              └─▶ Build Docker Image
                    └─▶ Push a Google Artifact Registry
                          └─▶ Cloud Run Deploy
```

---

## 📁 Estructura del Proyecto

```text
backend/
├── .github/
│   └── workflows/
│       └── deploy.yml             # CI/CD: Flake8 + Pytest → Google Cloud Run
│
├── alembic/                       # 🗄️ Migraciones de BD (Revisiones SQL)
│
├── agents/                        # 🤖 IA: LangGraph + Swarm MCP
│   ├── orchestrator.py            # Grafo principal + Redis Semantic Cache
│   ├── subagents.py               # Swarm agents + tools (MCP Router)
│   └── deep_agents/
│       └── psychologist_agent.py  # LangGraph flow del psicólogo
│
├── auth/
│   └── security.py                # JWT, bcrypt, RBAC
│
├── core/
│   ├── antigravity.py             # SharedMemory, EventBus SSE, AgentGraph
│   ├── vector_store.py            # PGVector RAG (upsert + semantic_search)
│   ├── ocr_engine.py              # Motor OCR Tesseract + validación PIL
│   ├── tasks.py                   # Celery tasks (procesamiento batch)
│   └── tracing.py                 # Logs JSON, Audit Events, X-Trace-ID
│
├── models/
│   └── database.py                # SQLAlchemy models + init_db()
│
├── routers/
│   ├── api.py                     # +50 endpoints: alumnos, notas, MINEDU...
│   ├── deep_agents.py             # IA pesada: sílabos, exámenes, BI, OCR
│   └── secretaria.py              # Caja, vouchers, admisiones
│
├── schemas/
│   └── mcp.py                     # Pydantic schemas
│
├── tests/                         # 🧪 Pruebas automatizadas (Pytest de API y BD)
├── Dockerfile
├── main.py                        # Entry point FastAPI + Lifespan + Middlewares
├── requirements.txt
├── .env.example                   # Plantilla de variables de entorno
└── README.md
```

---

<div align="center">

Desarrollado con ❤️ para el ecosistema educativo peruano

**I.E.P. José María Arguedas** · ERP Escolar AI v1.0

</div>
