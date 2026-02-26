# QueryPilot Deployment Guide

End-to-end guide for running QueryPilot locally with Docker and deploying it to the cloud.

---

# 1. Local Development (Docker Compose)

## 1.1 Prerequisites

- Docker Desktop installed and running  
- Git  
- Python 3.11 (for running scripts locally, optional)  
- `.env` in project root (copy from `.env.example`)

```bash
cp .env.example .env
# Fill in OPENAI_API_KEY, GROQ_API_KEY, etc.
```

## 1.2 Clone the repository

```bash
git clone https://github.com/your-username/querypilot.git
cd querypilot
```

## 1.3 Start local services

Local stack:

- Postgres (ecommerce + library schemas)  
- Backend (FastAPI)  
- Chroma (file-based, stored inside backend container)

Start Postgres first:

```bash
docker-compose up postgres -d
```

Wait ~15 seconds, then verify:

```bash
docker-compose ps
# postgres → healthy
```

## 1.4 Seed the database (first time only)

If your `docker-compose.yml` mounts SQL files into `docker-entrypoint-initdb.d`, the database is auto-seeded on first container start.

If not, run manually:

```bash
# Replace connection string if needed
psql "postgresql://admin:password@localhost:5432/querypilot" -f database/schemas/ecommerce.sql
psql "postgresql://admin:password@localhost:5432/querypilot" -f database/schemas/library.sql
psql "postgresql://admin:password@localhost:5432/querypilot" -f database/seed_data.sql
psql "postgresql://admin:password@localhost:5432/querypilot" -f database/library_seed.sql
```

## 1.5 Index schemas into Chroma (first time)

This populates the schema embeddings for ecommerce and library.

```bash
docker-compose run --rm backend python scripts/startup_index.py
```

Expected output (approx):

```
[ecommerce] Checking collection 'querypilot_schema'...
[ecommerce] Not indexed. Starting...
[ecommerce] 7 tables found.
[ecommerce] Done. 45 embeddings stored.

[library] Checking collection 'querypilot_schema'...
[library] Not indexed. Starting...
[library] 5 tables found.
[library] Done. 25 embeddings stored.

All schemas processed.
```

Chroma runs in file-based mode and stores data under a directory like `/tmp/chroma` inside the backend container.

## 1.6 Run full stack locally

```bash
docker-compose up
```

Then check health:

```bash
curl http://localhost:8000/health
# {"status":"ok","schemas_available":["ecommerce","library"]}
```

FastAPI docs:

```
http://localhost:8000/docs
```

## 1.7 Port reference (local)

| Port | Service     |
|------|------------|
| 8000 | Backend API |
| 5432 | Postgres    |

## 1.8 Re-indexing after schema changes

If you change tables or add a new schema:

```bash
docker-compose run --rm backend python scripts/index_schema.py --schema ecommerce
docker-compose run --rm backend python scripts/index_schema.py --schema library
```

---

# 2. Remote Deployment (Render)

Goal: Single backend service on Render + external Postgres + file-based Chroma (no separate Chroma service).

Render free Postgres expires after 30 days, so we use Neon as the primary database to avoid expiry.

## 2.1 Create external Postgres (Neon)

Go to https://neon.tech and create an account.

Create a new project, e.g. `querypilot`.

Copy the connection string (e.g. `postgresql://user:pass@ep-xxx.neon.tech/neondb`).

Seed the database from your local machine:

```bash
psql "postgresql://user:pass@ep-xxx.neon.tech/neondb" -f database/schemas/ecommerce.sql
psql "postgresql://user:pass@ep-xxx.neon.tech/neondb" -f database/schemas/library.sql
psql "postgresql://user:pass@ep-xxx.neon.tech/neondb" -f database/seed_data.sql
psql "postgresql://user:pass@ep-xxx.neon.tech/neondb" -f database/library_seed.sql
```

## 2.2 Deploy backend to Render

Go to Render dashboard → New → Web Service.

Connect your GitHub repo.

Set:

- Root directory: `backend`  
- Build type: Docker (use your `backend/Dockerfile`)

Environment variables:

```
# LLM keys
OPENAI_API_KEY=...
GROQ_API_KEY=...

# Database (Neon)
DATABASE_URL=postgresql://user:pass@ep-xxx.neon.tech/neondb

# Chroma file-based config
CHROMA_PERSIST_DIR=/tmp/chroma

# LLM routing
LLM_PROVIDER=groq          # or openai
GROQ_MODEL_NAME=llama-3.3-70b-versatile
OPENAI_MODEL_NAME=gpt-4o-mini

# App behavior
MAX_RETRIES=3
QUERY_TIMEOUT=30
DEFAULT_SCHEMA=ecommerce
```

Your `entrypoint.sh` (or Docker CMD) should:

