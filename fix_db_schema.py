import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from dotenv import load_dotenv

# Cargar variables de entorno si las hay
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("Por favor, asegúrate de tener la variable de entorno DATABASE_URL configurada con la conexión a tu base de datos de producción (Supabase).")
    exit(1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def actualizar_esquema_produccion():
    db = SessionLocal()
    try:
        print("Intentando actualizar la tabla 'citas' en producción...")
        # Agregar codigo_obs si no existe
        db.execute(text("ALTER TABLE citas ADD COLUMN IF NOT EXISTS codigo_obs VARCHAR;"))
        
        # Agregar dni_postulante si no existe
        db.execute(text("ALTER TABLE citas ADD COLUMN IF NOT EXISTS dni_postulante VARCHAR;"))

        # Agregar psicologo_id si no existe
        db.execute(text("ALTER TABLE citas ADD COLUMN IF NOT EXISTS psicologo_id INTEGER REFERENCES users(id);"))
        
        # Agregar informe si no existe
        db.execute(text("ALTER TABLE citas ADD COLUMN IF NOT EXISTS informe VARCHAR;"))

        db.commit()
        print("¡Esquema actualizado correctamente! Las columnas faltantes fueron añadidas a 'citas'.")
    except Exception as e:
        db.rollback()
        print(f"Error al actualizar el esquema: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    actualizar_esquema_produccion()
