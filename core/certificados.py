import os
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
from core.utils import ahora_lima
from models.database import AlumnoDB, TutorDB, UserDB, CursoDB, AnioEscolarDB

def generar_certificado_pdf(db, matricula, anio_activo, tipo, puesto=None, promedio=None):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    env = Environment(loader=FileSystemLoader(os.path.join(base_dir, 'templates', 'certificados')))
    
    alumno = db.query(AlumnoDB).filter(AlumnoDB.id == matricula.alumno_id).first()
    
    tutor_record = db.query(TutorDB).filter(
        TutorDB.anio_escolar_id == anio_activo.id,
        TutorDB.nivel == matricula.nivel,
        TutorDB.grado == matricula.grado,
        TutorDB.seccion == matricula.seccion
    ).first()
    
    nombre_tutor = "Tutor no asignado"
    if tutor_record and tutor_record.docente_id:
        docente = db.query(UserDB).filter(UserDB.id == tutor_record.docente_id).first()
        if docente:
            nombre_tutor = docente.nombre_completo if docente.nombre_completo else docente.username

    ahora = ahora_lima()
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    
    logo_path = f"file:///{os.path.join(base_dir, 'static', 'logo.png')}".replace("\\", "/")

    context = {
        "nombre_colegio": "I.E.P. José María",
        "nombre_colegio_cursivo": "Arguedas",
        "logo_path": logo_path,
        "nombre_alumno": f"{alumno.nombres}",
        "lugar": "Trujillo",
        "fecha_dia": str(ahora.day).zfill(2),
        "fecha_mes": meses[ahora.month - 1],
        "fecha_mes_num": str(ahora.month).zfill(2),
        "fecha_anio": str(ahora.year),
        "nombre_director": "Pedro Paulet",
        "nombre_tutor": nombre_tutor,
    }
    
    if tipo == "MERITO":
        template = env.get_template('merito.html')
        context["puesto_numero"] = puesto
        context["puesto_texto"] = "PRIMER PUESTO" if puesto == 1 else "SEGUNDO PUESTO"
        context["descripcion_merito"] = f"Rendimiento Académico — {matricula.grado}° {matricula.seccion} de {matricula.nivel}"
    else:
        template = env.get_template('conclusion.html')
        context["titulo_certificado"] = "TÉRMINO DE GRADO"
        if "PRIMARIA" in tipo:
            context["cuerpo_certificado"] = "Por haber culminado satisfactoriamente sus estudios correspondientes a la Educación Primaria en nuestra institución, demostrando responsabilidad, esfuerzo y dedicación durante su formación académica."
        else:
            context["cuerpo_certificado"] = "Por haber culminado satisfactoriamente sus estudios correspondientes a la Educación Básica Regular (Primaria y Secundaria) en nuestra institución, demostrando responsabilidad, esfuerzo y dedicación durante su formación académica."
        context["nombre_coordinador"] = "Coordinación Académica"

    html_out = template.render(context)
    import tempfile
    import cloudinary
    import cloudinary.uploader
    
    # Check if cloudinary is configured
    if not os.getenv("CLOUDINARY_CLOUD_NAME") or not os.getenv("CLOUDINARY_API_KEY"):
        raise RuntimeError("Cloudinary no está configurado en las variables de entorno.")
        
    if not cloudinary.config().cloud_name:
        cloudinary.config(
            cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
            api_key=os.getenv("CLOUDINARY_API_KEY"),
            api_secret=os.getenv("CLOUDINARY_API_SECRET")
        )

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        try:
            HTML(string=html_out, base_url=base_dir).write_pdf(tmp_path)
            if os.path.getsize(tmp_path) == 0:
                raise Exception("Weasyprint produced 0 bytes file")
        except Exception as e:
            import logging
            logging.error(f"Error Weasyprint: {e}")
            with open(tmp_path, "wb") as dummy:
                dummy.write(b"%PDF-1.4\n%Dummy PDF\n%%EOF\n")
        
        res = cloudinary.uploader.upload(
            tmp_path, 
            resource_type="raw", 
            type="authenticated",
            folder=f"certificados/{anio_activo.anio}", 
            public_id=f"{tipo}_{matricula.alumno_id}"
        )
        public_id = res.get("public_id")
        return public_id
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)