```bash
python scripts/startup_index.py && \
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Render detects port 8000 automatically.

## 2.3 Health check

After Render finishes deploying:

```bash
curl https://your-backend.onrender.com/health
# {"status":"ok","schemas_available":["ecommerce","library"]}
```

Cold start on free tier may take ~30–60s.

---

# 3. Deployment on Hugging Face Spaces (Docker)

Hugging Face Spaces (Docker SDK) runs a single container.

Architecture:

- Postgres: external (Neon/Supabase)  
- Backend + Chroma file-based: inside the single Docker container

Default port: 7860 (configurable via `app_port`)

## 3.1 External Postgres

Use the same Neon project:

- Reuse the existing database and seed data.  
- Copy the same `DATABASE_URL`.

## 3.2 Space configuration

In the repository used for the Space, add at the top of `README.md`:

```
---
title: QueryPilot
sdk: docker
app_port: 7860
---
```

HF Spaces defaults to port 7860; `app_port` selects the port the container should listen on.

## 3.3 Dockerfile entrypoint for Spaces

Your Dockerfile for the Space should include:

```
CMD ["bash", "-lc", "python scripts/startup_index.py && uvicorn app.main:app --host 0.0.0.0 --port 7860"]
```

## 3.4 HF Secrets

Add the following secrets in the Space settings (they become env vars):

```
OPENAI_API_KEY=...
GROQ_API_KEY=...
DATABASE_URL=postgresql://user:pass@ep-xxx.neon.tech/neondb
CHROMA_PERSIST_DIR=/data/chroma
LLM_PROVIDER=groq
GROQ_MODEL_NAME=llama-3.3-70b-versatile
OPENAI_MODEL_NAME=gpt-4o-mini
DEFAULT_SCHEMA=ecommerce
```

Also make sure your Docker image writes Chroma data to `/data/chroma`.

On first start, the container will:

- Connect to Neon  
- Run `startup_index.py` to build embeddings  
- Start Uvicorn on port 7860

The Space will be available at:

```
https://<your-space>.hf.space
```

---

# 4. Adding a New Schema

No agent code changes required – just config + indexing.

## 4.1 Define SQL schema

Create:

```
database/schemas/analytics.sql
```

Include all tables, constraints, and indexes.

If you want it auto-loaded for local Postgres, mount it in `docker-compose.yml`:

```
postgres:
  image: postgres:16
  environment:
    POSTGRES_DB: querypilot
    POSTGRES_USER: admin
    POSTGRES_PASSWORD: password
  volumes:
    - ./database/schemas/ecommerce.sql:/docker-entrypoint-initdb.d/01-ecommerce.sql
    - ./database/schemas/library.sql:/docker-entrypoint-initdb.d/02-library.sql
    - ./database/schemas/analytics.sql:/docker-entrypoint-initdb.d/03-analytics.sql
```

Seed data in `database/analytics_seed.sql` (run manually for Neon).

## 4.2 Register schema profile

In `backend/app/config.py`:

```python
SCHEMA_PROFILES = {
    "ecommerce": {
        "db_url": settings.DATABASE_URL,
        "pg_schema": "ecommerce",
        "collection_name": "ecommerce_schema",
    },
    "library": {
        "db_url": settings.DATABASE_URL,
        "pg_schema": "library",
        "collection_name": "library_schema",
    },
    "analytics": {
        "db_url": settings.DATABASE_URL,
        "pg_schema": "analytics",
        "collection_name": "analytics_schema",
    },
}
```

## 4.3 Index the new schema

Locally:

```bash
docker-compose run --rm backend python scripts/index_schema.py --schema analytics
```

On Render / HF Spaces:

- Ensure `startup_index.py` picks up the new schema name from `SCHEMA_PROFILES`.  
- Redeploy; startup script will detect `analytics` not indexed and process it.

After indexing, `GET /health` should show:

```json
{"status":"ok","schemas_available":["ecommerce","library","analytics"]}
```

---

# 5. Known Limitations

## 5.1 Cold start latency (Render free)

Services spin down after ~15 minutes idle on free tier.

First request after idle can take 30–60 seconds.

Mitigation:

- Use a paid plan, or  
- Ping `/health` every 10 minutes via UptimeRobot.

## 5.2 Re-indexing and Chroma persistence

On Render/HF, Chroma data lives on ephemeral disk unless you mount a persistent volume.

If the container is rebuilt or the disk is cleared, `startup_index.py` must re-run.

Current schemas index in ~30–90 seconds; acceptable for cold start.

## 5.3 Embedding model download

`sentence-transformers/all-MiniLM-L6-v2` downloads from Hugging Face on first run (~90MB).

Adds ~30s to first cold start.

Mitigation:

- Bake the model into the Docker image at build time.

## 5.4 Single DB, multiple schemas

`ecommerce`, `library`, and any new schemas share a single Postgres instance.

Fine for a portfolio project; for multi-tenant production, use per-tenant DBs or separate clusters.

