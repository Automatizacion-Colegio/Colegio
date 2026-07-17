from sqlalchemy import text
from models.database import SessionLocal, engine, Base, AnioEscolarDB, MatriculaDB, AlumnoDB

def run_migration():
    print("1. Creando tablas nuevas (anios_escolares, matriculas, certificados)...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    print("2. Agregando columnas a tablas existentes...")
    tables = ["cursos", "tutores", "horarios", "notas", "asistencia"]
    
    for table in tables:
        with engine.connect() as conn:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN anio_escolar_id INTEGER;"))
                conn.commit()
                print(f" [+] Columna anio_escolar_id agregada a {table}.")
            except Exception as e:
                conn.rollback()
                print(f" [!] Omitiendo {table} (ya existe la columna o error).")
            
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_anio FOREIGN KEY (anio_escolar_id) REFERENCES anios_escolares(id);"))
                conn.commit()
            except Exception:
                conn.rollback()

    print("3. Creando Año Escolar 2026 por defecto...")
    anio_2026 = db.query(AnioEscolarDB).filter(AnioEscolarDB.anio == 2026).first()
    if not anio_2026:
        anio_2026 = AnioEscolarDB(anio=2026, estado="ACTIVO")
        db.add(anio_2026)
        db.commit()
        db.refresh(anio_2026)
        print(" [+] Año 2026 ACTIVO creado.")
    else:
        print(" [*] Año 2026 ya existía.")
        
    print("4. Actualizando registros existentes al Año 2026...")
    for table in tables:
        with engine.connect() as conn:
            try:
                conn.execute(text(f"UPDATE {table} SET anio_escolar_id = :id WHERE anio_escolar_id IS NULL;"), {"id": anio_2026.id})
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(e)
                
    print("5. Generando Matrículas desde Alumnos actuales...")
    alumnos = db.query(AlumnoDB).all()
    matriculas_creadas = 0
    for alumno in alumnos:
        existe = db.query(MatriculaDB).filter(MatriculaDB.alumno_id == alumno.id, MatriculaDB.anio_escolar_id == anio_2026.id).first()
        if not existe:
            mat = MatriculaDB(
                alumno_id=alumno.id,
                anio_escolar_id=anio_2026.id,
                nivel=alumno.nivel,
                grado=alumno.grado,
                seccion=alumno.seccion
            )
            db.add(mat)
            matriculas_creadas += 1
    db.commit()
    print(f" [+] Se generaron {matriculas_creadas} matrículas.")

    db.close()
    print("Migración completada.")

if __name__ == "__main__":
    run_migration()
