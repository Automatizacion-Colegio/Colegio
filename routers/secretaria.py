import os
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from core.utils import ahora_lima
from core.certificados import generar_certificado_pdf
from sqlalchemy.orm import Session
from models.database import get_db, CajaDiariaDB, TransaccionDB, AlumnoDB, AdmisionDB, CursoRecuperacionDB, MatriculaDB, CursoDB, AnioEscolarDB, UserDB, CertificadoDB
from core.antigravity import school_db
from auth.security import get_current_user, TokenData, require_role
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
import pytesseract
from PIL import Image
import io

router = APIRouter(prefix="/secretaria", tags=["Secretaria y Caja"])

class AbrirCajaReq(BaseModel):
    monto_apertura: float

class CierreCajaReq(BaseModel):
    monto_cierre: float

class TransaccionReq(BaseModel):
    monto: float
    concepto: str
    metodo: str
    alumno_id: Optional[int] = None

@router.post("/caja/abrir")
async def abrir_caja(req: AbrirCajaReq, db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["SECRETARIO"]))):
    # Verify no open register exists for today
    hoy = ahora_lima().strftime("%Y-%m-%d")
    caja = db.query(CajaDiariaDB).filter(CajaDiariaDB.fecha == hoy, CajaDiariaDB.estado == "Abierta").first()
    if caja:
        raise HTTPException(status_code=400, detail="Ya hay una caja abierta para hoy.")
    
    nueva_caja = CajaDiariaDB(
        fecha=hoy,
        estado="Abierta",
        monto_apertura=req.monto_apertura,
        recaudado_sistema=0.0,
        secretario_id=current_user.user_id
    )
    db.add(nueva_caja)
    db.commit()
    db.refresh(nueva_caja)
    return nueva_caja

@router.get("/caja/estado")
async def estado_caja(db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["SECRETARIO", "ADMIN"]))):
    hoy = ahora_lima().strftime("%Y-%m-%d")
    caja = db.query(CajaDiariaDB).filter(CajaDiariaDB.fecha == hoy, CajaDiariaDB.estado == "Abierta").first()
    if not caja:
        return {"estado": "Cerrada", "caja": None, "transacciones": []}
    
    txs = db.query(TransaccionDB).filter(TransaccionDB.caja_id == caja.id).all()
    return {"estado": "Abierta", "caja": caja, "transacciones": txs}

@router.post("/caja/transaccion")
async def registrar_transaccion(req: TransaccionReq, db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["SECRETARIO"]))):
    hoy = ahora_lima().strftime("%Y-%m-%d")
    caja = db.query(CajaDiariaDB).filter(CajaDiariaDB.fecha == hoy, CajaDiariaDB.estado == "Abierta").first()
    if not caja:
        raise HTTPException(status_code=400, detail="Debes abrir caja primero.")
    
    tx = TransaccionDB(
        caja_id=caja.id,
        monto=req.monto,
        concepto=req.concepto,
        metodo=req.metodo,
        alumno_id=req.alumno_id,
        fecha_hora=ahora_lima().strftime("%H:%M:%S")
    )
    db.add(tx)
    caja.recaudado_sistema += req.monto
    db.commit()
    db.refresh(tx)
    return tx

