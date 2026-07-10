from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

import os
from dotenv import load_dotenv

load_dotenv()

# Exigir obligatoriamente la variable DATABASE_URL del .env (Neon)
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")
if not SQLALCHEMY_DATABASE_URL:
    raise ValueError("ERROR: DATABASE_URL no está configurada. El sistema requiere PostgreSQL (Neon).")

# Remover 'check_same_thread' porque es específico de SQLite
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String) # ADMIN, DOCENTE, PSICOLOGO, ALUMNO_PADRE, SECRETARIO
    nivel_asignado = Column(String, nullable=True) # PRIMARIA o SECUNDARIA (solo para DOCENTES)
    is_active = Column(Boolean, default=True)

class CursoDB(Base):
    __tablename__ = "cursos"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String)
    nivel = Column(String) # Primaria, Secundaria
    grado = Column(Integer)
    seccion = Column(String, default='A')
    docente_id = Column(Integer, ForeignKey("users.id"), nullable=True) # Profesor principal de la materia

class TutorDB(Base):
    __tablename__ = "tutores"
    id = Column(Integer, primary_key=True, index=True)
    docente_id = Column(Integer, ForeignKey("users.id"))
    nivel = Column(String)
    grado = Column(Integer)
    seccion = Column(String) # e.g. 'A', 'B'

class AlumnoDB(Base):
    __tablename__ = "alumnos"
    id = Column(Integer, primary_key=True, index=True)
    codigo_est = Column(String, unique=True, index=True)
    dni = Column(String, unique=True)
    nombres = Column(String)
    nivel = Column(String)
    grado = Column(Integer)
    seccion = Column(String, default='A')
    apoderado_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    estado = Column(String, default="Matriculado") # Aprobado, Matriculado, Repitente
    promedio_final = Column(Float, nullable=True)

class AsistenciaDB(Base):
    __tablename__ = "asistencia"
    id = Column(Integer, primary_key=True, index=True)
    alumno_id = Column(Integer, ForeignKey("alumnos.id"))
    fecha = Column(String) # YYYY-MM-DD
    estado = Column(String) # Presente, Falta, Tardanza

class NotaDB(Base):
    __tablename__ = "notas"
    id = Column(Integer, primary_key=True, index=True)
    alumno_id = Column(Integer, ForeignKey("alumnos.id"))
    curso_id = Column(Integer, ForeignKey("cursos.id"))
    docente_id = Column(Integer, ForeignKey("users.id"))
    criterio = Column(String) # Tareas, Participacion, Practicas, Examen
    semana = Column(String)
    valor_numerico = Column(Float, nullable=True) # Para secundaria
    valor_letra = Column(String, nullable=True) # AD, A, B, C para primaria
    observacion = Column(String, nullable=True)

class ObservacionDB(Base):
    __tablename__ = "observaciones"
    id = Column(Integer, primary_key=True, index=True)
    alumno_id = Column(Integer, ForeignKey("alumnos.id"))
    docente_id = Column(Integer, ForeignKey("users.id"))
    fecha = Column(String)
    texto = Column(String)

class CitaDB(Base):
    __tablename__ = "citas"
    id = Column(Integer, primary_key=True, index=True)
    alumno_id = Column(Integer, ForeignKey("alumnos.id"), nullable=True)
    codigo_obs = Column(String, nullable=True) # Para postulantes sin alumno_id
    motivo = Column(String) # 'Admisión', 'Rendimiento'
    psicologo_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    tutor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    dia = Column(String)
    hora = Column(String)
    estado = Column(String, default="Pendiente") # Pendiente, Atendido
    informe = Column(String, nullable=True)

class HorarioDB(Base):
    __tablename__ = "horarios"
    id = Column(Integer, primary_key=True, index=True)
    nivel = Column(String) # PRIMARIA, SECUNDARIA
    grado = Column(Integer)
    seccion = Column(String)
    dia = Column(String) # Lunes, Martes, etc.
    hora_inicio = Column(String) # "08:00"
    hora_fin = Column(String) # "08:45"
    curso_id = Column(Integer, ForeignKey("cursos.id"))
    docente_id = Column(Integer, ForeignKey("users.id"))

