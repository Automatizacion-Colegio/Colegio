from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
from core.utils import ahora_lima

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

class AnioEscolarDB(Base):
    __tablename__ = "anios_escolares"
    id = Column(Integer, primary_key=True, index=True)
    anio = Column(Integer, unique=True, index=True)
    estado = Column(String, default="ACTIVO") # ACTIVO, CERRADO
    fecha_cierre = Column(String, nullable=True)
    inicio_matricula = Column(String, nullable=True)
    fin_matricula = Column(String, nullable=True)
    limite_rematricula = Column(String, nullable=True)

class ConfiguracionGlobalDB(Base):
    __tablename__ = "configuracion_global"
    id = Column(Integer, primary_key=True, index=True)
    cupos_primaria = Column(Integer, default=30)
    cupos_secundaria = Column(Integer, default=30)
    precio_matricula_primaria = Column(Float, default=0.0)
    precio_matricula_secundaria = Column(Float, default=0.0)
    precio_pension_primaria = Column(Float, default=0.0)
    precio_pension_secundaria = Column(Float, default=0.0)
    precio_recuperacion_primaria = Column(Float, default=0.0)
    precio_recuperacion_secundaria = Column(Float, default=0.0)

class MatriculaDB(Base):
    __tablename__ = "matriculas"
    id = Column(Integer, primary_key=True, index=True)
    alumno_id = Column(Integer, ForeignKey("alumnos.id"))
    anio_escolar_id = Column(Integer, ForeignKey("anios_escolares.id"))
    nivel = Column(String)
    grado = Column(Integer)
    seccion = Column(String, default='A')
    promedio_final = Column(Float, nullable=True)
    estado_final = Column(String, nullable=True) # Aprobado, Repitente, Recuperacion
    puesto = Column(Integer, nullable=True)
    estado_matricula = Column(String, default="CONFIRMADA") # CONFIRMADA, PENDIENTE_PAGO, PENDIENTE_RECUPERACION
    __table_args__ = (
        UniqueConstraint("alumno_id", "anio_escolar_id", name="uq_matricula_alumno_anio"),
    )

class CertificadoDB(Base):
    __tablename__ = "certificados"
    id = Column(Integer, primary_key=True, index=True)
    alumno_id = Column(Integer, ForeignKey("alumnos.id"))
    anio_escolar_id = Column(Integer, ForeignKey("anios_escolares.id"))
    tipo = Column(String) # MERITO, CONCLUSION_PRIMARIA, CONCLUSION_SECUNDARIA
    puesto = Column(Integer, nullable=True)
    ruta_archivo = Column(String)
    fecha_generacion = Column(String)
    storage_type = Column(String, default="LOCAL") # LOCAL o CLOUDINARY

class CursoRecuperacionDB(Base):
    __tablename__ = "cursos_recuperacion"
    id = Column(Integer, primary_key=True, index=True)
    matricula_id = Column(Integer, ForeignKey("matriculas.id"))
    curso_id = Column(Integer, ForeignKey("cursos.id"))
    nota_recuperacion = Column(String, nullable=True)
    estado = Column(String, default="PENDIENTE") # PENDIENTE, APROBADO, JALADO

class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    nombre_completo = Column(String, nullable=True)
    role = Column(String) # ADMIN, DOCENTE, PSICOLOGO, ALUMNO_PADRE, SECRETARIO
    nivel_asignado = Column(String, nullable=True) # PRIMARIA o SECUNDARIA (solo para DOCENTES)
    is_active = Column(Boolean, default=True)
    motivo_inactivo = Column(String, default="NINGUNO") # NINGUNO, EGRESADO, RETIRADO

class DocenteEspecialidadDB(Base):
    __tablename__ = "docente_especialidad"
    id = Column(Integer, primary_key=True, index=True)
    docente_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    curso_nombre = Column(String, nullable=False)
    nivel = Column(String, nullable=False)  # PRIMARIA o SECUNDARIA únicamente
    __table_args__ = (
        UniqueConstraint("docente_id", "curso_nombre", "nivel", name="uq_docente_especialidad"),
    )

class CursoDB(Base):
    __tablename__ = "cursos"
    id = Column(Integer, primary_key=True, index=True)
    anio_escolar_id = Column(Integer, ForeignKey("anios_escolares.id"), nullable=True)
    nombre = Column(String)
    nivel = Column(String) # Primaria, Secundaria
    grado = Column(Integer)
    seccion = Column(String, default='A')
    docente_id = Column(Integer, ForeignKey("users.id"), nullable=True) # Profesor principal de la materia