@router.post("/caja/cerrar")
async def cerrar_caja(req: CierreCajaReq, db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["SECRETARIO"]))):
    hoy = ahora_lima().strftime("%Y-%m-%d")
    caja = db.query(CajaDiariaDB).filter(CajaDiariaDB.fecha == hoy, CajaDiariaDB.estado == "Abierta").first()
    if not caja:
        raise HTTPException(status_code=400, detail="No hay caja abierta para cerrar.")
    
    txs = db.query(TransaccionDB).filter(TransaccionDB.caja_id == caja.id).all()
    
    # Separar Efectivo de Digital
    recaudado_efectivo = sum(t.monto for t in txs if t.metodo == "Efectivo")
    recaudado_digital = sum(t.monto for t in txs if t.metodo != "Efectivo")
    
    caja.monto_cierre = req.monto_cierre
    # Solo el EFECTIVO debe estar físicamente en el cajón
    esperado_efectivo = caja.monto_apertura + recaudado_efectivo
    caja.diferencia = req.monto_cierre - esperado_efectivo
    caja.estado = "Cerrada"
    
    # AI Auditor - Detect anomalies
    lista_tx = ", ".join([f"{t.concepto}: S/ {t.monto} ({t.metodo})" for t in txs])
    
    prompt = f"""
    Eres un auditor financiero experto de un colegio. El Secretario acaba de cerrar la caja.
    Datos del día:
    Apertura (Suelto inicial): S/ {caja.monto_apertura}
    Ingresos en Efectivo: S/ {recaudado_efectivo}
    Ingresos Digitales (Bancos/Yape): S/ {recaudado_digital}
    Efectivo Total Esperado en Cajón: S/ {esperado_efectivo}
    Dinero Físico/Real Contado por el Secretario: S/ {caja.monto_cierre}
    Diferencia en Efectivo (Sobrante/Faltante): S/ {caja.diferencia}
    Transacciones: {lista_tx}
    
    Evalúa la cuadratura física (Efectivo Esperado vs Real Contado).
    Los ingresos digitales (S/ {recaudado_digital}) NO están en el cajón, no deben afectar la diferencia física.
    Si hay un faltante de efectivo, levanta alerta severa. Si cuadra, felicita.
    Genera un breve reporte de 2 a 3 líneas.
    """
    
    try:
        llm = ChatGroq(tags=["secretaria"], metadata={"agent_name": "secretaria"}, temperature=0, model_name="llama-3.1-8b-instant", groq_api_key=os.getenv("GROQ_API_KEY"))
        caja.reporte_ia = llm.invoke(prompt).content
    except Exception as e:
        caja.reporte_ia = f"Error generando reporte de IA: {e}"
        
    db.commit()
    return {"message": "Caja cerrada.", "reporte": caja.reporte_ia, "diferencia": caja.diferencia}

@router.get("/admin/auditoria_cajas")
async def auditoria_cajas(db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["ADMIN"]))):
    cajas = db.query(CajaDiariaDB).order_by(CajaDiariaDB.id.desc()).all()
    return cajas

class CobranzaEmailReq(BaseModel):
    alumno_id: int
    meses_deuda: int

@router.post("/cobranza/email_empatico")
async def generar_email_cobranza(req: CobranzaEmailReq, db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["SECRETARIO"]))):
    alumno = db.query(AlumnoDB).filter(AlumnoDB.id == req.alumno_id).first()
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
        
    prompt = f"""
    Redacta un correo electrónico (Asunto y Cuerpo) extremadamente cortés, profesional y empático.
    Dirigido al apoderado del alumno {alumno.nombres}.
    Motivo: Recordatorio de pago de pensión atrasada (Deuda: {req.meses_deuda} meses).
    Reglas:
    - No uses un tono amenazante ni legal.
    - Ofrécele facilidades de pago (ej. acercarse a Secretaría para fraccionar).
    - El colegio se llama "I.E.P. José María Arguedas".
    - El remitente es "Secretaría y Caja".
    Mantenlo corto, directo, pero humano.
    """
    try:
        llm = ChatGroq(tags=["secretaria"], metadata={"agent_name": "secretaria"}, temperature=0.3, model_name="llama-3.1-8b-instant", groq_api_key=os.getenv("GROQ_API_KEY"))
        correo = llm.invoke(prompt).content
        return {"email_draft": correo}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/caja/leer_voucher")
