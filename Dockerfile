# Usamos una imagen de Python ligera
FROM python:3.11-slim

# Evitar que Python escriba archivos .pyc y forzar el volcado de stdout (bueno para los logs en Google Cloud)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema necesarias para compilar paquetes y OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    git \
    tesseract-ocr \
    tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

# Copiar el archivo de requisitos y las dependencias
COPY requirements.txt .

# Instalar las librerías
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Pre-descargar el modelo de HuggingFace en la imagen para evitar Cold Starts eternos en Cloud Run
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

# Copiar todo el código del backend al contenedor
COPY . .

# Cloud Run automáticamente inyecta la variable de entorno $PORT (usualmente 8080)
# Así que usamos uvicorn escuchando en 0.0.0.0 y ese puerto.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
