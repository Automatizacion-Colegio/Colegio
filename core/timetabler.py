from sqlalchemy.orm import Session
from models.database import CursoDB, HorarioDB, TutorDB, DocenteEspecialidadDB, AnioEscolarDB, UserDB
import random
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
BLOQUES = [
    ("08:00", "08:45"),
    ("08:45", "09:30"),
    ("09:30", "10:15"),
    ("10:45", "11:30"),  # Recreo 10:15 - 10:45
    ("11:30", "12:15"),
    ("12:15", "13:00"),
    ("13:15", "14:00")   # Recreo 13:00 - 13:15
]


def _get_docentes_con_especialidad(db: Session, curso_nombre: str, nivel: str) -> list:
    anio_activo = db.query(AnioEscolarDB).filter(AnioEscolarDB.estado == "ACTIVO").first()
    """
    Retorna lista de docente_id que tienen especialización en (curso_nombre, nivel).
    Solo acepta PRIMARIA o SECUNDARIA — no existe nivel AMBOS.
    """
    esps = db.query(DocenteEspecialidadDB).filter(
        DocenteEspecialidadDB.curso_nombre == curso_nombre,
        DocenteEspecialidadDB.nivel == nivel.upper()
    ).all()
    return [e.docente_id for e in esps]


def generate_timetables(db: Session, target_nivel: str = None) -> dict:
    anio_activo = db.query(AnioEscolarDB).filter(AnioEscolarDB.estado == "ACTIVO").first()
    """
    Genera horarios para todas las aulas (o solo el nivel indicado).
    Asigna docentes ÚNICAMENTE si tienen la especialización correspondiente.
    Retorna un dict con advertencias para que el endpoint las muestre al admin.
    """
    # Borrar horarios existentes
    if target_nivel:
        db.query(HorarioDB).filter(HorarioDB.anio_escolar_id == (anio_activo.id if anio_activo else None)).filter(HorarioDB.nivel == target_nivel).delete()
    else:
        db.query(HorarioDB).filter(HorarioDB.anio_escolar_id == (anio_activo.id if anio_activo else None)).delete()
    db.commit()

    if target_nivel:
        cursos_db = db.query(CursoDB).filter(CursoDB.anio_escolar_id == (anio_activo.id if anio_activo else None)).filter(CursoDB.nivel == target_nivel).all()
    else:
        cursos_db = db.query(CursoDB).filter(CursoDB.anio_escolar_id == (anio_activo.id if anio_activo else None)).all()

    if not cursos_db:
        return {"conflictos_resueltos": True, "bloques_libres": 0, "advertencias": []}

    aulas = list(set((c.nivel, c.grado, c.seccion) for c in cursos_db))

    cursos_por_aula = {}
    for c in cursos_db:
        key = (c.nivel, c.grado, c.seccion)
        cursos_por_aula.setdefault(key, []).append(c)

    # Obtener tutores
    tutores_db = db.query(TutorDB).filter(TutorDB.anio_escolar_id == (anio_activo.id if anio_activo else None)).all()
    tutor_por_aula = {(t.nivel, t.grado, t.seccion): t.docente_id for t in tutores_db}

    # Pre-computar: (curso_nombre, nivel) → [docente_id, ...] con especialización
    combinaciones_unicas = {(c.nombre, c.nivel) for c in cursos_db}
    docentes_por_curso = {
        (nombre, nivel_c): _get_docentes_con_especialidad(db, nombre, nivel_c)
        for (nombre, nivel_c) in combinaciones_unicas
    }

    # Advertencias previas: cursos sin ningún docente especializado
    advertencias_previas = []
    for aula in aulas:
        nivel, grado, seccion = aula
        for c in cursos_por_aula[aula]:
            es_tutoria = "tutoría" in c.nombre.lower() or "tutoria" in c.nombre.lower()
            is_special = any(x in c.nombre.lower() for x in ["inglés", "educación física", "religión"])
            
            if es_tutoria:
                docs = [tutor_por_aula.get(aula)] if tutor_por_aula.get(aula) else []
            elif nivel == "PRIMARIA" and not is_special:
                docs = [tutor_por_aula.get(aula)] if tutor_por_aula.get(aula) else []
            else:
                docs = docentes_por_curso.get((c.nombre, nivel), [])
                
            if not docs:
                if es_tutoria or (nivel == "PRIMARIA" and not is_special):
                    msg = f"SIN TUTOR ASIGNADO: '{c.nombre}' para {grado}° {seccion} de {nivel}"
                else:
                    msg = (f"SIN DOCENTE ESPECIALIZADO: '{c.nombre}' para "
                           f"{grado}° {seccion} de {nivel}")
                if msg not in advertencias_previas:
                    advertencias_previas.append(msg)
                    logger.warning(f"Timetabler ⚠️  {msg}")

    # Contador de horas por docente (para balanceo de carga)
    # horas_docente[docente_id] = cantidad de bloques ya asignados en este intento
    MAX_ATTEMPTS = 200
    mejor_conflictos = float('inf')
    mejor_horario = []
    mejor_advertencias_intento = []

    for attempt in range(MAX_ATTEMPTS):
        ocupacion_docentes = {}   # (docente_id, dia_idx, bloque_idx) → True
        horas_docente = defaultdict(int)  # docente_id → bloques asignados (balanceo)
        horarios_temporales = []
        conflictos_en_intento = 0
        advertencias_intento = []

        # Calcular requerimientos de horas por curso/aula
        requerimientos = {}
        for aula in aulas:
            req = {c.id: 0 for c in cursos_por_aula[aula]}
            ca = cursos_por_aula[aula]
            horas_asignadas = 0
            for c in ca:
                nombre = c.nombre.lower()
                if any(x in nombre for x in ["matemática", "comunicación"]):
                    horas = 6
                elif any(x in nombre for x in ["ciencia", "personal"]):
                    horas = 4
                elif any(x in nombre for x in ["inglés", "educación física", "religión"]):
                    horas = 2
                else:
                    horas = 2
                req[c.id] = horas
                horas_asignadas += horas

            idx = 0
            while horas_asignadas < 35:
                req[ca[idx % len(ca)].id] += 1
                horas_asignadas += 1
                idx += 1
            while horas_asignadas > 35:
                for c in ca:
                    if req[c.id] > 2:
                        req[c.id] -= 1
                        horas_asignadas -= 1
                        if horas_asignadas == 35:
                            break

            requerimientos[aula] = req

        for d_idx, dia in enumerate(DIAS):
            for b_idx, (hora_inicio, hora_fin) in enumerate(BLOQUES):
                aulas_mezcladas = aulas.copy()
                random.shuffle(aulas_mezcladas)

                for aula in aulas_mezcladas:
                    nivel, grado, seccion = aula
                    cursos_aula = cursos_por_aula[aula]

                    # Para cada curso con horas pendientes, encontrar docente disponible con especialización
                    opciones_con_docente = []
                    for c in cursos_aula:
                        if requerimientos[aula][c.id] <= 0:
                            continue

                        es_tutoria = "tutoría" in c.nombre.lower() or "tutoria" in c.nombre.lower()
                        is_special = any(x in c.nombre.lower() for x in ["inglés", "educación física", "religión"])
                        
                        if es_tutoria:
                            tutor_id = tutor_por_aula.get(aula)
                            if not tutor_id:
                                continue
                            docs_habilitados = [tutor_id]
                        elif nivel == "PRIMARIA" and not is_special:
                            tutor_id = tutor_por_aula.get(aula)
                            if not tutor_id:
                                continue
                            docs_habilitados = [tutor_id]
                        else:
                            docs_habilitados = docentes_por_curso.get((c.nombre, nivel), [])

                        if not docs_habilitados:
                            continue  # ya advertido arriba

                        # Docentes libres en este slot
                        docs_libres = [
                            d for d in docs_habilitados
                            if not ocupacion_docentes.get((d, d_idx, b_idx))
                        ]
                        if docs_libres:
                            opciones_con_docente.append((c, docs_libres))

                    if not opciones_con_docente:
                        adv = (f"Bloque libre: {grado}°{seccion} {nivel} "
                               f"{dia} {hora_inicio}")
                        advertencias_intento.append(adv)
                        horarios_temporales.append(HorarioDB(anio_escolar_id=anio_activo.id if anio_activo else None, 
                            nivel=nivel, grado=grado, seccion=seccion,
                            dia=dia, hora_inicio=hora_inicio, hora_fin=hora_fin,
                            curso_id=None, docente_id=None
                        ))
                        conflictos_en_intento += 1
                        continue

                    # Priorizar cursos pesados en bloques de mañana
                    pesados = [(c, dl) for c, dl in opciones_con_docente
                               if any(x in c.nombre.lower() for x in ["matem", "comunica", "física", "química", "ciencia"])]
                    livianos = [(c, dl) for c, dl in opciones_con_docente if (c, dl) not in pesados]

                    if b_idx < 3 and pesados and random.random() < 0.6:
                        curso_sel, docs_libres_sel = random.choice(pesados)
                    elif livianos and random.random() < 0.8:
                        curso_sel, docs_libres_sel = random.choice(livianos)
                    else:
                        curso_sel, docs_libres_sel = random.choice(opciones_con_docente)

                    # BALANCEO DE CARGA: elegir docente con menos horas asignadas hasta ahora
                    docente_sel = min(docs_libres_sel, key=lambda d: horas_docente[d])

                    requerimientos[aula][curso_sel.id] -= 1
                    ocupacion_docentes[(docente_sel, d_idx, b_idx)] = True
                    horas_docente[docente_sel] += 1

                    horarios_temporales.append(HorarioDB(anio_escolar_id=anio_activo.id if anio_activo else None, 
                        nivel=nivel, grado=grado, seccion=seccion,
                        dia=dia, hora_inicio=hora_inicio, hora_fin=hora_fin,
                        curso_id=curso_sel.id,
                        docente_id=docente_sel
                    ))

        if conflictos_en_intento < mejor_conflictos:
            mejor_conflictos = conflictos_en_intento
            mejor_horario = horarios_temporales
            mejor_advertencias_intento = advertencias_intento

        if mejor_conflictos == 0:
            break

    for h in mejor_horario:
        db.add(h)
    db.commit()

    # Deduplicar advertencias
    todas_advertencias = list(dict.fromkeys(advertencias_previas + mejor_advertencias_intento))

    return {
        "conflictos_resueltos": mejor_conflictos == 0,
        "bloques_libres": mejor_conflictos,
        "advertencias": todas_advertencias
    }
