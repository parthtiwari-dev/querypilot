"""
Chroma DB Manager
Handles vector storage and retrieval for schema embeddings
"""

import chromadb
from chromadb.config import Settings as ChromaSettings
from typing import List, Dict, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ChromaManager:
    """Manages Chroma DB operations for schema storage"""
    
    def __init__(self, chroma_url: str = "http://localhost:8000"):
        """
        Initialize Chroma DB client
        
        Args:
            chroma_url: URL of Chroma DB server
        """
        self.client = chromadb.HttpClient(
            host=chroma_url.replace("http://", "").split(":")[0],
            port=int(chroma_url.split(":")[-1])
        )
        self.collection_name = "querypilot_schema"
        self.collection = None
        logger.info(f"Connected to Chroma DB at {chroma_url}")
    
    def initialize_collection(self, reset: bool = False):
        """
        Create or get the schema collection
        
        Args:
            reset: If True, delete existing collection and create new one
        """
        if reset:
            try:
                self.client.delete_collection(self.collection_name)
                logger.info(f"Deleted existing collection: {self.collection_name}")
            except Exception as e:
                logger.info(f"No existing collection to delete: {e}")
        
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "Database schema embeddings for QueryPilot"}
        )
        logger.info(f"Collection '{self.collection_name}' ready")
    
    def add_schema_embeddings(
        self,
        documents: List[str],
        embeddings: List[List[float]],
        metadatas: List[Dict[str, Any]]
    ):
        """
        Add schema embeddings to Chroma DB
        
        Args:
            documents: Text descriptions
            embeddings: Vector embeddings
            metadatas: Metadata for each embedding
        """
        if self.collection is None:
            self.initialize_collection()
        
        # Generate IDs
        ids = [f"schema_{i}" for i in range(len(documents))]
        
        # Add to collection
        self.collection.add(
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids
        )
        
        logger.info(f"Added {len(documents)} embeddings to Chroma DB")
    
    def search_schema(
        self,
        query_embedding: List[float],
        n_results: int = 10
    ) -> Dict[str, Any]:
        """
        Search for relevant schema elements
        
        Args:
            query_embedding: Embedding of user question
            n_results: Number of results to return
            
        Returns:
            Dictionary with documents, metadatas, and distances
        """
        if self.collection is None:
            self.initialize_collection()
        
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )
        
        return results
    
    def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics about the collection"""
        if self.collection is None:
            self.initialize_collection()
        
        count = self.collection.count()
        return {
            'name': self.collection_name,
            'count': count,
            'metadata': self.collection.metadata
        }


# Quick test if running directly
if __name__ == "__main__":
    from app.config import settings
    
    chroma = ChromaManager(settings.CHROMA_URL)
    chroma.initialize_collection()
    
    print("\n" + "="*50)
    print("CHROMA DB CONNECTION TEST")
    print("="*50)
    
    # Test adding sample data
    test_docs = ["Test document 1", "Test document 2"]
    test_embeddings = [[0.1] * 384, [0.2] * 384]  # Dummy embeddings
    test_metas = [{'type': 'test'}, {'type': 'test'}]
    
    chroma.add_schema_embeddings(test_docs, test_embeddings, test_metas)
    
    stats = chroma.get_collection_stats()
    print(f"\nCollection: {stats['name']}")
    print(f"Total embeddings: {stats['count']}")
    
    # Test search
    results = chroma.search_schema([0.15] * 384, n_results=2)
    print(f"\nSearch results: {len(results['documents'][0])} found")
    
    print("\n✓ Chroma DB connection working!")
