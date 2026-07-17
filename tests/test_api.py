import pytest
from fastapi.testclient import TestClient
from main import app
from models.database import init_db

# Inicializar DB de prueba (en memoria si se configura así)
init_db()
client = TestClient(app)

def test_get_config():
    """Prueba básica de un endpoint sin autenticación compleja"""
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "primaria" in data
    assert "secundaria" in data
