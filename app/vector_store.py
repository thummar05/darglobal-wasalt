"""
ChromaDB Vector Store Module
Provides persistence, indexing, metadata sanitization,
and similarity search for real estate property documents.
"""

import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)


def sanitize_chroma_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure all metadata values conform to Chroma requirements:
    Only primitive types (str, int, float, bool) allowed.
    None or complex types (dicts/lists) are converted or sanitized.
    """
    clean_meta = {}
    for k, v in metadata.items():
        if not k:
            continue
        if v is None:
            continue
        elif isinstance(v, (str, int, float, bool)):
            clean_meta[k] = v
        elif isinstance(v, (dict, list)):
            clean_meta[k] = json.dumps(v, ensure_ascii=False)
        else:
            clean_meta[k] = str(v)
    return clean_meta


class VectorStore:
    """
    Persistent ChromaDB vector store interface.
    """
    def __init__(
        self,
        persist_directory: str = "./data/chroma",
        collection_name: str = "property_documents"
    ):
        self.persist_directory = Path(persist_directory).resolve()
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        
        logger.info(f"Connecting to ChromaDB at: {self.persist_directory}")
        self.client = chromadb.PersistentClient(
            path=str(self.persist_directory),
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        logger.info(f"✓ Connected to collection '{collection_name}', existing items: {self.count_documents()}")

    def count_documents(self) -> int:
        """Return total document count in collection."""
        try:
            return self.collection.count()
        except Exception as e:
            logger.error(f"Error counting documents: {e}")
            return 0

    def delete_all(self):
        """Reset/clear all items in collection."""
        try:
            self.client.delete_collection(name=self.collection_name)
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"✓ Cleared collection '{self.collection_name}'")
        except Exception as e:
            logger.warning(f"Failed to reset collection: {e}")

    def get_collection_info(self) -> Dict[str, Any]:
        """Return collection metadata and statistics."""
        return {
            "name": self.collection_name,
            "count": self.count_documents(),
            "persist_directory": str(self.persist_directory),
            "metadata": self.collection.metadata
        }

    def add_documents(self, documents: List[Dict[str, Any]], batch_size: int = 500) -> int:
        """
        Add a batch of embedded document chunks into ChromaDB.
        Each document dict should contain:
        - text: str (document content)
        - metadata: dict (document metadata)
        - chunk_id: str (unique identifier)
        - embedding: list of float (optional, if precomputed)
        """
        if not documents:
            return 0

        total_added = 0
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            
            ids = []
            texts = []
            metadatas = []
            embeddings = []
            has_embeddings = False
            
            for idx, doc in enumerate(batch):
                doc_id = doc.get("chunk_id") or doc.get("id") or f"doc_{total_added + idx}"
                ids.append(str(doc_id))
                
                texts.append(doc.get("text", ""))
                
                raw_meta = doc.get("metadata", {})
                metadatas.append(sanitize_chroma_metadata(raw_meta))
                
                if "embedding" in doc and doc["embedding"] is not None:
                    embeddings.append(doc["embedding"])
                    has_embeddings = True

            kwargs = {
                "ids": ids,
                "documents": texts,
                "metadatas": metadatas
            }
            if has_embeddings and len(embeddings) == len(ids):
                kwargs["embeddings"] = embeddings

            self.collection.add(**kwargs)
            total_added += len(batch)

        return total_added

    def similarity_search(
        self,
        query: str,
        n_results: int = 5,
        query_embedding: Optional[List[float]] = None,
        where: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform vector similarity search.
        Can supply either query_embedding or rely on query string if collection has embedding function.
        """
        query_kwargs = {"n_results": min(n_results, max(1, self.count_documents()))}
        if where:
            query_kwargs["where"] = where
            
        if query_embedding is not None:
            query_kwargs["query_embeddings"] = [query_embedding]
        else:
            query_kwargs["query_texts"] = [query]

        results = self.collection.query(**query_kwargs)
        
        formatted = []
        if results and "documents" in results and results["documents"]:
            docs = results["documents"][0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]
            ids = results.get("ids", [[]])[0]
            
            for i in range(len(docs)):
                formatted.append({
                    "id": ids[i] if i < len(ids) else None,
                    "text": docs[i],
                    "metadata": metas[i] if i < len(metas) else {},
                    "score": 1.0 - dists[i] if (dists and i < len(dists)) else None
                })
                
        return formatted
