# QueryPilot Deployment Guide

End-to-end guide for running QueryPilot locally with Docker and deploying it to the cloud.

---

# 1. Local Development (Docker Compose)

## 1.1 Prerequisites

- Docker Desktop installed and running  
- Git  
- Python 3.11 (optional, for running scripts directly)  
- `.env` in project root (copy from `.env.example`)

```bash
cp .env.example .env
# Fill in OPENAI_API_KEY, GROQ_API_KEY, DATABASE_URL, etc.
```

Note: In local development you typically point `DATABASE_URL` to Neon (external Postgres). A local Postgres container is optional.

---

## 1.2 Clone the repository

```bash
git clone https://github.com/your-username/querypilot.git
cd querypilot
```

---

## 1.3 Start local services

Local stack (typical dev setup):

- Backend (FastAPI)
- Chroma (HTTP service via `CHROMA_URL` in Docker)
- External Postgres (Neon via `DATABASE_URL`)

Start everything:

```bash
docker-compose up --build
```

Verify health:

```bash
curl http://localhost:8000/health
# {"status":"ok","schemas_available":["ecommerce","library"]}
```

FastAPI docs:

```
http://localhost:8000/docs
```

---

## 1.4 Optional: Local Postgres container

If you prefer running Postgres locally instead of Neon, ensure your `DATABASE_URL` in `.env` matches the container configuration in `docker-compose.yml`.

Mount schema SQL files into `docker-entrypoint-initdb.d` or seed manually:

```bash
psql "postgresql://admin:password@localhost:5432/querypilot" -f database/schemas/ecommerce.sql
psql "postgresql://admin:password@localhost:5432/querypilot" -f database/schemas/library.sql
psql "postgresql://admin:password@localhost:5432/querypilot" -f database/seed_data.sql
psql "postgresql://admin:password@localhost:5432/querypilot" -f database/library_seed.sql
```

---

## 1.5 Index schemas into Chroma

This populates schema embeddings for all profiles defined in `schema_profiles.json`.

```bash
docker-compose run --rm backend python scripts/startup_index.py
```

`startup_index.py` indexes all schemas listed in `backend/app/schema_profiles.json`.

---

## 1.6 Port reference (local)

| Port | Service     |
|------|------------|
| 8000 | Backend API |

---

## 1.7 Re-indexing after schema changes

If you modify tables or add a new schema:

```bash
docker-compose run --rm backend python scripts/startup_index.py
```

The startup script will re-check all profiles in `schema_profiles.json` and index missing ones.

---

# 2. Remote Deployment (Render)

Goal: Single backend service on Render + external Postgres (Neon) + Chroma.

Render free Postgres expires after 30 days, so Neon is used as the primary database.

---

## 2.1 Create external Postgres (Neon)

Go to https://neon.tech and create a project (e.g., `querypilot`).

Copy the connection string, e.g.:

```
postgresql://user:pass@ep-xxx.neon.tech/neondb
```

Seed the database:

```bash
psql "postgresql://user:pass@ep-xxx.neon.tech/neondb" -f database/schemas/ecommerce.sql
psql "postgresql://user:pass@ep-xxx.neon.tech/neondb" -f database/schemas/library.sql
psql "postgresql://user:pass@ep-xxx.neon.tech/neondb" -f database/seed_data.sql
psql "postgresql://user:pass@ep-xxx.neon.tech/neondb" -f database/library_seed.sql
```

---

## 2.2 Deploy backend to Render

Render → New → Web Service.

- Root directory: `backend`  
- Build type: Docker

Environment variables:

```
# LLM keys
OPENAI_API_KEY=...
GROQ_API_KEY=...

# Database (Neon)
DATABASE_URL=postgresql://user:pass@ep-xxx.neon.tech/neondb

# Chroma config
CHROMA_URL=http://chroma:8000
CHROMA_PERSIST_DIR=/tmp/chroma

# LLM routing
LLM_PROVIDER=openai          # or groq
GROQ_MODEL_NAME=llama-3.1-70b-versatile
OPENAI_MODEL_NAME=gpt-4o-mini

# App behavior
MAX_RETRIES=3
QUERY_TIMEOUT=30
DEFAULT_SCHEMA=ecommerce
```

Entrypoint / CMD:

```bash
python scripts/startup_index.py && \
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl https://your-backend.onrender.com/health
# {"status":"ok","schemas_available":["ecommerce","library"]}
```

---

# 3. Deployment on Hugging Face Spaces (Docker)

Hugging Face Spaces (Docker SDK) runs a single container.

Architecture:

- Postgres: external (Neon)
- Backend + Chroma: inside the same container

Default port: 7860

---

## 3.1 Space configuration

At the top of `README.md` in the Space repo:

```
---
title: QueryPilot
sdk: docker
app_port: 7860
---
```

---

## 3.2 Dockerfile entrypoint

```
CMD ["bash", "-lc", "python scripts/startup_index.py && uvicorn app.main:app --host 0.0.0.0 --port 7860"]
```

---

## 3.3 HF Secrets

Add in Space settings:

```
OPENAI_API_KEY=...
GROQ_API_KEY=...
DATABASE_URL=postgresql://user:pass@ep-xxx.neon.tech/neondb
CHROMA_PERSIST_DIR=/data/chroma
LLM_PROVIDER=openai
GROQ_MODEL_NAME=llama-3.1-70b-versatile
OPENAI_MODEL_NAME=gpt-4o-mini
DEFAULT_SCHEMA=ecommerce
```

On first start:

- Connects to Neon
- Runs `startup_index.py`
- Starts Uvicorn on port 7860

Space URL:

```
https://<your-space>.hf.space
```

---

# 4. Adding a New Schema

No agent code changes required — configuration + indexing only.

---

## 4.1 Define SQL schema

Create:

```
database/schemas/analytics.sql
```

Seed manually for Neon if needed.

---

## 4.2 Register schema profile

In `backend/app/schema_profiles.json`:

```json
{
  "ecommerce": {
    "pg_schema": "public",
    "collection_name": "querypilot_ecommerce_v2"
  },
  "library": {
    "pg_schema": "library",
    "collection_name": "querypilot_library_v2"
  },
  "analytics": {
    "pg_schema": "analytics",
    "collection_name": "querypilot_analytics_v1"
  }
}
```

`config.py` loads this file into `SCHEMA_PROFILES` and injects `db_url` at runtime based on `DATABASE_URL`.

---

## 4.3 Index the new schema

```bash
docker-compose run --rm backend python scripts/startup_index.py
```

Startup script will index all profiles defined in `schema_profiles.json`, including the new `analytics` schema.

After indexing:

```bash
curl http://localhost:8000/health
# {"status":"ok","schemas_available":["ecommerce","library","analytics"]}
```

---

# 5. Known Limitations

## 5.1 Cold start latency (Render free)

Services spin down after idle on free tier.

First request may take 30–60 seconds.

---

## 5.2 Re-indexing and Chroma persistence

If persistent volume is not mounted, Chroma data is ephemeral.

`startup_index.py` will rebuild embeddings on cold start.

---

## 5.3 Embedding model download

`sentence-transformers/all-MiniLM-L6-v2` downloads on first run (~90MB).

Adds ~30s to first cold start.

---

## 5.4 Single DB, multiple schemas

All schemas share a single Postgres instance via `DATABASE_URL`.

Suitable for portfolio use; production multi-tenant setups should isolate databases.

