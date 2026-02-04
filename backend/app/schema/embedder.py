"""
Schema Embedder
Converts schema metadata into embeddings for vector search
"""

from sentence_transformers import SentenceTransformer
from typing import Dict, List, Tuple, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SchemaEmbedder:
    """
    Generates embeddings for database schema elements
    Uses sentence-transformers (LOCAL - no API costs!)
    """
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize embedder with sentence-transformer model
        
        Args:
            model_name: HuggingFace model name (default is fast and good)
        """
        logger.info(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        logger.info("Embedding model loaded successfully")
    
    def embed_schema(
        self, 
        schema_metadata: Dict[str, Any]
    ) -> Tuple[List[str], List[List[float]], List[Dict[str, str]]]:
        """
        Generate embeddings for entire schema
        
        Args:
            schema_metadata: Output from SchemaMetadataExtractor
            
        Returns:
            Tuple of (documents, embeddings, metadatas)
            - documents: Text descriptions
            - embeddings: Vector embeddings
            - metadatas: Metadata for each embedding
        """
        documents = []
        metadatas = []
        
        for table_name, table_info in schema_metadata.items():
            # Create table-level embedding
            table_doc = self._create_table_document(table_name, table_info)
            documents.append(table_doc)
            metadatas.append({
                'type': 'table',
                'table_name': table_name,
                'column_count': str(table_info['column_count'])
            })
            
            # Create column-level embeddings
            for col_name in table_info['columns']:
                col_doc = self._create_column_document(
                    table_name, 
                    col_name, 
                    table_info['data_types'].get(col_name, 'UNKNOWN')
                )
                documents.append(col_doc)
                metadatas.append({
                    'type': 'column',
                    'table_name': table_name,
                    'column_name': col_name,
                    'data_type': str(table_info['data_types'].get(col_name, 'UNKNOWN'))
                })
        
        # Generate embeddings in batch (faster)
        logger.info(f"Generating embeddings for {len(documents)} schema elements...")
        embeddings = self.model.encode(documents, show_progress_bar=True)
        logger.info(f"Generated {len(embeddings)} embeddings")
        
        return documents, embeddings.tolist(), metadatas
    
    def _create_table_document(self, table_name: str, table_info: Dict) -> str:
        """
        Create text description for a table
        
        Example output:
        "Table: customers. Columns: customer_id, name, email, country, lifetime_value"
        """
        columns_str = ', '.join(table_info['columns'])
        doc = f"Table: {table_name}. Columns: {columns_str}"
        
        # Add foreign key info if exists
        if table_info['foreign_keys']:
            fk_info = []
            for fk in table_info['foreign_keys']:
                fk_info.append(
                    f"{fk['constrained_columns'][0]} references {fk['referred_table']}"
                )
            doc += f". Relationships: {', '.join(fk_info)}"
        
        return doc
    
    def _create_column_document(
        self, 
        table_name: str, 
        column_name: str, 
        data_type: str
    ) -> str:
        """
        Create text description for a column
        
        Example output:
        "Column: email in table customers. Type: VARCHAR"
        """
        return f"Column: {column_name} in table {table_name}. Type: {data_type}"
    
    def embed_question(self, question: str) -> List[float]:
        """
        Embed a user question for similarity search
        
        Args:
            question: Natural language question
            
        Returns:
            Embedding vector
        """
        return self.model.encode(question).tolist()


# Quick test if running directly
if __name__ == "__main__":
    from app.schema.extractor import SchemaMetadataExtractor
    from app.config import settings
    
    # Extract schema
    extractor = SchemaMetadataExtractor(settings.DATABASE_URL)
    schema = extractor.extract_schema()
    
    # Create embeddings
    embedder = SchemaEmbedder()
    documents, embeddings, metadatas = embedder.embed_schema(schema)
    
    print("\n" + "="*50)
    print("SCHEMA EMBEDDING TEST")
    print("="*50)
    
    print(f"\nGenerated {len(embeddings)} embeddings")
    print(f"Embedding dimension: {len(embeddings[0])}")
    
    print("\n" + "-"*50)
    print("SAMPLE DOCUMENTS:")
    print("-"*50)
    for i, (doc, meta) in enumerate(zip(documents[:5], metadatas[:5])):
        print(f"\n{i+1}. Type: {meta['type']}")
        print(f"   Document: {doc}")
        print(f"   Metadata: {meta}")
    
    print("\n" + "-"*50)
    print("SAMPLE QUESTION EMBEDDING:")
    print("-"*50)
    question = "Show me customer information"
    q_embedding = embedder.embed_question(question)
    print(f"Question: {question}")
    print(f"Embedding shape: {len(q_embedding)}")
    print(f"First 5 values: {q_embedding[:5]}")