async def leer_voucher_ocr(file: UploadFile = File(...), current_user: TokenData = Depends(require_role(["SECRETARIO"]))):
    try:
        image_bytes = await file.read()
        try:
            image = Image.open(io.BytesIO(image_bytes))
        except Exception as img_err:
            raise HTTPException(status_code=400, detail=f"Imagen inválida o corrupta: {str(img_err)}")
        
        try:
            import sys
            if sys.platform.startswith('win'):
                pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
            ocr_text = pytesseract.image_to_string(image, lang='spa')
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error en OCR: {str(e)}")
            
        prompt = f"""
        Eres un asistente de tesorería experto en extraer información de comprobantes de pago (Vouchers de Yape, BCP, Plin, BBVA).
        Extrae del siguiente texto obtenido por OCR:
        1. Monto Pagado (sólo el número)
        2. Fecha
        3. Número de Operación o Código
        
        Si no encuentras algo, pon null.
        
        Texto OCR:
        {ocr_text}
        
        Responde SOLO en este formato JSON exacto:
        {{
            "monto": 150.00,
            "fecha": "12/05/2023",
            "nro_operacion": "12345678"
        }}
        """
        
        llm = ChatGroq(tags=["secretaria"], metadata={"agent_name": "secretaria"}, temperature=0, model_name="llama-3.1-8b-instant", groq_api_key=os.getenv("GROQ_API_KEY"))
        res = llm.invoke(prompt).content
        
        import json
        if "```json" in res:
            res = res.split("```json")[1].split("```")[0].strip()
        elif "```" in res:
            res = res.split("```")[1].strip()
            
        return json.loads(res)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error leyendo voucher: {e}")


# ======================================================================
# Gestión de Admisiones (Secretaría)
# ======================================================================

@router.get("/admisiones")
async def listar_admisiones(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["SECRETARIO", "ADMIN"]))
):
    admisiones = db.query(AdmisionDB).order_by(AdmisionDB.fecha_registro.desc()).all()
    return [{
        "id": a.id, 
        "codigo_est": a.codigo_est, 
        "nombres": f"{a.nombres} {a.apellidos}", 
        "nivel": a.nivel, 
        "promedio": a.promedio, 
        "conducta": a.conducta, 
        "estado_proceso": a.estado_proceso
    } for a in admisiones]

@router.post("/admisiones/{id_admision}/estado")
async def cambiar_estado_admision(
    id_admision: int,
    estado: str, # "Admitido (Falta Pago)" o "Rechazado"
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_role(["SECRETARIO", "ADMIN"]))
):
    admision = db.query(AdmisionDB).filter(AdmisionDB.id == id_admision).first()
    if not admision:
        raise HTTPException(status_code=404, detail="Admisión no encontrada")
    
    admision.estado_proceso = estado
    db.commit()

    # Sincronizar con la memoria JSON
    mem_state = await school_db.get_state()
    if admision.codigo_est in mem_state.get("enrolled_students", {}):
        mem_state["enrolled_students"][admision.codigo_est]["estado_proceso"] = estado
        await school_db.set_state(mem_state)

    return {"message": f"Estado de admisión cambiado a {estado} exitosamente."}





@router.get("/alumnos/recuperacion")
async def obtener_alumnos_recuperacion(db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["SECRETARIO", "ADMIN"]))):
    anio_activo = db.query(AnioEscolarDB).filter(AnioEscolarDB.estado == "ACTIVO").first()
    if not anio_activo:
        raise HTTPException(status_code=400, detail="No hay año escolar activo.")
        
    matriculas = db.query(MatriculaDB).filter(MatriculaDB.anio_escolar_id == anio_activo.id, MatriculaDB.estado_matricula == "PENDIENTE_RECUPERACION").all()
    resultado = []
    for mat in matriculas:
        alumno = db.query(AlumnoDB).filter(AlumnoDB.id == mat.alumno_id).first()
        if not alumno: continue
        
        # Encontrar los cursos a recuperar (en la matricula del año a recuperar, es decir, la matricula actual en estado pendiente_recuperacion)
        # La forma segura es buscar los CursoRecuperacionDB pendientes asociados a la matricula del año pasado
        # Ah, espera, CursoRecuperacionDB se inserta en cierre_escolar con matricula_id = matricula CERRADA del año anterior.
        # Así que buscamos las matrículas del alumno y todos los CursoRecuperacionDB pendientes.
        cursos_rec = db.query(CursoRecuperacionDB).join(MatriculaDB).filter(
            MatriculaDB.alumno_id == alumno.id,
            CursoRecuperacionDB.estado == "PENDIENTE"
        ).all()
        
        cursos_detalle = []
        for cr in cursos_rec:
            cinfo = db.query(CursoDB).filter(CursoDB.id == cr.curso_id).first()
            if cinfo:
                cursos_detalle.append({
                    "curso_recuperacion_id": cr.id,
                    "nombre": cinfo.nombre
                })
                
        if len(cursos_detalle) > 0:
            resultado.append({
                "alumno_id": alumno.id,
                "alumno_nombres": f"{alumno.nombres}",
                "grado": mat.grado,
                "nivel": mat.nivel,
                "cursos_pendientes": cursos_detalle
            })
    return resultado

