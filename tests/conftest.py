import pytest

@pytest.fixture(autouse=True)
def disable_ai_tokens(monkeypatch):
    """
    Fixture global: Se ejecuta automáticamente antes de CADA test.
    Sobrescribe las llaves reales de las APIs de IA con valores falsos
    para garantizar que ninguna prueba pueda hacer peticiones reales
    a Groq, OpenAI o LangChain. Si un test intenta usar la IA,
    fallará instantáneamente sin gastar un solo token.
    """
    monkeypatch.setenv("GROQ_API_KEY", "dummy_groq_key_disabled")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy_openai_key_disabled")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "dummy_langchain_key_disabled")
