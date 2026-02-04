"""
Schema Linker Agent
Retrieves relevant database tables for natural language questions
"""

from app.schema.extractor import SchemaMetadataExtractor
from app.schema.embedder import SchemaEmbedder
from app.schema.chroma_manager import ChromaManager
from app.config import settings
from typing import Dict, List, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SchemaLinker:
    """
    Agent that links natural language questions to relevant database schema
    This is the first step in preventing hallucinations!
    """
    
    def __init__(self):
        """Initialize Schema Linker with all components"""
        logger.info("Initializing Schema Linker...")
        
        # Initialize components
        self.extractor = SchemaMetadataExtractor(settings.DATABASE_URL)
        self.embedder = SchemaEmbedder()
        self.chroma = ChromaManager(settings.CHROMA_URL)
        
        # Cache for schema metadata
        self._schema_cache = None
        
        logger.info("Schema Linker initialized successfully")
    
    def index_schema(self, reset: bool = True):
        """
        Extract database schema and index it in Chroma DB
        This should be run once at startup
        
        Args:
            reset: If True, clear existing index and rebuild
        """
        logger.info("Starting schema indexing...")
        
        # Step 1: Extract schema from database
        schema_metadata = self.extractor.extract_schema()
        self._schema_cache = schema_metadata
        logger.info(f"Extracted schema for {len(schema_metadata)} tables")
        
        # Step 2: Generate embeddings
        documents, embeddings, metadatas = self.embedder.embed_schema(schema_metadata)
        logger.info(f"Generated {len(embeddings)} embeddings")
        
        # Step 3: Store in Chroma DB
        self.chroma.initialize_collection(reset=reset)
        self.chroma.add_schema_embeddings(documents, embeddings, metadatas)
        
        logger.info("✓ Schema indexing complete!")
        
        return {
            'tables_indexed': len(schema_metadata),
            'embeddings_created': len(embeddings),
            'status': 'success'
        }
    
    def link_schema(
        self, 
        question: str, 
        top_k: int = 7
    ) -> Dict[str, List[str]]:
        """
        Find relevant tables and columns for a question
        
        Args:
            question: Natural language question
            top_k: Number of schema elements to retrieve
            
        Returns:
            Dictionary mapping table names to their relevant columns
        """
        logger.info(f"Linking schema for question: {question}")
        
        # Step 1: Embed the question
        question_embedding = self.embedder.embed_question(question)
        
        # Step 2: Search Chroma DB for similar schema elements
        results = self.chroma.search_schema(question_embedding, n_results=top_k)
        
        # Step 3: Group results by table
        relevant_schema = self._group_by_table(results)
        
        logger.info(f"Found {len(relevant_schema)} relevant tables")
        
        return relevant_schema
    
    def _group_by_table(self, search_results: Dict) -> Dict[str, List[str]]:
        """
        Group search results by table name
        
        Args:
            search_results: Results from Chroma DB search
            
        Returns:
            Dictionary mapping table names to column lists
        """
        table_schema = {}
        
        metadatas = search_results['metadatas'][0]
        
        for metadata in metadatas:
            table_name = metadata['table_name']
            
            if table_name not in table_schema:
                table_schema[table_name] = {
                    'columns': set(),
                    'score': 0
                }
            
            # Add column if it's a column-level result
            if metadata['type'] == 'column':
                table_schema[table_name]['columns'].add(metadata['column_name'])
        
        # Convert sets to lists and get all columns for each table
        result = {}
        for table_name in table_schema.keys():
            if self._schema_cache and table_name in self._schema_cache:
                # Get all columns for this table
                result[table_name] = self._schema_cache[table_name]['columns']
            else:
                # Fallback to retrieved columns only
                result[table_name] = list(table_schema[table_name]['columns'])
        
        return result
    
    def get_schema_summary(self) -> str:
        """Get a human-readable summary of indexed schema"""
        if self._schema_cache is None:
            return "Schema not indexed yet. Call index_schema() first."
        
        summary = f"Indexed Schema Summary:\n"
        summary += f"Total Tables: {len(self._schema_cache)}\n\n"
        
        for table_name, info in self._schema_cache.items():
            summary += f"  • {table_name} ({len(info['columns'])} columns)\n"
        
        return summary


# Main execution and testing
if __name__ == "__main__":
    print("\n" + "="*60)
    print("SCHEMA LINKER - FULL TEST")
    print("="*60)
    
    # Initialize Schema Linker
    linker = SchemaLinker()
    
    # Index the schema
    print("\n[1] Indexing database schema...")
    result = linker.index_schema(reset=True)
    print(f"✓ Indexed {result['tables_indexed']} tables")
    print(f"✓ Created {result['embeddings_created']} embeddings")
    
    # Show summary
    print("\n" + "-"*60)
    print(linker.get_schema_summary())
    
    # Test with sample questions
    print("-"*60)
    print("[2] Testing with sample questions...")
    print("-"*60)
    
    test_questions = [
        "What are the top 10 products by revenue?",
        "Show me customer information",
        "Find orders from last month",
        "Which products have low stock?",
        "Show customer reviews and ratings"
    ]
    
    for i, question in enumerate(test_questions, 1):
        print(f"\n{i}. Question: {question}")
        schema = linker.link_schema(question, top_k=10)
        
        print(f"   Retrieved Tables: {list(schema.keys())}")
        for table, columns in schema.items():
            print(f"     - {table}: {len(columns)} columns")