@router.get("/matriculas/pendientes")
async def obtener_matricula_pendiente(dni: str, db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["SECRETARIO", "ADMIN"]))):
    alumno = db.query(AlumnoDB).filter(AlumnoDB.dni == dni).first()
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado.")
        
    anio_activo = db.query(AnioEscolarDB).filter(AnioEscolarDB.estado == "ACTIVO").first()
    if not anio_activo:
        raise HTTPException(status_code=400, detail="No hay año escolar activo.")
        
    matricula = db.query(MatriculaDB).filter(MatriculaDB.alumno_id == alumno.id, MatriculaDB.anio_escolar_id == anio_activo.id).first()
    
    if not matricula or matricula.estado_matricula != "PENDIENTE_PAGO":
        raise HTTPException(status_code=400, detail="El alumno no tiene matrícula pendiente de pago para el año activo.")
        
    return {
        "id": matricula.id,
        "alumno_id": alumno.id,
        "alumno_nombre": f"{alumno.nombres}",
        "grado": matricula.grado,
        "nivel": matricula.nivel,
        "estado_matricula": matricula.estado_matricula,
        "monto_total": 350.0
    }

class MatricularSecretariaReq(BaseModel):
    alumno_id: int
    metodo_pago: str
    monto_pago: float

@router.post("/matricular")
async def secretaria_matricular(req: MatricularSecretariaReq, db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["SECRETARIO", "ADMIN"]))):
    caja = db.query(CajaDiariaDB).filter(CajaDiariaDB.fecha == ahora_lima().strftime("%Y-%m-%d"), CajaDiariaDB.estado == "ABIERTA").first()
    if not caja:
        raise HTTPException(status_code=400, detail="Debe abrir la caja diaria de hoy primero.")
        
    anio_activo = db.query(AnioEscolarDB).filter(AnioEscolarDB.estado == "ACTIVO").first()
    if not anio_activo:
        raise HTTPException(status_code=400, detail="No hay año escolar activo.")
        
    matricula = db.query(MatriculaDB).filter(MatriculaDB.alumno_id == req.alumno_id, MatriculaDB.anio_escolar_id == anio_activo.id).first()
    if not matricula or matricula.estado_matricula != "PENDIENTE_PAGO":
        raise HTTPException(status_code=400, detail="La matrícula no está pendiente de pago.")
        
    alumno = db.query(AlumnoDB).filter(AlumnoDB.id == req.alumno_id).first()
    
    try:
        matricula.estado_matricula = "CONFIRMADA"
        
        # Registrar Transaccion
        transaccion = TransaccionDB(
            caja_id=caja.id,
            monto=req.monto_pago,
            concepto=f"Pago Matrícula {anio_activo.anio} - {alumno.nombres}",
            metodo=req.metodo_pago,
            alumno_id=req.alumno_id,
            fecha_hora=ahora_lima().strftime("%Y-%m-%d %H:%M:%S"),
            aprobado=True
        )
        db.add(transaccion)
        
        db.commit()
        return {"message": "Matrícula confirmada y pago registrado exitosamente."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


class RecuperacionResult(BaseModel):
    curso_recuperacion_id: int
    nota: str # "A", "15", etc.
    aprobado: bool
    metodo_pago: str # "Efectivo", "Yape", "Transferencia"
    monto_pago: float

@router.post("/recuperacion/registrar")
async def registrar_recuperacion(req: RecuperacionResult, db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["SECRETARIO", "ADMIN"]))):
    # Validar caja abierta
    caja = db.query(CajaDiariaDB).filter(CajaDiariaDB.fecha == ahora_lima().strftime("%Y-%m-%d"), CajaDiariaDB.estado == "ABIERTA").first()
    if not caja:
        raise HTTPException(status_code=400, detail="Debe abrir la caja diaria de hoy primero.")
        
    curso_rec = db.query(CursoRecuperacionDB).filter(CursoRecuperacionDB.id == req.curso_recuperacion_id).first()
    if not curso_rec:
        raise HTTPException(status_code=404, detail="Registro de recuperación no encontrado.")
        
    if curso_rec.estado != "PENDIENTE":
        raise HTTPException(status_code=400, detail=f"El curso ya fue procesado con estado {curso_rec.estado}.")

    matricula_cerrada = db.query(MatriculaDB).filter(MatriculaDB.id == curso_rec.matricula_id).first()
    curso_info = db.query(CursoDB).filter(CursoDB.id == curso_rec.curso_id).first()
    
    try:
        # 1. Actualizar estado del curso de recuperación
        curso_rec.nota_recuperacion = req.nota
        curso_rec.estado = "APROBADO" if req.aprobado else "JALADO"
        
        # 2. Registrar Transacción
        transaccion = TransaccionDB(
            caja_id=caja.id,
            monto=req.monto_pago,
            concepto=f"Recuperación - {curso_info.nombre} ({matricula_cerrada.nivel} {matricula_cerrada.grado})",
            metodo=req.metodo_pago,
            alumno_id=matricula_cerrada.alumno_id,
            fecha_hora=ahora_lima().strftime("%Y-%m-%d %H:%M:%S"),
            aprobado=True
        )
        db.add(transaccion)
        db.flush()
        
        # 3. Evaluar si ya terminó todos sus cursos de recuperación
        todos_cursos = db.query(CursoRecuperacionDB).filter(CursoRecuperacionDB.matricula_id == matricula_cerrada.id).all()
        
        pendientes = [c for c in todos_cursos if c.estado == "PENDIENTE"]
        
        if len(pendientes) == 0:
            # Ya terminó todas sus recuperaciones
            jalados = [c for c in todos_cursos if c.estado == "JALADO"]
            
            anio_activo = db.query(AnioEscolarDB).filter(AnioEscolarDB.estado == "ACTIVO").first()
            matricula_nueva = db.query(MatriculaDB).filter(MatriculaDB.alumno_id == matricula_cerrada.alumno_id, MatriculaDB.anio_escolar_id == anio_activo.id).first()
            alumno = db.query(AlumnoDB).filter(AlumnoDB.id == matricula_cerrada.alumno_id).first()
            
            if len(jalados) > 0:
                # JALÓ AL MENOS UNO -> REVIERTE A REPITENTE (Mismo grado que el año cerrado)
                matricula_nueva.estado_matricula = "PENDIENTE_PAGO"
                matricula_nueva.nivel = matricula_cerrada.nivel # REVERSIÓN DE GRADO/NIVEL (Cubre caso 6to Primaria o 5to Secu)
                matricula_nueva.grado = matricula_cerrada.grado
            else:
                # APROBÓ TODOS
                if matricula_cerrada.nivel == "SECUNDARIA" and matricula_cerrada.grado == 5:
                    # CASO 5TO SECUNDARIA RECUPERA Y APRUEBA
                    alumno.estado = "EGRESADO"
                    if alumno.apoderado_id:
                        apoderado = db.query(UserDB).filter(UserDB.id == alumno.apoderado_id).first()
                        if apoderado:
                            apoderado.is_active = False
                            apoderado.motivo_inactivo = "EGRESADO"
                            
                    ruta_pdf = generar_certificado_pdf(db, matricula_cerrada, anio_activo, "CONCLUSION_SECUNDARIA")
                    db.add(CertificadoDB(
                        alumno_id=alumno.id, 
                        anio_escolar_id=matricula_cerrada.anio_escolar_id, 
                        tipo="CONCLUSION_SECUNDARIA",
                        ruta_archivo=ruta_pdf,
                        fecha_generacion=ahora_lima().strftime("%Y-%m-%d")
                    ))
                    
                    # Eliminar la matricula nueva (porque ya egresó y no sigue estudiando)
                    if matricula_nueva:
                        db.delete(matricula_nueva)
                else:
                    # CASO REGULAR (Sigue al siguiente grado de forma normal)
                    matricula_nueva.estado_matricula = "PENDIENTE_PAGO"

        db.commit()
        return {"message": "Recuperación y pago registrados exitosamente."}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error registrando recuperación: {str(e)}")
