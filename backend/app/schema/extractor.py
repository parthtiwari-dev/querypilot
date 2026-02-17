"""
Schema Metadata Extractor
Extracts table and column information from PostgreSQL database
"""

from sqlalchemy import create_engine, inspect, MetaData
from typing import Dict, List, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SchemaMetadataExtractor:
    """Extracts schema metadata from PostgreSQL database"""
    
    def __init__(self, database_url: str):
        """
        Initialize extractor with database connection
        
        Args:
            database_url: PostgreSQL connection string
        """
        self.database_url = database_url
        self.engine = create_engine(database_url)
        self.inspector = inspect(self.engine)
        
    def extract_schema(self) -> Dict[str, Any]:
        """
        Extract complete schema metadata from database
        
        Returns:
            Dictionary with table names as keys and metadata as values
        """
        schema_metadata = {}
        
        # Get all table names
        table_names = self.inspector.get_table_names()
        logger.info(f"Found {len(table_names)} tables in database")
        
        for table_name in table_names:
            schema_metadata[table_name] = self._extract_table_metadata(table_name)
            
        return schema_metadata
    
    def _extract_table_metadata(self, table_name: str) -> Dict[str, Any]:
        """
        Extract metadata for a specific table
        
        Args:
            table_name: Name of the table
            
        Returns:
            Dictionary with columns, data types, and foreign keys
        """
        # Get columns
        columns = self.inspector.get_columns(table_name)
        column_names = [col['name'] for col in columns]
        
        # Get data types
        data_types = {col['name']: str(col['type']) for col in columns}
        
        # Get foreign keys
        foreign_keys = self.inspector.get_foreign_keys(table_name)
        
        # ✅ FIX: Format FK as {column: referred_table.referred_column}
        # This matches what SQL Generator expects!
        fk_dict = {}
        for fk in foreign_keys:
            if fk['constrained_columns'] and fk['referred_columns']:
                col = fk['constrained_columns'][0]
                ref_table = fk['referred_table']
                ref_col = fk['referred_columns'][0]
                fk_dict[col] = f"{ref_table}.{ref_col}"
        
        # Get primary key
        pk_constraint = self.inspector.get_pk_constraint(table_name)
        primary_keys = pk_constraint.get('constrained_columns', [])
        
        return {
            'columns': data_types,  # ✅ Dict format
            'data_types': data_types,
            'primary_keys': primary_keys,
            'foreign_keys': fk_dict,  # ✅ FIX: Use dict format
            'column_count': len(column_names)
        }
    
    def get_table_description(self, table_name: str) -> str:
        """
        Generate human-readable description of a table
        
        Args:
            table_name: Name of the table
            
        Returns:
            Text description of the table
        """
        metadata = self._extract_table_metadata(table_name)
        
        desc = f"Table: {table_name}\n"
        desc += f"Columns ({len(metadata['columns'])}): {', '.join(metadata['columns'])}\n"
        
        if metadata['primary_keys']:
            desc += f"Primary Keys: {', '.join(metadata['primary_keys'])}\n"
        
        if metadata['foreign_keys']:
            fk_desc = []
            for fk in metadata['foreign_keys']:
                fk_desc.append(
                    f"{fk['constrained_columns'][0]} -> {fk['referred_table']}.{fk['referred_columns'][0]}"
                )
            desc += f"Foreign Keys: {', '.join(fk_desc)}\n"
        
        return desc
    
    def get_database_summary(self) -> str:
        """Get a summary of the entire database schema"""
        schema = self.extract_schema()
        
        summary = f"Database Summary:\n"
        summary += f"Total Tables: {len(schema)}\n"
        summary += f"Total Columns: {sum(meta['column_count'] for meta in schema.values())}\n\n"
        
        summary += "Tables:\n"
        for table_name in schema.keys():
            summary += f"  - {table_name} ({len(schema[table_name]['columns'])} columns)\n"
        
        return summary


# Quick test if running directly
if __name__ == "__main__":
    from app.config import settings
    
    extractor = SchemaMetadataExtractor(settings.DATABASE_URL)
    
    # Test extraction
    schema = extractor.extract_schema()
    
    print("\n" + "="*50)
    print("SCHEMA EXTRACTION TEST")
    print("="*50)
    
    print(f"\nExtracted {len(schema)} tables:")
    for table_name in schema.keys():
        print(f"  ✓ {table_name}")
    
    print("\n" + "-"*50)
    print("SAMPLE TABLE DETAILS (customers):")
    print("-"*50)
    print(extractor.get_table_description('customers'))
    
    print("\n" + "-"*50)
    print("DATABASE SUMMARY:")
    print("-"*50)
    print(extractor.get_database_summary())