class CajaDiariaDB(Base):
    __tablename__ = "cajas_diarias"
    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(String) # YYYY-MM-DD
    estado = Column(String, default="Abierta") # Abierta, Cerrada
    monto_apertura = Column(Float, default=0.0)
    monto_cierre = Column(Float, nullable=True) # Lo que cuenta la secretaria en fisico
    recaudado_sistema = Column(Float, default=0.0) # Lo que suma el ERP
    diferencia = Column(Float, nullable=True)
    reporte_ia = Column(String, nullable=True) # Reporte de auditoría
    secretario_id = Column(Integer, ForeignKey("users.id"))

class TransaccionDB(Base):
    __tablename__ = "transacciones"
    id = Column(Integer, primary_key=True, index=True)
    caja_id = Column(Integer, ForeignKey("cajas_diarias.id"))
    monto = Column(Float)
    concepto = Column(String) # "Pensión Marzo", "Matrícula"
    metodo = Column(String) # "Efectivo", "Yape", "Transferencia BCP"
    alumno_id = Column(Integer, ForeignKey("alumnos.id"), nullable=True)
    fecha_hora = Column(String)
    aprobado = Column(Boolean, default=True)

class CompetenciaMINEDUDB(Base):
    __tablename__ = "minedu_competencias"
    id = Column(Integer, primary_key=True, index=True)
    nivel = Column(String, index=True)
    curso_nombre = Column(String, index=True)
    descripcion = Column(Text)

class CapacidadMINEDUDB(Base):
    __tablename__ = "minedu_capacidades"
    id = Column(Integer, primary_key=True, index=True)
    competencia_id = Column(Integer, ForeignKey("minedu_competencias.id"))
    descripcion = Column(Text)

class EstandarMINEDUDB(Base):
    __tablename__ = "minedu_estandares"
    id = Column(Integer, primary_key=True, index=True)
    nivel = Column(String, index=True)
    ciclo = Column(String, index=True)
    curso_nombre = Column(String, index=True)
    descripcion = Column(Text)

class DesempenoMINEDUDB(Base):
    __tablename__ = "minedu_desempenos"
    id = Column(Integer, primary_key=True, index=True)
    nivel = Column(String, index=True)
    grado = Column(Integer, index=True)
    curso_nombre = Column(String, index=True)
    descripcion = Column(Text)

class SilaboTemDB(Base):
    """Sílabo completo por curso, nivel y grado."""
    __tablename__ = "silabos"
    id = Column(Integer, primary_key=True, index=True)
    nivel = Column(String, index=True)           # PRIMARIA | SECUNDARIA
    grado = Column(Integer, index=True)          # 1-6 Primaria | 1-5 Secundaria
    curso_nombre = Column(String, index=True)    # Ej: "Matemática", "Comunicación"
    anno_escolar = Column(String, default="2025")  # Año lectivo
    
    # 14 Secciones del Sílabo MINEDU
    datos_informativos = Column(Text, nullable=True)
    fundamentacion = Column(Text, nullable=True)
    proposito = Column(Text, nullable=True)
    competencias = Column(Text, nullable=True)
    capacidades = Column(Text, nullable=True)
    estandares = Column(Text, nullable=True)
    desempennos = Column(Text, nullable=True)
    enfoques = Column(Text, nullable=True)
    organizacion_unidades = Column(Text, nullable=True)
    contenidos = Column(Text, nullable=True)
    metodologia = Column(Text, nullable=True)
    sistema_evaluacion = Column(Text, nullable=True)
    materiales = Column(Text, nullable=True)
    bibliografia = Column(Text, nullable=True)
    
    # Legacy (por si acaso para no romper el front)
    bimestre_1 = Column(Text, nullable=True)
    bimestre_2 = Column(Text, nullable=True)
    bimestre_3 = Column(Text, nullable=True)
    bimestre_4 = Column(Text, nullable=True)
    
    docente_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))
    updated_at = Column(String, nullable=True)

from sqlalchemy import text

def init_db():
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.commit()
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