from pydantic import BaseModel
class MatriculaDirectaRequest(BaseModel):
    nombres: str
    apellidos: str
    dni: str
    nivel: str
    grado: int
    seccion: str = "A"
    ap_nombre: str
    ap_dni: str
    ap_correo: str
    ap_telefono: str
    metodo: str
    monto: float
    efectivoRecibido: str = ""

@router.post("/matricula_directa")
async def matricula_directa(req: MatriculaDirectaRequest, db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["SECRETARIO", "ADMIN"]))):
    try:
        hoy = ahora_lima().strftime("%Y-%m-%d")
        caja = db.query(CajaDiariaDB).filter(CajaDiariaDB.fecha == hoy, CajaDiariaDB.estado == "Abierta").first()
        if not caja:
            raise HTTPException(status_code=400, detail="Debes abrir caja primero antes de registrar un cobro.")

        # Registrar ingreso en caja
        nueva_tx = TransaccionDB(
            caja_id=caja.id,
            monto=req.monto,
            concepto=f"Matrícula Directa - {req.nombres} {req.apellidos}",
            metodo=req.metodo
        )
        db.add(nueva_tx)

        # Crear alumno
        import random
        codigo_est = f"EST-{random.randint(1000, 9999)}-DIR"
        nuevo_alumno = AlumnoDB(
            codigo_est=codigo_est,
            dni=req.dni,
            nombres=req.nombres,
            apellidos=req.apellidos,
            nivel=req.nivel,
            grado=req.grado,
            seccion=req.seccion,
            estado="Matriculado"
        )
        db.add(nuevo_alumno)
        db.flush()

        # Crear admision para registro
        nueva_admision = AdmisionDB(
            codigo_est=codigo_est,
            dni=req.dni,
            nombres=req.nombres,
            apellidos=req.apellidos,
            nivel=req.nivel,
            grado=req.grado,
            ap_nombre=req.ap_nombre,
            ap_correo=req.ap_correo,
            ap_telefono=req.ap_telefono,
            estado_proceso="Matriculado"
        )
        db.add(nueva_admision)

        db.commit()
        return {"message": "Matrícula directa registrada exitosamente"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

class CobroRequest(BaseModel):
    monto: float
    metodo: str

@router.post("/admisiones/{id}/cobrar")
async def cobrar_admision(id: int, req: CobroRequest, db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["SECRETARIO", "ADMIN"]))):
    try:
        admision = db.query(AdmisionDB).filter(AdmisionDB.id == id).first()
        if not admision:
            raise HTTPException(status_code=404, detail="Admisión no encontrada")

        if admision.estado_proceso == "Matriculado":
            raise HTTPException(status_code=400, detail="El alumno ya está matriculado")

        hoy = ahora_lima().strftime("%Y-%m-%d")
        caja = db.query(CajaDiariaDB).filter(CajaDiariaDB.fecha == hoy, CajaDiariaDB.estado == "Abierta").first()
        if not caja:
            raise HTTPException(status_code=400, detail="Debes abrir caja primero antes de registrar un cobro.")

        # Registrar ingreso en caja
        nueva_tx = TransaccionDB(
            caja_id=caja.id,
            monto=req.monto,
            concepto=f"Cobro Admisión/Matrícula - {admision.nombres} {admision.apellidos}",
            metodo=req.metodo,
            alumno_id=None
        )
        db.add(nueva_tx)

        admision.estado_proceso = "Matriculado"
        
        # Crear en AlumnoDB
        alumno_existente = db.query(AlumnoDB).filter(AlumnoDB.codigo_est == admision.codigo_est).first()
        if not alumno_existente:
            nuevo_alumno = AlumnoDB(
                codigo_est=admision.codigo_est,
                dni=admision.dni,
                nombres=admision.nombres,
                apellidos=admision.apellidos,
                nivel=admision.nivel,
                grado=admision.grado,
                seccion="A",
                estado="Matriculado"
            )
            db.add(nuevo_alumno)
        else:
            alumno_existente.estado = "Matriculado"

        db.commit()
        return {"message": "Cobro registrado exitosamente, alumno matriculado"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
