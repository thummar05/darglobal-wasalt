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
        raw_data_dir: str = None,
        vector_store_dir: str = None,
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
        self.raw_data_dir = Path(raw_data_dir) if raw_data_dir else base_dir / "data" / "raw"
        self.vector_store_dir = str(vector_store_dir) if vector_store_dir else str(base_dir / "data" / "chroma")
        
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
                        if isinstance(data, list):
                            for idx, item in enumerate(data):
                                if isinstance(item, dict):
                                    item['source'] = source_dir.name
                                    item['file_name'] = f"{json_file.stem}_{idx}.json"
                                    documents.append(item)
                        elif isinstance(data, dict):
                            data['source'] = source_dir.name
                            data['file_name'] = json_file.name
                            documents.append(data)
                except Exception as e:
                    logger.error(f"Error loading {json_file}: {e}")
        
        logger.info(f"✓ Loaded {len(documents)} documents")
        return documents
    
    def extract_structured_fields(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Extract structured fields from document metadata and content."""
        meta = doc.get('metadata', {})
        fields = {}
        
        # Source & Site
        fields['source'] = doc.get('source') or doc.get('site') or 'unknown'
        fields['url'] = doc.get('url', '')
        fields['title'] = doc.get('title', '')
        fields['page_type'] = doc.get('page_type', 'general')
        
        # Location / City extraction
        address = meta.get('address') or meta.get('location') or ''
        city = ''
        if address:
            fields['location'] = address
            # Common Saudi & UAE cities
            for c in ['Riyadh', 'Jeddah', 'Mecca', 'Medina', 'Dammam', 'Khobar', 'Taif', 'Dubai', 'Ras Al Khaimah', 'Muscat', 'Doha', 'London']:
                if c.lower() in address.lower() or c.lower() in doc.get('title', '').lower():
                    city = c
                    break
        if not city:
            for c in ['Riyadh', 'Jeddah', 'Mecca', 'Medina', 'Dammam', 'Khobar', 'Taif', 'Dubai', 'Ras Al Khaimah', 'Muscat', 'Doha', 'London']:
                if c.lower() in doc.get('title', '').lower() or c.lower() in doc.get('content', '')[:300].lower():
                    city = c
                    break
        if city:
            fields['city'] = city
            
        # Price and Currency
        if meta.get('price') is not None:
            fields['price'] = str(meta['price'])
        elif doc.get('content'):
            import re
            price_match = re.search(r'([\d,]+)\s*(?:SAR|AED|OMR|QAR|/Year|/Month)', doc['content'])
            if price_match:
                fields['price'] = price_match.group(1).replace(',', '')
        if meta.get('currency'):
            fields['currency'] = meta['currency']
            
        # Property type / partner / category
        prop_type = meta.get('property_main_type') or meta.get('project_type') or ''
        if prop_type:
            fields['property_type'] = prop_type
        if meta.get('partner'):
            fields['partner'] = meta['partner']
        if meta.get('category'):
            fields['category'] = meta['category']
            
        # Bedrooms and Area
        import re
        bed_match = re.search(r'(\d+)\s*Bedrooms?', doc.get('title', '') + ' ' + doc.get('content', '')[:400], re.IGNORECASE)
        if bed_match:
            fields['bedrooms'] = int(bed_match.group(1))
            
        area_match = re.search(r'([\d.]+)\s*SQM', doc.get('title', '') + ' ' + doc.get('content', '')[:400], re.IGNORECASE)
        if area_match:
            fields['area_sqm'] = float(area_match.group(1))
            
        return fields

    def prepare_text(self, doc: Dict[str, Any]) -> str:
        """
        Extract and prepare text from document with structured header.
        
        Args:
            doc: Document dictionary
        
        Returns:
            Cleaned text ready for chunking
        """
        parts = []
        structured = self.extract_structured_fields(doc)
        
        # Add structured header for rich context
        header_items = []
        if structured.get('title'):
            header_items.append(f"Title: {structured['title']}")
        if structured.get('source'):
            header_items.append(f"Source: {structured['source'].capitalize()}")
        if structured.get('city'):
            header_items.append(f"City: {structured['city']}")
        if structured.get('location'):
            header_items.append(f"Location: {structured['location']}")
        if structured.get('property_type'):
            header_items.append(f"Property Type: {structured['property_type']}")
        if structured.get('price'):
            curr = structured.get('currency', 'SAR')
            header_items.append(f"Price: {structured['price']} {curr}")
        if structured.get('bedrooms'):
            header_items.append(f"Bedrooms: {structured['bedrooms']}")
        if structured.get('area_sqm'):
            header_items.append(f"Area: {structured['area_sqm']} SQM")
        if structured.get('partner'):
            header_items.append(f"Brand Partner: {structured['partner']}")
        if structured.get('url'):
            header_items.append(f"URL: {structured['url']}")
            
        if header_items:
            parts.append("--- Property Summary ---\n" + "\n".join(header_items))
        
        # Add metadata summary if present
        if doc.get('meta_description'):
            parts.append(f"Description: {doc['meta_description']}")
        
        # Add main content
        if doc.get('main_content'):
            parts.append(doc['main_content'])
        elif doc.get('content'):
            parts.append(doc['content'])
        elif doc.get('text'):
            parts.append(doc['text'])
        
        # Add FAQ if available
        if doc.get('faq'):
            faq_text = "Frequently Asked Questions:\n"
            for qa in doc['faq']:
                if isinstance(qa, dict):
                    q = qa.get('question', '')
                    a = qa.get('answer', '')
                    if q and a:
                        faq_text += f"Q: {q}\nA: {a}\n"
            parts.append(faq_text)
        
        # Join all parts
        text = "\n\n".join(parts)
        return text.strip()
    
    def create_chunk_metadata(
        self,
        doc: Dict[str, Any],
        chunk_index: int
    ) -> Dict[str, Any]:
        """
        Create metadata for a chunk, preserving structured listing fields.
        """
        structured = self.extract_structured_fields(doc)
        meta = {
            'source': structured.get('source', 'unknown'),
            'url': structured.get('url', ''),
            'title': structured.get('title', ''),
            'page_type': structured.get('page_type', 'general'),
            'chunk_index': chunk_index,
            'file_name': doc.get('file_name', '')
        }
        for key in ['city', 'location', 'property_type', 'price', 'currency', 'partner', 'category', 'bedrooms', 'area_sqm']:
            if key in structured and structured[key] is not None:
                meta[key] = structured[key]
                
        return meta
    
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
        
        for doc in tqdm(documents, desc="Processing documents"):
            # 1. Extract and prepare text
            text = self.prepare_text(doc)
            
            if not text:
                logger.warning(f"No text extracted from {doc.get('url', 'unknown')}")
                continue
            
            # 2. Chunk the text
            chunks = chunking.chunk_text(
                text=text,
                metadata=self.create_chunk_metadata(doc, 0),
                chunk_size=self.chunk_size,
                overlap=self.chunk_overlap
            )
            
            if not chunks:
                continue
            
            # 3. Generate embeddings in batches
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i:i + batch_size]
                
                # Update chunk indices
                for j, chunk in enumerate(batch):
                    chunk['chunk_index'] = i + j
                    chunk['chunk_id'] = f"{doc.get('source', 'unknown')}_{doc.get('file_name', 'unknown')}_{i+j}"
                
                # Embed the batch
                embedded_chunks = self.embedder.embed_chunks(batch)
                
                # 4. Add to vector store
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
