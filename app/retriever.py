"""
Retriever Module for DarGlobal + Wasalt RAG
Bridges VectorStore with query analysis, metadata filtering,
and context assembly for the LangGraph workflow.
"""

import logging
from typing import List, Dict, Any, Optional

from app.config import settings
from app.vector_store import VectorStore
from app.embeddings import EmbeddingModel

logger = logging.getLogger(__name__)


class RealEstateRetriever:
    """
    Retrieves and ranks relevant property chunks from ChromaDB,
    with support for metadata filtering and multi-query fallbacks.
    """

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        embedder: Optional[EmbeddingModel] = None,
        top_k: int = 5
    ):
        self.top_k = top_k or settings.TOP_K
        self.vector_store = vector_store or VectorStore(
            persist_directory=settings.CHROMA_PERSIST_DIRECTORY,
            collection_name=settings.COLLECTION_NAME
        )
        self.embedder = embedder or EmbeddingModel(
            model_name=settings.EMBEDDING_MODEL_NAME
        )

    def build_where_clause(self, filters: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Construct a valid ChromaDB `where` filter dictionary from extracted filters.
        """
        if not filters:
            return None

        clauses = []

        # Source filter ("darglobal" or "wasalt")
        source = filters.get("source")
        if source and isinstance(source, str) and source.lower() in ("darglobal", "wasalt"):
            clauses.append({"source": source.lower()})

        # Property type filter
        prop_type = filters.get("property_type")
        if prop_type and isinstance(prop_type, str):
            clauses.append({"property_type": prop_type.lower()})

        # City filter
        city = filters.get("city")
        if city and isinstance(city, str):
            clauses.append({"city": city.capitalize()})

        if not clauses:
            return None
        elif len(clauses) == 1:
            return clauses[0]
        else:
            return {"$and": clauses}

    def retrieve(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: Optional[int] = None,
        min_score: float = 0.50
    ) -> List[Dict[str, Any]]:
        """
        Execute vector similarity search.
        Tries filtered search first; if no results are found, relaxes filters.
        Filters out low-confidence matches below min_score threshold.
        """
        k = top_k or self.top_k
        query_embedding = self.embedder.embed_query(query)
        where_clause = self.build_where_clause(filters)

        results = []
        if where_clause:
            try:
                logger.info(f"Searching with Chroma filter: {where_clause}")
                results = self.vector_store.similarity_search(
                    query=query,
                    n_results=k,
                    query_embedding=query_embedding,
                    where=where_clause
                )
            except Exception as e:
                logger.warning(f"Filtered search failed ({e}); falling back to unfiltered search.")

        # If filtered search yielded nothing or had no filters, run standard search
        if not results:
            results = self.vector_store.similarity_search(
                query=query,
                n_results=k,
                query_embedding=query_embedding
            )

        # Apply confidence threshold filtering
        if min_score is not None and results:
            filtered_by_score = [
                doc for doc in results
                if doc.get("score") is None or doc.get("score") >= min_score
            ]
            if filtered_by_score:
                results = filtered_by_score
            else:
                results = []

        return results

    @staticmethod
    def format_context(documents: List[Dict[str, Any]]) -> str:
        """
        Format retrieved document dictionaries into a clean text block for the LLM.
        """
        if not documents:
            return "No matching records found in the database."

        formatted_chunks = []
        for idx, doc in enumerate(documents, 1):
            meta = doc.get("metadata", {})
            title = meta.get("title") or meta.get("project_name") or f"Property Record {idx}"
            source = meta.get("source", "Unknown").capitalize()
            url = meta.get("url", "")
            city = meta.get("city") or meta.get("location", "")
            prop_type = meta.get("property_type", "")
            price = meta.get("price", "")
            currency = meta.get("currency", "")

            header_parts = [f"[{idx}] {title} ({source})"]
            if city:
                header_parts.append(f"Location: {city}")
            if prop_type:
                header_parts.append(f"Type: {prop_type}")
            if price:
                header_parts.append(f"Price: {price} {currency}".strip())
            if url:
                header_parts.append(f"URL: {url}")

            header_str = " | ".join(header_parts)
            text_body = doc.get("text", "").strip()

            formatted_chunks.append(f"{header_str}\n{text_body}")

        return "\n\n---\n\n".join(formatted_chunks)

    @staticmethod
    def extract_sources(documents: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """
        Extract unique verified source references with titles and URLs.
        """
        seen_urls = set()
        sources = []

        for doc in documents:
            meta = doc.get("metadata", {})
            url = meta.get("url", "").strip()
            title = meta.get("title") or meta.get("project_name") or "Listing Details"
            source = meta.get("source", "Real Estate Portal")

            if url and url not in seen_urls:
                seen_urls.add(url)
                sources.append({
                    "title": title,
                    "url": url,
                    "source": source
                })
            elif not url:
                # Add source by title if no URL exists
                sources.append({
                    "title": title,
                    "url": "",
                    "source": source
                })

        return sources
