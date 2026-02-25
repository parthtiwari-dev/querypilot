"""
Startup indexing script for QueryPilot.
Loops over all SCHEMA_PROFILES and indexes any that aren't already in Chroma.
Safe to re-run — skips already-indexed collections.

Usage:
    python scripts/startup_index.py
"""

import sys
import logging
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from app.config import settings, SCHEMA_PROFILES
from app.schema.extractor import SchemaMetadataExtractor
from app.schema.embedder import SchemaEmbedder
from app.schema.chroma_manager import ChromaManager

logging.basicConfig(level=logging.WARNING)


def index_if_needed(schema_name: str, profile: dict) -> None:
    collection_name = profile["collection_name"]
    db_url          = profile["db_url"]
    pg_schema       = profile["pg_schema"]

    print(f"\n[{schema_name}] Checking collection '{collection_name}'...")

    chroma = ChromaManager(settings.CHROMA_URL, collection_name=collection_name)
    chroma.initialize_collection(reset=False)
    count = chroma.get_collection_stats()["count"]

    if count > 0:
        print(f"[{schema_name}] Already indexed ({count} embeddings). Skipping.")
        return

    print(f"[{schema_name}] Not indexed. Starting...")

    # Step 1: Extract
    extractor = SchemaMetadataExtractor(db_url)
    schema_metadata = extractor.extract_schema(pg_schema=pg_schema)

    if not schema_metadata:
        print(f"[{schema_name}] ERROR: No tables found in pg_schema='{pg_schema}'. Skipping.")
        return

    print(f"[{schema_name}] {len(schema_metadata)} tables found.")

    # Step 2: Embed
    embedder = SchemaEmbedder()
    documents, embeddings, metadatas = embedder.embed_schema(schema_metadata)
    print(f"[{schema_name}] {len(embeddings)} embeddings generated.")

    # Step 3: Store — no reset, collection was just confirmed empty
    chroma.add_schema_embeddings(documents, embeddings, metadatas)

    # Step 4: Verify
    final_count = chroma.get_collection_stats()["count"]
    if final_count == 0:
        print(f"[{schema_name}] ERROR: 0 embeddings after indexing. Check DB URL and pg_schema.")
        return

    print(f"[{schema_name}] Done. {final_count} embeddings stored.")


if __name__ == "__main__":
    print("=" * 50)
    print("  QueryPilot Startup Indexer")
    print("=" * 50)
    for name, profile in SCHEMA_PROFILES.items():
        index_if_needed(name, profile)
    print("\nAll schemas processed.")
