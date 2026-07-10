from sqlalchemy.orm import Session
from models.database import CursoDB, HorarioDB, TutorDB
import random

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
BLOQUES = [
    ("08:00", "08:45"),
    ("08:45", "09:30"),
    ("09:30", "10:15"),
    ("10:45", "11:30"), # Recreo 10:15 - 10:45
    ("11:30", "12:15"),
    ("12:15", "13:00"),
    ("13:15", "14:00")  # Recreo 13:00 - 13:15
]

def generate_timetables(db: Session, target_nivel: str = None):
    # Borrar horarios existentes
    if target_nivel:
        db.query(HorarioDB).filter(HorarioDB.nivel == target_nivel).delete()
    else:
        db.query(HorarioDB).delete()
    db.commit()

    # Obtener todas las aulas (nivel, grado, seccion) basadas en cursos
    if target_nivel:
        cursos_db = db.query(CursoDB).filter(CursoDB.nivel == target_nivel).all()
    else:
        cursos_db = db.query(CursoDB).all()
        
    if not cursos_db:
        return

    aulas = list(set((c.nivel, c.grado, c.seccion) for c in cursos_db))

    # Organizar cursos por aula
    cursos_por_aula = {}
    for c in cursos_db:
        key = (c.nivel, c.grado, c.seccion)
        if key not in cursos_por_aula:
            cursos_por_aula[key] = []
        cursos_por_aula[key].append(c)

    MAX_ATTEMPTS = 200
    mejor_conflictos = float('inf')
    mejor_horario = []
    
    for attempt in range(MAX_ATTEMPTS):
        ocupacion_docentes = {}
        horarios_temporales = []
        conflictos_en_intento = 0

        # Requerimientos por aula
        requerimientos = {}
        for aula in aulas:
            req = {c.id: 0 for c in cursos_por_aula[aula]}
            ca = cursos_por_aula[aula]
            
            # Distribución de horas
            horas_asignadas = 0
            for c in ca:
                nombre = c.nombre.lower()
                if any(x in nombre for x in ["matemática", "comunicación"]):
                    horas = 6
                elif any(x in nombre for x in ["ciencia", "personal"]):
                    horas = 4
                elif any(x in nombre for x in ["inglés", "educación física", "religión"]):
                    horas = 2 # Especialistas dictan 2 horas por aula (2 * 12 aulas = 24 horas < 35 horas max)
                else:
                    horas = 2
                req[c.id] = horas
                horas_asignadas += horas
            
            # Si faltan horas para llegar a 35, se las damos a matemática/comunicación
            idx = 0
            while horas_asignadas < 35:
                req[ca[idx % len(ca)].id] += 1
                horas_asignadas += 1
                idx += 1
            
            # Si sobran horas, quitamos de los que tienen más de 2
            while horas_asignadas > 35:
                for c in ca:
                    if req[c.id] > 2:
                        req[c.id] -= 1
                        horas_asignadas -= 1
                        if horas_asignadas == 35:
                            break
                            
            requerimientos[aula] = req

        # Llenar bloque por bloque para distribuir las restricciones
        for d_idx, dia in enumerate(DIAS):
            for b_idx, (hora_inicio, hora_fin) in enumerate(BLOQUES):
                aulas_mezcladas = aulas.copy()
                random.shuffle(aulas_mezcladas)

                for aula in aulas_mezcladas:
                    nivel, grado, seccion = aula
                    cursos_aula = cursos_por_aula[aula]
                    
                    # Filtrar cursos que aún necesitan horas y cuyo docente está libre
                    opciones = [
                        c for c in cursos_aula 
                        if requerimientos[aula][c.id] > 0 and 
                        (not c.docente_id or not ocupacion_docentes.get((c.docente_id, d_idx, b_idx)))
                    ]

                    if not opciones:
                        # Fallback: Assign a free study block if no teacher is available
                        horarios_temporales.append(HorarioDB(
                            nivel=nivel,
                            grado=grado,
                            seccion=seccion,
                            dia=dia,
                            hora_inicio=hora_inicio,
                            hora_fin=hora_fin,
                            curso_id=None,
                            docente_id=None
                        ))
                        conflictos_en_intento += 1
                        continue

                    # Sort by how constrained the teacher is (number of remaining hours for that teacher across all aulas)
                    # To keep it simple and fast, we just pick randomly but ensure we don't strictly block specialists from the morning.
                    # Prioritizar cursos pesados en la mañana (pero con probabilidad, no estricto)
                    pesados = [c for c in opciones if any(x in c.nombre.lower() for x in ["matem", "comunica", "física", "química", "ciencia"])]
                    livianos = [c for c in opciones if c not in pesados]

                    if b_idx < 3 and pesados and random.random() < 0.6:
                        c = random.choice(pesados)
                    elif livianos and random.random() < 0.8:
                        c = random.choice(livianos)
                    else:
                        c = random.choice(opciones)

                    requerimientos[aula][c.id] -= 1
                    if c.docente_id:
                        ocupacion_docentes[(c.docente_id, d_idx, b_idx)] = True

                    horarios_temporales.append(HorarioDB(
                        nivel=nivel,
                        grado=grado,
                        seccion=seccion,
                        dia=dia,
                        hora_inicio=hora_inicio,
                        hora_fin=hora_fin,
                        curso_id=c.id,
                        docente_id=c.docente_id
                    ))
                
        # Guardar el mejor intento (el que tiene menos conflictos)
        if conflictos_en_intento < mejor_conflictos:
            mejor_conflictos = conflictos_en_intento
            mejor_horario = horarios_temporales
            
        if mejor_conflictos == 0:
            break

    # Guardar en DB el mejor horario encontrado
    for h in mejor_horario:
        db.add(h)
    db.commit()
