import os
from sqlalchemy.orm import Session
from models.database import SessionLocal, UserDB, DocenteEspecialidadDB, CursoDB
from utils.security import get_password_hash

# Nombres reales para profesores
profesores = [
    # PRIMARIA (Polidocentes)
    {"username": "mariagonzales", "nivel": "PRIMARIA", "tipo": "polidocente"},
    {"username": "rosaperez", "nivel": "PRIMARIA", "tipo": "polidocente"},
    {"username": "carmensalinas", "nivel": "PRIMARIA", "tipo": "polidocente"},
    {"username": "jorgegomez", "nivel": "PRIMARIA", "tipo": "polidocente"},
    {"username": "analopez", "nivel": "PRIMARIA", "tipo": "polidocente"},
    {"username": "patriciatorres", "nivel": "PRIMARIA", "tipo": "polidocente"},
    {"username": "luissanchez", "nivel": "PRIMARIA", "tipo": "polidocente"},
    {"username": "elizabethgarcia", "nivel": "PRIMARIA", "tipo": "polidocente"},
    
    # PRIMARIA (Especialistas - Enseñan cursos específicos en primaria)
    {"username": "carlosespinoza", "nivel": "PRIMARIA", "tipo": "especialista", "cursos": ["Educación Física"]},
    {"username": "teresaguzman", "nivel": "PRIMARIA", "tipo": "especialista", "cursos": ["Inglés"]},
    {"username": "hectorsilva", "nivel": "PRIMARIA", "tipo": "especialista", "cursos": ["Religión"]},

    # SECUNDARIA (Especializados por curso)
    {"username": "robertoruiz", "nivel": "SECUNDARIA", "tipo": "especialista", "cursos": ["Matemática"]},
    {"username": "fernandovargas", "nivel": "SECUNDARIA", "tipo": "especialista", "cursos": ["Matemática", "Física"]},
    {"username": "elenacastro", "nivel": "SECUNDARIA", "tipo": "especialista", "cursos": ["Comunicación"]},
    {"username": "silviarojas", "nivel": "SECUNDARIA", "tipo": "especialista", "cursos": ["Comunicación", "Literatura"]},
    {"username": "pedrogutierrez", "nivel": "SECUNDARIA", "tipo": "especialista", "cursos": ["Ciencia y Tecnología", "Biología"]},
    {"username": "miguelcastillo", "nivel": "SECUNDARIA", "tipo": "especialista", "cursos": ["Ciencia y Tecnología", "Química"]},
    {"username": "javierfernandez", "nivel": "SECUNDARIA", "tipo": "especialista", "cursos": ["Ciencias Sociales", "Historia"]},
    {"username": "andreamedina", "nivel": "SECUNDARIA", "tipo": "especialista", "cursos": ["Ciencias Sociales", "Geografía"]},
    {"username": "manuelrodriguez", "nivel": "SECUNDARIA", "tipo": "especialista", "cursos": ["Educación Física"]},
    {"username": "sofianavarro", "nivel": "SECUNDARIA", "tipo": "especialista", "cursos": ["Inglés"]},
    {"username": "rauldominguez", "nivel": "SECUNDARIA", "tipo": "especialista", "cursos": ["Arte y Cultura"]},
    {"username": "lauravillanueva", "nivel": "SECUNDARIA", "tipo": "especialista", "cursos": ["Desarrollo Personal", "Tutoría"]},
]

def seed():
    db = SessionLocal()
    try:
        # Obtener todos los cursos únicos por nivel
        cursos_primaria = [c[0] for c in db.query(CursoDB.nombre).filter(CursoDB.nivel == 'PRIMARIA').distinct().all()]
        cursos_secundaria = [c[0] for c in db.query(CursoDB.nombre).filter(CursoDB.nivel == 'SECUNDARIA').distinct().all()]
        
        # Cursos base de primaria (Polidocencia)
        excluir_primaria = ['Inglés', 'Educación Física', 'Religión']
        cursos_base_primaria = [c for c in cursos_primaria if c not in excluir_primaria]

        if not cursos_primaria or not cursos_secundaria:
            print("⚠️ ADVERTENCIA: No hay cursos registrados en la base de datos. Los profesores se crearán sin especialidades.")

        creados = 0
        for prof in profesores:
            # 1. Crear Usuario
            existente = db.query(UserDB).filter(UserDB.username == prof['username']).first()
            if existente:
                print(f"[{prof['username']}] Ya existe, omitiendo...")
                continue
            
            nuevo_user = UserDB(
                username=prof['username'],
                hashed_password=get_password_hash(f"{prof['username']}123"), # Contraseña por defecto: nombre123
                role="DOCENTE",
                nivel_asignado=prof['nivel'],
                is_active=True
            )
            db.add(nuevo_user)
            db.commit()
            db.refresh(nuevo_user)
            creados += 1
            
            # 2. Asignar Especialidades
            especialidades_a_insertar = []
            if prof['tipo'] == 'polidocente':
                # Asignar todos los cursos base de primaria
                for curso in cursos_base_primaria:
                    especialidades_a_insertar.append(
                        DocenteEspecialidadDB(docente_id=nuevo_user.id, curso_nombre=curso, nivel=prof['nivel'])
                    )
            elif prof['tipo'] == 'especialista':
                # Asignar cursos específicos si existen en la BD
                cursos_disponibles = cursos_primaria if prof['nivel'] == 'PRIMARIA' else cursos_secundaria
                for curso_esp in prof['cursos']:
                    # Hacemos match suave o lo agregamos directo si queremos forzar que enseñe ese curso
                    if curso_esp in cursos_disponibles:
                        especialidades_a_insertar.append(
                            DocenteEspecialidadDB(docente_id=nuevo_user.id, curso_nombre=curso_esp, nivel=prof['nivel'])
                        )
                    else:
                        # Si el curso no existe en la currícula actual, igual lo agregamos como especialidad válida
                        especialidades_a_insertar.append(
                            DocenteEspecialidadDB(docente_id=nuevo_user.id, curso_nombre=curso_esp, nivel=prof['nivel'])
                        )

            if especialidades_a_insertar:
                db.add_all(especialidades_a_insertar)
                db.commit()
            
            print(f"✅ Registrado: {prof['username']} ({prof['nivel']}) - {len(especialidades_a_insertar)} especialidades")

        print(f"\n🎉 Seed finalizado! Se crearon {creados} profesores.")
        print("💡 Contraseña para todos los nuevos usuarios: [username]123 (ej. mariagonzales123)")

    except Exception as e:
        db.rollback()
        print(f"❌ Error durante el seed: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed()
