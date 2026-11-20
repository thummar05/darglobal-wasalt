"""
Embedding Module
Provides embedding models for multilingual real estate text.
Supports BAAI/bge-m3, intfloat/multilingual-e5-small,
and Chroma's built-in ONNX embedding function as a lightweight fallback.
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """
    Multilingual embedding generator for real estate chunks and queries.
    Uses Chroma's local ONNX embedding runtime (all-MiniLM-L6-v2, 384d) by default,
    with SentenceTransformer fallback or override.
    """
    def __init__(self, model_name: str = "all-MiniLM-L6-v2", use_fallback_if_needed: bool = True):
        self.model_name = model_name
        self._model = None
        self._is_chroma_fn = False
        
        # Default to Chroma's local ONNX MiniLM runtime for zero-download instant execution
        if model_name in ("all-MiniLM-L6-v2", "default", "onnx"):
            try:
                import chromadb.utils.embedding_functions as ef
                self._model = ef.DefaultEmbeddingFunction()
                self._is_chroma_fn = True
                logger.info("✓ Using Chroma DefaultEmbeddingFunction (ONNX all-MiniLM-L6-v2, 384d)")
                return
            except Exception as chroma_err:
                logger.warning(f"Could not load Chroma DefaultEmbeddingFunction: {chroma_err}")

        # Try loading sentence-transformers if a custom model was specified
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading SentenceTransformer: {model_name}...")
            self._model = SentenceTransformer(model_name)
            logger.info(f"✓ Loaded SentenceTransformer: {model_name}")
        except Exception as e:
            if not use_fallback_if_needed:
                raise e
            logger.warning(
                f"Could not load SentenceTransformer ({e}). Falling back to Chroma's ONNX embedding function..."
            )
            import chromadb.utils.embedding_functions as ef
            self._model = ef.DefaultEmbeddingFunction()
            self._is_chroma_fn = True
            logger.info("✓ Using Chroma DefaultEmbeddingFunction (ONNX MiniLM)")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of strings."""
        if not texts:
            return []
            
        if self._is_chroma_fn:
            embeddings = self._model(texts)
            # Ensure float lists
            return [list(map(float, emb)) for emb in embeddings]
        else:
            embeddings = self._model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
            return [emb.tolist() if hasattr(emb, "tolist") else list(emb) for emb in embeddings]

    def embed_query(self, query: str) -> List[float]:
        """Generate embedding for a single search query."""
        if self._is_chroma_fn:
            res = self._model([query])
            return list(map(float, res[0]))
        else:
            emb = self._model.encode([query], show_progress_bar=False, normalize_embeddings=True)[0]
            return emb.tolist() if hasattr(emb, "tolist") else list(emb)

    def embed_chunks(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Embed a list of chunk dicts in place.
        Adds 'embedding' key with list of floats to each chunk dict.
        """
        if not chunks:
            return []
            
        texts = [chunk.get("text", "") for chunk in chunks]
        embeddings = self.embed_documents(texts)
        
        for chunk, emb in zip(chunks, embeddings):
            chunk["embedding"] = emb
            
        return chunks
