import os
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from models.database import get_db, CajaDiariaDB, TransaccionDB, AlumnoDB, AdmisionDB
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
    hoy = datetime.now().strftime("%Y-%m-%d")
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
    hoy = datetime.now().strftime("%Y-%m-%d")
    caja = db.query(CajaDiariaDB).filter(CajaDiariaDB.fecha == hoy, CajaDiariaDB.estado == "Abierta").first()
    if not caja:
        return {"estado": "Cerrada", "caja": None, "transacciones": []}
    
    txs = db.query(TransaccionDB).filter(TransaccionDB.caja_id == caja.id).all()
    return {"estado": "Abierta", "caja": caja, "transacciones": txs}

@router.post("/caja/transaccion")
async def registrar_transaccion(req: TransaccionReq, db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["SECRETARIO"]))):
    hoy = datetime.now().strftime("%Y-%m-%d")
    caja = db.query(CajaDiariaDB).filter(CajaDiariaDB.fecha == hoy, CajaDiariaDB.estado == "Abierta").first()
    if not caja:
        raise HTTPException(status_code=400, detail="Debes abrir caja primero.")
    
    tx = TransaccionDB(
        caja_id=caja.id,
        monto=req.monto,
        concepto=req.concepto,
        metodo=req.metodo,
        alumno_id=req.alumno_id,
        fecha_hora=datetime.now().strftime("%H:%M:%S")
    )
    db.add(tx)
    caja.recaudado_sistema += req.monto
    db.commit()
    db.refresh(tx)
    return tx

@router.post("/caja/cerrar")
async def cerrar_caja(req: CierreCajaReq, db: Session = Depends(get_db), current_user: TokenData = Depends(require_role(["SECRETARIO"]))):
    hoy = datetime.now().strftime("%Y-%m-%d")
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
        "grado": a.grado, 
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
