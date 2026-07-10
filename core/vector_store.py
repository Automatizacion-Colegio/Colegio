"""
Memoria Semántica Vectorial con LangChain y ChromaDB.
Provee Retrievers avanzados para LangGraph y agentes.
"""
import os
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from langchain_postgres.vectorstores import PGVector
from langchain_huggingface import HuggingFaceEmbeddings
from models.database import SQLALCHEMY_DATABASE_URL

# Modelo para compatibilidad hacia atrás
class SemanticResult(BaseModel):
    id: str
    content: str
    metadata: Dict[str, Any]
    distance: float

class VectorStore:
    def __init__(self):
        # Embeddings de alto rendimiento (multilingüe) para RAG robusto
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        
        # Wrappers de LangChain para colecciones
        self.historiales_store = PGVector(
            embeddings=self.embeddings,
            collection_name="historiales_psicologia",
            connection=SQLALCHEMY_DATABASE_URL,
            use_jsonb=True
        )
        
        self.curriculos_store = PGVector(
            embeddings=self.embeddings,
            collection_name="curriculos",
            connection=SQLALCHEMY_DATABASE_URL,
            use_jsonb=True
        )

    def upsert_record(self, collection_name: str, doc_id: str, content: str, metadata: dict = None):
        """Inserta o actualiza un documento."""
        metadata = metadata or {}
        store = self.historiales_store if collection_name == "historiales_psicologia" else self.curriculos_store
        store.add_texts(texts=[content], metadatas=[metadata], ids=[doc_id])

    def get_retriever(self, collection_name: str, search_type: str = "mmr", k: int = 3):
        """
        Retorna un retriever avanzado (p. ej. MMR - Maximal Marginal Relevance)
        listo para conectarse directo a las cadenas LangChain/LangGraph.
        """
        store = self.historiales_store if collection_name == "historiales_psicologia" else self.curriculos_store
        return store.as_retriever(search_type=search_type, search_kwargs={"k": k})

    def semantic_search(self, collection_name: str, query: str, n_results: int = 2) -> List[SemanticResult]:
        """Busca documentos por similitud semántica (Compatibilidad Legacy)."""
        store = self.historiales_store if collection_name == "historiales_psicologia" else self.curriculos_store
        
        # Búsqueda con puntuación de relevancia en LangChain
        docs_with_scores = store.similarity_search_with_score(query, k=n_results)
        
        semantic_results = []
        for doc, score in docs_with_scores:
            # LangChain Chroma devuelve score como distancia L2 o similar, dependiente del espacio
            semantic_results.append(SemanticResult(
                id=doc.metadata.get("id", "doc"), # El id real a veces no se retorna en LangChain Docs por defecto, pero se guarda
                content=doc.page_content,
                metadata=doc.metadata,
                distance=score
            ))
            
        return semantic_results

# Instancia singleton para uso global
vector_store = VectorStore()
