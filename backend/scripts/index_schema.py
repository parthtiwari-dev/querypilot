"""
Schema Indexing Script
One-time setup: extracts schema from Postgres, embeds it, stores in Chroma.

Usage:
    python scripts/index_schema.py --schema library
    python scripts/index_schema.py --schema ecommerce
"""

import sys
import argparse
import logging
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from app.config import settings, SCHEMA_PROFILES
from app.schema.extractor import SchemaMetadataExtractor
from app.schema.embedder import SchemaEmbedder
from app.schema.chroma_manager import ChromaManager


logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def index_schema(schema_name: str) -> None:

    # ── 0. Validate profile ──────────────────────────────────────────
    if schema_name not in SCHEMA_PROFILES:
        print(f"\nERROR: Unknown schema '{schema_name}'.")
        print(f"Available profiles: {list(SCHEMA_PROFILES.keys())}")
        sys.exit(1)

    profile        = SCHEMA_PROFILES[schema_name]
    db_url         = profile["db_url"]
    pg_schema      = profile["pg_schema"]
    collection_name = profile["collection_name"]

    print("\n" + "=" * 60)
    print(f"  INDEXING SCHEMA : {schema_name}")
    print("=" * 60)
    print(f"  pg_schema       : {pg_schema}")
    print(f"  collection      : {collection_name}")
    print(f"  chroma_url      : {settings.CHROMA_URL}")

    # ── 1. Extract ───────────────────────────────────────────────────
    print("\n[1/3] Extracting schema from PostgreSQL...")
    extractor = SchemaMetadataExtractor(db_url)
    schema_metadata = extractor.extract_schema(pg_schema=pg_schema)

    if not schema_metadata:
        print(f"\nERROR: No tables found in pg_schema='{pg_schema}'.")
        print("  → Check that the schema exists and the DB URL is correct.")
        sys.exit(1)

    print(f"  ✓ {len(schema_metadata)} tables found: {list(schema_metadata.keys())}")
    for table, info in schema_metadata.items():
        print(f"    • {table} ({len(info['columns'])} columns)")

    # ── 2. Embed ─────────────────────────────────────────────────────
    print("\n[2/3] Generating embeddings...")
    embedder = SchemaEmbedder()
    documents, embeddings, metadatas = embedder.embed_schema(schema_metadata)
    print(f"  ✓ {len(embeddings)} embeddings generated (dim={len(embeddings[0])})")

    # ── 3. Store in Chroma ───────────────────────────────────────────
    print(f"\n[3/3] Storing in Chroma collection '{collection_name}'...")
    chroma = ChromaManager(settings.CHROMA_URL, collection_name=collection_name)
    chroma.initialize_collection(reset=True)
    chroma.add_schema_embeddings(documents, embeddings, metadatas)

    # ── 4. Verify ────────────────────────────────────────────────────
    stats = chroma.get_collection_stats()
    count = stats["count"]

    print("\n" + "=" * 60)
    if count == 0:
        print("  ❌ FAILED: 0 embeddings in collection after indexing.")
        print("     → Debug: verify pg_schema and DATABASE_URL.")
        sys.exit(1)

    print(f"  ✓ SUCCESS")
    print(f"  tables indexed  : {len(schema_metadata)}")
    print(f"  embeddings      : {count}")
    print(f"  collection      : {collection_name}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Index a database schema into Chroma for QueryPilot"
    )
    parser.add_argument(
        "--schema",
        required=True,
        choices=list(SCHEMA_PROFILES.keys()),
        help="Schema profile to index (e.g. library, ecommerce)"
    )
    args = parser.parse_args()

    index_schema(args.schema)
