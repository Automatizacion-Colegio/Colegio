from sqlalchemy import text
from models.database import SessionLocal, engine, Base

def run_migration():
    print("1. Creando tablas nuevas (cursos_recuperacion)...")
    # Base.metadata.create_all ensures any new tables defined in models are created
    Base.metadata.create_all(bind=engine)
    
    print("2. Agregando nuevas columnas a tablas existentes...")
    
    with engine.connect() as conn:
        # Add motivo_inactivo to users
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN motivo_inactivo VARCHAR DEFAULT 'NINGUNO';"))
            conn.commit()
            print(" [+] Columna motivo_inactivo agregada a users.")
        except Exception as e:
            conn.rollback()
            print(f" [!] Omitiendo motivo_inactivo en users (ya existe o error: {e}).")

        # Add estado_matricula to matriculas
        try:
            conn.execute(text("ALTER TABLE matriculas ADD COLUMN estado_matricula VARCHAR DEFAULT 'CONFIRMADA';"))
            conn.commit()
            print(" [+] Columna estado_matricula agregada a matriculas.")
        except Exception as e:
            conn.rollback()
            print(f" [!] Omitiendo estado_matricula en matriculas (ya existe o error: {e}).")

        # Add tipo to certificados
        try:
            conn.execute(text("ALTER TABLE certificados ADD COLUMN tipo VARCHAR;"))
            conn.commit()
            print(" [+] Columna tipo agregada a certificados.")
        except Exception as e:
            conn.rollback()
            print(f" [!] Omitiendo tipo en certificados (ya existe o error: {e}).")

    print("Migración de cierre escolar completada.")

if __name__ == "__main__":
    run_migration()