class TutorDB(Base):
    __tablename__ = "tutores"
    id = Column(Integer, primary_key=True, index=True)
    anio_escolar_id = Column(Integer, ForeignKey("anios_escolares.id"), nullable=True)
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
    estado_continuidad = Column(String, default="PENDIENTE") # PENDIENTE, SI, NO

class AsistenciaDB(Base):
    __tablename__ = "asistencia"
    id = Column(Integer, primary_key=True, index=True)
    anio_escolar_id = Column(Integer, ForeignKey("anios_escolares.id"), nullable=True)
    alumno_id = Column(Integer, ForeignKey("alumnos.id"))
    fecha = Column(String) # YYYY-MM-DD
    estado = Column(String) # Presente, Falta, Tardanza

class NotaDB(Base):
    __tablename__ = "notas"
    id = Column(Integer, primary_key=True, index=True)
    anio_escolar_id = Column(Integer, ForeignKey("anios_escolares.id"), nullable=True)
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

class TarifarioDB(Base):
    __tablename__ = "tarifarios"
    id = Column(Integer, primary_key=True, index=True)
    anio_escolar_id = Column(Integer, ForeignKey("anios_escolares.id"))
    nivel = Column(String) # PRIMARIA, SECUNDARIA
    concepto = Column(String) # MATRICULA, PENSION, RECUPERACION, CONSTANCIA
    monto = Column(Float)
    activo = Column(Boolean, default=True)

class CitaDB(Base):
    __tablename__ = "citas"
    id = Column(Integer, primary_key=True, index=True)
    alumno_id = Column(Integer, ForeignKey("alumnos.id"), nullable=True)
    codigo_obs = Column(String, nullable=True) # Para postulantes sin alumno_id
    dni_postulante = Column(String, nullable=True) # Enlace directo con AdmisionDB
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
    anio_escolar_id = Column(Integer, ForeignKey("anios_escolares.id"), nullable=True)
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
    grado = Column(Integer, index=True)
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
    created_at = Column(String, default=lambda: ahora_lima().strftime("%Y-%m-%d %H:%M"))
    updated_at = Column(String, nullable=True)

from sqlalchemy import text

class AdmisionDB(Base):
    __tablename__ = "admisiones"
    id = Column(Integer, primary_key=True, index=True)
    codigo_est = Column(String, unique=True, index=True)
    dni = Column(String)
    nombres = Column(String)
    apellidos = Column(String)
    nivel = Column(String)
    grado = Column(Integer)
    promedio = Column(Float)
    conducta = Column(String)
    ap_nombre = Column(String)
    ap_correo = Column(String)
    ap_telefono = Column(String)
    estado_proceso = Column(String, default="Pendiente Evaluación")
    fecha_registro = Column(DateTime, default=ahora_lima)

class EmailLogDB(Base):
    __tablename__ = "email_logs"
    id = Column(Integer, primary_key=True, index=True)
    destinatario = Column(String, index=True)
    asunto = Column(String)
    cuerpo = Column(Text)
    fecha_envio = Column(DateTime, default=ahora_lima)
    estado = Column(String, default="Enviado") # Enviado, Fallido
    error_msg = Column(String, nullable=True)

def init_db():
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        # Ejecutar las actualizaciones de esquema para columnas nuevas
        try:
            conn.execute(text("ALTER TABLE citas ADD COLUMN IF NOT EXISTS codigo_obs VARCHAR;"))
            conn.execute(text("ALTER TABLE citas ADD COLUMN IF NOT EXISTS dni_postulante VARCHAR;"))
            conn.execute(text("ALTER TABLE citas ADD COLUMN IF NOT EXISTS psicologo_id INTEGER REFERENCES users(id);"))
            conn.execute(text("ALTER TABLE citas ADD COLUMN IF NOT EXISTS informe VARCHAR;"))
            
            conn.execute(text("ALTER TABLE admisiones ADD COLUMN IF NOT EXISTS promedio FLOAT;"))
            conn.execute(text("ALTER TABLE admisiones ADD COLUMN IF NOT EXISTS conducta VARCHAR;"))
        except Exception as e:
            print(f"Nota: No se pudieron actualizar las columnas: {e}")
        conn.commit()
    Base.metadata.create_all(bind=engine)
    
    # Limpiar cursos huérfanos
    try:
        db = SessionLocal()
        db.execute(text("UPDATE cursos SET docente_id = NULL WHERE docente_id IS NOT NULL AND docente_id NOT IN (SELECT id FROM users)"))
        db.commit()
        db.close()
    except Exception as e:
        print(f"Nota: No se pudo limpiar cursos huérfanos: {e}")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
