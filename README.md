<div align="center">

# 🎓 ERP Escolar AI - Backend

**Plataforma educativa avanzada impulsada por Agentes de Inteligencia Artificial**

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109.2-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)
[![Cloud Run](https://img.shields.io/badge/Deploy-Google%20Cloud%20Run-4285F4?logo=googlecloud)](https://cloud.google.com/run)

</div>

---

## 📋 Tabla de Contenidos

- [Descripción](#-descripción)
- [Arquitectura](#-arquitectura)
- [Stack Tecnológico](#-stack-tecnológico)
- [Módulos del Sistema](#-módulos-del-sistema)
- [Seguridad](#-seguridad)
- [API Endpoints](#-api-endpoints)
- [Variables de Entorno](#-variables-de-entorno)
- [Instalación y Ejecución Local](#-instalación-y-ejecución-local)
- [CI/CD Pipeline](#-cicd-pipeline)
- [Base de Datos e IA](#-base-de-datos-e-ia)
- [Estructura del Proyecto](#-estructura-del-proyecto)

---

## 📖 Descripción

**ERP Escolar AI Backend** es el núcleo lógico de un sistema de gestión escolar (I.E.P. José María Arguedas). Construido en Python con **FastAPI**, orquesta no solo operaciones CRUD típicas (gestión de alumnos, notas, personal) sino también **Agentes Inteligentes Autónomos** basados en LangGraph y LLMs (Gemini, Groq). Esto permite flujos automatizados de tutoría, evaluación académica y soporte administrativo.

---

## 🏗️ Arquitectura

```text
┌─────────────────────────────────────────────────────────────┐
│                        CLIENTES                             │
│                 Frontend (React / Vercel)                   │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTPS
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              Google Cloud Run (Serverless)                  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              ERP Escolar AI (FastAPI)               │    │
│  │                                                     │    │
│  │  Middlewares (CORS / TraceID) → Routers             │    │
│  │       │                              │              │    │
│  │  Auth & JWT                 LangGraph Orchestrator  │    │
│  └──────────────────────────────────────┼──────────────┘    │
└────────┬──────────────┬─────────────────┼───────────────────┘
         │              │                 │ (Celery / Async)
         ▼              ▼                 ▼
    Neon (PgSQL)      Redis        Modelos de IA (LLMs)
   + pgvector      (Broker/Cache)  (Groq / Google Gemini)
```

---

## 🛠️ Stack Tecnológico

| Categoría | Tecnología | Versión |
|---|---|---|
| **Lenguaje** | Python | 3.11+ |
| **Framework Web** | FastAPI | 0.109.2 |
| **Servidor ASGI** | Uvicorn | 0.27.1 |
| **Base de Datos** | PostgreSQL (Neon) | — |
| **ORM** | SQLAlchemy | 2.0.25 |
| **Validación de Datos** | Pydantic | 2.6.1 |
| **Base de Datos Vectorial** | `pgvector` + `langchain-postgres` | — |
| **Agentes e IA** | LangChain / LangGraph | — |
| **LLMs Integrados** | Groq / Gemini (Google) / OpenAI | — |
| **Colas / Tareas** | Celery + Redis | 5.3.6 / 5.0.1 |
| **Seguridad / Auth** | Python-jose + Passlib + bcrypt | — |
| **Despliegue** | Google Cloud Run + Artifact Registry | — |
| **CI/CD** | GitHub Actions | — |

---

## 📦 Módulos del Sistema

### 🤖 Inteligencia Artificial y Agentes (`agents/`)
Utiliza **LangGraph** para crear un grafo de agentes que colaboran entre sí. Incluye orquestadores, validadores y evaluadores que responden de forma contextual según el rol del usuario que consulta (alumno, profesor, padre).

### 👥 Gestión de Usuarios y Roles (`auth/`)
Soporte para múltiples roles jerárquicos: `ADMIN`, `DOCENTE`, `PSICOLOGO`, `ALUMNO_PADRE`, `SECRETARIO`. Control de acceso estricto mediante tokens JWT.

### 🏛️ Secretaría (`routers/secretaria.py`)
Módulo administrativo para la gestión del año escolar, inscripciones, asignación de cursos y mantenimiento del personal.

### 🧠 Deep Agents (`routers/deep_agents.py`)
Endpoints especializados para tareas asíncronas pesadas (análisis de desempeño, generación de informes psicológicos) procesados vía Celery y LangGraph.

### 📊 Trazabilidad y Auditoría (`core/tracing.py`)
Cada request HTTP inyecta un `X-Trace-ID`. Registro (Audit Logs) de inicio de sesión exitosos, fallidos o intentos de uso de cuentas suspendidas para análisis de seguridad.

---

## 🔐 Seguridad

### Autenticación y Autorización
- **JWT (JSON Web Tokens)**: Endpoints protegidos, tokens con tiempo de expiración y claims de roles.
- Hasheo de contraseñas utilizando el algoritmo **bcrypt** a través de `passlib`.
- Roles estrictamente segregados mediante dependencias de FastAPI (RBAC).

### Seguridad de la IA (Jailbreak Prevention)
- **Escudos Lógicos**: Los *prompts* pasan por filtros de seguridad para evitar *Prompt Injection* y manipulación.
- **Data Isolation**: Un agente solo tiene acceso al contexto (notas, reportes) del estudiante asociado al token activo.

### Trazabilidad HTTP
- Middleware personalizado que adjunta tiempos de proceso (`X-Process-Time`) y UUIDs de seguimiento (`X-Trace-ID`) en los headers de cada respuesta.

---

## 🌐 API Endpoints


### Resumen de Enrutadores principales

| Router | Prefijo | Descripción |
|---|---|---|
| `Token` | `/token` | Autenticación y generación de JWT |
| `API General` | `/api` | Endpoints genéricos del sistema (`api.py`) |
| `Secretaría` | `/api/secretaria` | Acciones exclusivas del área administrativa |
| `Deep Agents` | `/api/deep_agents` | Consultas complejas a IA y tareas en background |

---

## ⚙️ Variables de Entorno

Crear un archivo `.env` en la raíz del backend con las siguientes configuraciones. En producción, estas se inyectan como GitHub Secrets hacia Cloud Run.

### Base de Datos y Caché
| Variable | Descripción |
|---|---|
| `DATABASE_URL` | String de conexión a Neon PostgreSQL |
| `REDIS_URL` | Conexión al servidor Redis Cloud |
| `CELERY_BROKER_URL` | Broker para tareas asíncronas (Redis) |
| `CELERY_RESULT_BACKEND` | Almacenamiento de resultados de Celery |

### Modelos y LangSmith
El sistema soporta rotación de API Keys para evitar cuotas limitadas (Load Balancing manual).
| Variable | Descripción |
|---|---|
| `GROQ_API_KEY_1` al `8` | Keys para inferencia ultrarrápida Llama/Mixtral |
| `LANGCHAIN_API_KEY_1` al `6`| Keys para LangSmith (Trazabilidad de IA) |
| `GOOGLE_API_KEY` | Modelos nativos de Gemini (Google AI Studio) |

### Seguridad y App
| Variable | Descripción |
|---|---|
| `JWT_SECRET` | Llave maestra para firma de tokens |
| `SMTP_PASSWORD` | Contraseña de aplicación para envíos de correo |
| `FRONTEND_URL` | URL permitida en las políticas de CORS |

---

## 🚀 Instalación y Ejecución Local

### Prerrequisitos
- Python 3.11+
- PostgreSQL (o una cuenta en Neon.tech)
- Redis Server (local o en nube)

### 1. Clonar y crear entorno virtual
```bash
git clone https://github.com/tu-usuario/erp_escolar_ai.git
cd erp_escolar_ai/backend
python -m venv venv

# Activar entorno virtual
# En Windows:
venv\Scripts\activate
# En Linux/Mac:
source venv/bin/activate
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3. Configurar `.env`
Copia las variables de la sección anterior en tu archivo local `.env`.

### 4. Levantar servidor de desarrollo
Las tablas y la extensión `pgvector` se autogeneran al iniciar gracias a `init_db()`.
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
> *Nota: Al arrancar por primera vez, el sistema creará usuarios base como `admin`, `docente1`, `psico1`, etc.*

---

## 🔄 CI/CD Pipeline

Se utiliza **GitHub Actions** (`.github/workflows/`) para realizar despliegues automáticos (CD) hacia **Google Cloud Run**.

1. **Trigger**: Push a la rama `main`.
2. **Build Docker**: Se construye el `Dockerfile` del backend.
3. **Push Artifact**: Se almacena en *Google Artifact Registry*.
4. **Deploy**: Cloud Run levanta la nueva imagen e inyecta los secretos de entorno mapeados desde GitHub.

---

## 🧠 Base de Datos e IA

### PostgreSQL Serverless (Neon) + pgvector
En lugar de una base de datos vectorial separada (como Chroma), este proyecto consolida sus datos transaccionales (ORM con SQLAlchemy) y sus **embeddings vectoriales** en la misma base PostgreSQL gracias a la extensión `pgvector`. 
Esto reduce latencia y permite búsquedas híbridas exactas en un solo lugar.

### Orquestación de Agentes
El directorio `agents/` contiene grafos de estado de **LangGraph** (`orchestrator.py`, `subagents.py`). Cada nodo del grafo es una función Python (un "Agente") que interactúa con las herramientas del sistema o con un LLM, permitiendo procesos de reflexión, búsqueda de contexto en BBDD y validación antes de devolver la respuesta al frontend.

---

## 📁 Estructura del Proyecto

```text
backend/
├── .github/workflows/    # Pipelines de CI/CD para Google Cloud Run
├── agents/               # Lógica de Inteligencia Artificial (LangGraph)
│   ├── orchestrator.py   # Grafo principal de agentes
│   └── subagents.py      # Agentes especialistas (Ej: corrector, psicólogo)
├── auth/                 # Módulo de Seguridad
│   └── security.py       # JWT, hashing, validación OAuth2
├── core/                 # Configuraciones Globales
│   └── tracing.py        # Logs y tiempos de ejecución
├── models/               # Capa de Datos (SQLAlchemy)
│   └── database.py       # Esquemas, conexión a Neon y pgvector
├── routers/              # Controladores (Endpoints REST)
│   ├── api.py            # Endpoints generales
│   ├── deep_agents.py    # IA asíncrona
│   └── secretaria.py     # Endpoints administrativos
├── Dockerfile            # Configuración para contenedor de producción
├── main.py               # Punto de entrada de FastAPI y Middlewares
├── requirements.txt      # Dependencias PIP
└── README.md
```

---

<div align="center">

Desarrollado con ❤️ para el ecosistema educativo

</div>
