"""
setup_schema.py — one-command schema registration for QueryPilot.

Usage:
    python scripts/setup_schema.py --schema-name my_schema --pg-schema public

What it does:
1. Connects to DATABASE_URL and confirms tables exist in the given pg_schema
2. Adds the schema entry to schema_profiles.json (never edits Python source files)
3. Runs index_schema.py to build embeddings for the new schema
"""

import argparse
import json
import os
import sys
import subprocess
from pathlib import Path
from sqlalchemy import create_engine, text

sys.path.append(str(Path(__file__).parent.parent))

from app.config import settings

PROFILES_PATH = Path(__file__).parent.parent / "app" / "schema_profiles.json"
DATABASE_URL = settings.DATABASE_URL


def check_db_connection(pg_schema: str) -> list:
    db_url = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")
    engine = create_engine(db_url)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = :schema ORDER BY table_name"
        ), {"schema": pg_schema}).fetchall()
    return [r[0] for r in rows]


def load_profiles() -> dict:
    return json.loads(PROFILES_PATH.read_text())


def save_profiles(profiles: dict):
    PROFILES_PATH.write_text(json.dumps(profiles, indent=2))


def run_indexing(schema_name: str):
    subprocess.run(
        [sys.executable, "scripts/index_schema.py", "--schema", schema_name],
        check=True
    )


def main():
    parser = argparse.ArgumentParser(
        description="Register and index a new schema for QueryPilot"
    )
    parser.add_argument("--schema-name", required=True,
                        help="Name to use in QueryPilot (e.g. my_schema)")
    parser.add_argument("--pg-schema", default="public",
                        help="PostgreSQL schema name (default: public)")
    args = parser.parse_args()

    print(f"\n=== QueryPilot Schema Setup ===")
    print(f"Schema name  : {args.schema_name}")
    print(f"PG schema    : {args.pg_schema}")
    print(f"DATABASE_URL : {DATABASE_URL[:40]}...")
    print(f"Profiles file: {PROFILES_PATH}")

    print(f"\n[1/3] Connecting to database...")
    try:
        tables = check_db_connection(args.pg_schema)
    except Exception as e:
        print(f"ERROR: Could not connect to database.\n{e}")
        sys.exit(1)

    if not tables:
        print(f"ERROR: No tables found in pg_schema '{args.pg_schema}'.")
        print("Make sure your tables exist in the database before running setup.")
        sys.exit(1)

    print(f"Found {len(tables)} tables: {', '.join(tables)}")

    print(f"\n[2/3] Registering in schema_profiles.json...")
    profiles = load_profiles()

    if args.schema_name in profiles:
        print(f"'{args.schema_name}' already registered. Skipping registration.")
    else:
        profiles[args.schema_name] = {
            "pg_schema": args.pg_schema,
            "collection_name": f"{args.schema_name}_collection"
        }
        save_profiles(profiles)
        print(f"Added '{args.schema_name}' to schema_profiles.json")

    print(f"\n[3/3] Indexing schema embeddings...")
    try:
        run_indexing(args.schema_name)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Indexing failed.\n{e}")
        sys.exit(1)

    print(f"\n✅ Done. Query your schema:")
    print(f'  curl -X POST http://localhost:8000/query \\')
    print(f'    -H "Content-Type: application/json" \\')
    print(f'    -d \'{{"question": "...", "schema_name": "{args.schema_name}"}}\' ')


if __name__ == "__main__":
    main()
