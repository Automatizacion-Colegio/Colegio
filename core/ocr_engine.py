"""
core/ocr_engine.py — Motor de OCR local con pytesseract.
Extrae texto de imágenes de documentos médicos/justificativos subidos por los apoderados.

Dependencias ya presentes:
  - pytesseract==0.3.10  (requirements.txt)
  - Pillow==10.2.0        (requirements.txt)
  - tesseract-ocr + tesseract-ocr-spa  (Dockerfile, apt)
"""
import io
import sys
import asyncio

import pytesseract
from PIL import Image

# Ruta al binario de Tesseract en Windows (local dev).
# En producción (Docker Linux), el binario está en el PATH del sistema.
if sys.platform.startswith("win"):
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


async def extract_text_from_image(image_bytes: bytes) -> str:
    """
    Extrae texto de una imagen usando pytesseract (OCR local).

    Soporta JPEG, PNG y formatos comunes de documentos médicos escaneados.
    Optimizado para documentos en español (idioma 'spa' instalado en la imagen Docker).

    Args:
        image_bytes: Contenido binario de la imagen subida via UploadFile.

    Returns:
        Texto extraído como string limpio. Puede estar vacío si la imagen
        es ilegible o no contiene texto reconocible.

    Raises:
        ValueError: Si los bytes no corresponden a una imagen válida.
        pytesseract.TesseractError: Si el binario de Tesseract no está disponible.
    """
    def _run_ocr(data: bytes) -> str:
        try:
            image = Image.open(io.BytesIO(data))
            # lang='spa' para documentos médicos peruanos en español
            return pytesseract.image_to_string(image, lang="spa")
        except Exception as exc:
            raise ValueError(f"No se pudo procesar la imagen para OCR: {exc}") from exc

    # Ejecutar en thread pool para no bloquear el event loop de FastAPI.
    # pytesseract es síncrono y CPU-bound, por eso va en executor.
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _run_ocr, image_bytes)
    return text.strip()
