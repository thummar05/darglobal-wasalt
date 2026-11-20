"""
Data Ingestion Pipeline - Complete RAG data processing

This script processes scraped property data and loads it into the vector store:
1. Load raw JSON files from data/raw/
2. Clean and prepare text
3. Chunk into manageable pieces
4. Generate embeddings
5. Store in ChromaDB vector database

Usage:
    python ingest.py                    # Process all data
    python ingest.py --source darglobal # Process only DarGlobal
    python ingest.py --source wasalt    # Process only Wasalt
    python ingest.py --reset            # Reset database before ingestion
"""

import json
import argparse
from pathlib import Path
from typing import List, Dict, Any
import logging
from tqdm import tqdm

from app import chunking
from app.embeddings import EmbeddingModel
from app.vector_store import VectorStore

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DataIngestionPipeline:
    """Complete pipeline for ingesting scraped data into vector store"""
    
    def __init__(
        self,
        raw_data_dir: str = "./data/raw",
        vector_store_dir: str = "./data/chroma",
        chunk_size: int = 600,
        chunk_overlap: int = 100
    ):
        """
        Initialize the ingestion pipeline
        
        Args:
            raw_data_dir: Directory containing raw scraped JSON files
            vector_store_dir: Directory for ChromaDB persistence
            chunk_size: Target size for text chunks (tokens)
            chunk_overlap: Overlap between chunks (tokens)
        """
        base_dir = Path(__file__).resolve().parent
        self.raw_data_dir = Path(raw_data_dir) if Path(raw_data_dir).is_absolute() else base_dir / raw_data_dir
        self.vector_store_dir = str(vector_store_dir) if Path(vector_store_dir).is_absolute() else str(base_dir / vector_store_dir)
        
        # Store chunking parameters
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
        # Initialize components
        logger.info("Initializing pipeline components...")
        self.embedder = EmbeddingModel()
        self.vector_store = VectorStore(
            persist_directory=self.vector_store_dir,
            collection_name="property_documents"
        )
        
        logger.info("✓ Pipeline components initialized")
    
    def load_json_files(self, source: str = None) -> List[Dict[str, Any]]:
        """
        Load all JSON files from raw data directory
        
        Args:
            source: Filter by source ('darglobal' or 'wasalt'), None for all
        
        Returns:
            List of document dictionaries
        """
        documents = []
        
        # Determine which directories to scan
        if source:
            dirs = [self.raw_data_dir / source]
        else:
            dirs = [d for d in self.raw_data_dir.iterdir() if d.is_dir()]
        
        for source_dir in dirs:
            if not source_dir.exists():
                logger.warning(f"Directory not found: {source_dir}")
                continue
            
            json_files = list(source_dir.glob("*.json"))
            logger.info(f"Loading {len(json_files)} files from {source_dir.name}...")
            
            for json_file in json_files:
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                        # Check if data is a list (DarGlobal format)
                        if isinstance(data, list):
                            for idx, record in enumerate(data):
                                if isinstance(record, dict):
                                    record['source'] = source_dir.name
                                    record['file_name'] = f"{json_file.stem}_{idx}.json"
                                    documents.append(record)
                            logger.info(f"  Extracted {len(data)} records from {json_file.name}")
                        
                        # Check if data has nested "records" structure (Wasalt format)
                        elif isinstance(data, dict) and 'records' in data and isinstance(data['records'], list):
                            for idx, record in enumerate(data['records']):
                                if isinstance(record, dict):
                                    record['source'] = source_dir.name
                                    record['file_name'] = f"{json_file.stem}_{idx}.json"
                                    documents.append(record)
                            logger.info(f"  Extracted {len(data['records'])} records from {json_file.name}")
                        
                        # Single document format
                        elif isinstance(data, dict):
                            data['source'] = source_dir.name
                            data['file_name'] = json_file.name
                            documents.append(data)
                            
                except Exception as e:
                    logger.error(f"Error loading {json_file}: {e}")
        
        logger.info(f"✓ Loaded {len(documents)} documents")
        return documents
    
    def normalize_document(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize document to unified format regardless of source
        
        Args:
            doc: Raw document from either DarGlobal or Wasalt
        
        Returns:
            Normalized document with consistent structure
        """
        # Create unified document structure
        normalized = {
            'url': doc.get('url', ''),
            'title': doc.get('title', ''),
            'source': doc.get('source', 'unknown'),
            'file_name': doc.get('file_name', ''),
            'scraped_at': doc.get('scraped_at', ''),
            'word_count': doc.get('word_count', 0),
        }
        
        # Extract main content from different field names
        # DarGlobal uses: 'text'
        # Wasalt uses: 'content'
        content = doc.get('text') or doc.get('content') or doc.get('main_content') or ''
        
        # Skip error messages
        if content and 'Incapsula incident ID' in content:
            content = ''
        
        normalized['content'] = content
        
        # Extract page type
        # DarGlobal uses: 'type'
        # Wasalt uses: 'page_type'
        page_type = doc.get('page_type') or doc.get('type') or 'unknown'
        normalized['page_type'] = page_type
        
        # Extract language (try to detect from URL or default)
        language = doc.get('language', 'unknown')
        if language == 'unknown':
            # Try to detect from URL
            url = normalized['url'].lower()
            if '/ar/' in url or '/ar?' in url:
                language = 'ar'
            elif '/en/' in url or '/en?' in url:
                language = 'en'
            else:
                language = 'en'  # Default to English
        normalized['language'] = language
        
        # Extract additional metadata
        metadata = {}
        
        # DarGlobal specific fields
        if 'headings' in doc and doc['headings']:
            metadata['headings'] = doc['headings']
        
        # Wasalt specific fields
        if 'structured_data' in doc and doc['structured_data']:
            metadata['structured_data'] = doc['structured_data']
        
        if 'nextjs_data' in doc and doc['nextjs_data']:
            # Extract useful info from nextjs_data without storing huge objects
            nextjs = doc['nextjs_data']
            if isinstance(nextjs, dict):
                # Store only small, useful fields
                if 'pageProps' in nextjs:
                    metadata['has_nextjs_data'] = True
        
        # Add description if available
        description = doc.get('description') or doc.get('meta_description', '')
        if description:
            metadata['description'] = description
        
        normalized['metadata'] = metadata
        
        return normalized
    
    def prepare_text(self, doc: Dict[str, Any]) -> str:
        """
        Extract and prepare text from normalized document
        
        Args:
            doc: Normalized document dictionary
        
        Returns:
            Cleaned text ready for chunking
        """
        parts = []
        
        # Add title
        if doc.get('title'):
            parts.append(f"Title: {doc['title']}")
        
        # Add description from metadata if available
        if doc.get('metadata', {}).get('description'):
            parts.append(f"Description: {doc['metadata']['description']}")
        
        # Add main content
        content = doc.get('content', '')
        if content:
            parts.append(content)
        
        # Add headings (DarGlobal specific)
        headings = doc.get('metadata', {}).get('headings')
        if headings and isinstance(headings, list):
            heading_text = " | ".join(str(h) for h in headings if h)
            if heading_text:
                parts.append(f"Key Topics: {heading_text}")
        
        # Join all parts
        text = "\n\n".join(parts)
        return text.strip()
    
    def create_chunk_metadata(
        self,
        doc: Dict[str, Any],
        chunk_index: int
    ) -> Dict[str, Any]:
        """
        Create metadata for a chunk from normalized document
        
        Args:
            doc: Normalized document
            chunk_index: Index of this chunk
        
        Returns:
            Metadata dictionary
        """
        metadata = {
            'source': doc.get('source', 'unknown'),
            'url': doc.get('url', ''),
            'title': doc.get('title', ''),
            'page_type': doc.get('page_type', 'unknown'),
            'language': doc.get('language', 'en'),
            'chunk_index': chunk_index,
            'file_name': doc.get('file_name', ''),
            'word_count': doc.get('word_count', 0),
        }
        
        # Add token count if available
        if doc.get('content'):
            # Rough estimate: 1 token ≈ 4 characters
            metadata['token_count'] = len(doc['content']) // 4
        
        # Extract city if present in URL/title/content for retriever filtering
        url_lower = doc.get('url', '').lower()
        title_lower = doc.get('title', '').lower()
        for c in ['Riyadh', 'Jeddah', 'Mecca', 'Makkah', 'Medina', 'Madinah', 'Dammam', 'Khobar', 'Dubai', 'London', 'Muscat']:
            if c.lower() in url_lower or c.lower() in title_lower:
                metadata['city'] = c
                break

        # Extract property_type if present
        for pt in ['villa', 'apartment', 'land', 'floor', 'office', 'penthouse', 'townhouse']:
            if pt in url_lower or pt in title_lower:
                metadata['property_type'] = pt
                break

        return metadata
    
    def process_documents(
        self,
        documents: List[Dict[str, Any]],
        batch_size: int = 32
    ) -> int:
        """
        Process documents through the complete pipeline
        
        Args:
            documents: List of document dictionaries
            batch_size: Batch size for embedding generation
        
        Returns:
            Total number of chunks added to vector store
        """
        total_chunks = 0
        
        logger.info(f"Processing {len(documents)} documents...")
        
        for doc_idx, doc in enumerate(tqdm(documents, desc="Processing documents")):
            # 1. Normalize document to unified format
            normalized_doc = self.normalize_document(doc)
            
            # 2. Extract and prepare text
            text = self.prepare_text(normalized_doc)
            
            if not text:
                logger.warning(f"No text extracted from {normalized_doc.get('url', 'unknown')}")
                continue
            
            # 3. Chunk the text
            chunks = chunking.chunk_text(
                text=text,
                metadata=self.create_chunk_metadata(normalized_doc, 0),
                chunk_size=self.chunk_size,
                overlap=self.chunk_overlap
            )
            
            if not chunks:
                continue
            
            # 4. Generate embeddings in batches
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i:i + batch_size]
                
                # Update chunk indices
                for j, chunk in enumerate(batch):
                    chunk['chunk_index'] = i + j
                    clean_file = Path(normalized_doc.get('file_name', 'doc')).stem
                    chunk['chunk_id'] = f"{normalized_doc.get('source', 'unknown')}_{clean_file}_{doc_idx}_{i+j}"
                
                # Embed the batch
                embedded_chunks = self.embedder.embed_chunks(batch)
                
                # 5. Add to vector store
                count = self.vector_store.add_documents(embedded_chunks)
                total_chunks += count
        
        logger.info(f"✓ Total chunks processed and stored: {total_chunks}")
        return total_chunks
    
    def run(
        self,
        source: str = None,
        reset: bool = False
    ):
        """
        Run the complete ingestion pipeline
        
        Args:
            source: Filter by source ('darglobal' or 'wasalt'), None for all
            reset: If True, clear existing data before ingestion
        """
        print("\n" + "=" * 60)
        print("DATA INGESTION PIPELINE")
        print("=" * 60)
        
        # Reset if requested
        if reset:
            print("\n⚠ Resetting vector store...")
            self.vector_store.delete_all()
            print("✓ Vector store cleared")
        
        # Show initial state
        initial_count = self.vector_store.count_documents()
        print(f"\nInitial document count: {initial_count}")
        
        # Load documents
        print("\n1. Loading documents...")
        documents = self.load_json_files(source)
        
        if not documents:
            print("❌ No documents found to process")
            return
        
        # Process documents
        print("\n2. Processing documents (chunk + embed + store)...")
        total_chunks = self.process_documents(documents)
        
        # Show final state
        final_count = self.vector_store.count_documents()
        print(f"\n3. Final document count: {final_count}")
        print(f"   New chunks added: {total_chunks}")
        
        # Show collection info
        print("\n4. Collection information:")
        info = self.vector_store.get_collection_info()
        for key, value in info.items():
            print(f"   {key}: {value}")
        
        print("\n" + "=" * 60)
        print("✓ INGESTION COMPLETED SUCCESSFULLY!")
        print("=" * 60 + "\n")


def main():
    """Main entry point for ingestion script"""
    parser = argparse.ArgumentParser(
        description='Ingest scraped property data into vector database'
    )
    parser.add_argument(
        '--source',
        type=str,
        choices=['darglobal', 'wasalt'],
        help='Process only specific source (default: all)'
    )
    parser.add_argument(
        '--reset',
        action='store_true',
        help='Reset vector store before ingestion'
    )
    parser.add_argument(
        '--chunk-size',
        type=int,
        default=600,
        help='Target chunk size in tokens (default: 600)'
    )
    parser.add_argument(
        '--chunk-overlap',
        type=int,
        default=100,
        help='Chunk overlap in tokens (default: 100)'
    )
    
    args = parser.parse_args()
    
    # Create and run pipeline
    pipeline = DataIngestionPipeline(
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap
    )
    
    pipeline.run(
        source=args.source,
        reset=args.reset
    )


if __name__ == "__main__":
    main()
