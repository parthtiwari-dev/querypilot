# QueryPilot Deployment Guide

---

## Section 1: Local Development (Docker Compose)

### Prerequisites

- Docker Desktop installed and running  
- Git  
- A `.env` file in the project root (copy from `.env.example`)

---

### Setup

#### 1. Clone the repository

```bash
git clone https://github.com/your-username/querypilot.git
cd querypilot
```

#### 2. Create your `.env` file

```bash
cp .env.example .env
# Fill in OPENAI_API_KEY, GROQ_API_KEY
```

#### 3. Start Postgres + Chroma

```bash
docker-compose up postgres chromadb -d
```

#### 4. Wait ~15 seconds, verify both are running

```bash
docker-compose ps
# postgres → healthy
# chromadb → Up
```

#### 5. Index all schemas into Chroma (run once)

```bash
docker-compose run --rm backend python scripts/startup_index.py
```

Expected output:

```text
[ecommerce] Indexing... Done. 45 embeddings stored.
[library] Indexing... Done. 25 embeddings stored.
All schemas processed.
```

#### 6. Start the full stack

```bash
docker-compose up
```

#### 7. Verify

```bash
curl http://localhost:8000/health
# {"status":"ok","schemas_available":["ecommerce","library"]}
```

FastAPI docs available at:  
`http://localhost:8000/docs`

---

### Port Reference

| Port | Service |
|------|----------|
| 8000 | Backend (FastAPI) |
| 8001 | Chroma (host mapping) |
| 5432 | Postgres |

---

### Re-indexing

If you need to force re-index (after schema changes):

```bash
docker-compose run --rm backend python scripts/index_schema.py --schema ecommerce
docker-compose run --rm backend python scripts/index_schema.py --schema library
```

---

## Section 2: Remote Deployment

---

### Option A: Render (Recommended)

#### Architecture on Render

| Local | Render |
|--------|--------|
| Postgres container | Render managed Postgres |
| Chroma container | Render Web Service (chromadb/chroma image) |
| Backend container | Render Web Service (from Dockerfile) |

---

### Step 1 — Managed Postgres

Go to Render dashboard → New → PostgreSQL  

Name: `querypilot-db`  

Copy the **Internal Database URL** (used for `DATABASE_URL`)

---

### Step 2 — Deploy Chroma

New → Web Service → Deploy an existing image  

Image: `chromadb/chroma:1.4.1`  

Environment variable:

```text
IS_PERSISTENT=TRUE
```

Add a Disk:  
- Mount path: `/data`  
- Size: 1GB  

Copy the internal URL (e.g. `https://querypilot-chroma.onrender.com`)

---

### Step 3 — Deploy Backend

New → Web Service → Connect your GitHub repo  

- Root directory: `backend`  
- Dockerfile path: `./Dockerfile`  

Add all environment variables:

```text
OPENAI_API_KEY=...
GROQ_API_KEY=...
DATABASE_URL=<Internal Postgres URL from Step 1>
CHROMA_URL=<Chroma service URL from Step 2>
GROQ_MODEL_NAME=llama-3.3-70b-versatile
OPENAI_MODEL_NAME=gpt-4o-mini
MAX_RETRIES=3
QUERY_TIMEOUT=30
LLM_PROVIDER=openai
DEFAULT_SCHEMA=ecommerce
```

---

### Step 4 — Seed the Database

Use Render's Shell tab on the Postgres service, or connect with `psql`:

```bash
psql <External Database URL> -f database/schemas/ecommerce.sql
psql <External Database URL> -f database/schemas/library.sql
psql <External Database URL> -f database/seed_data.sql
psql <External Database URL> -f database/library_seed.sql
```

---

### Step 5 — Run Startup Indexing

In Render dashboard → Backend service → Shell:

```bash
python scripts/startup_index.py
```

---

### Step 6 — Verify

```bash
curl https://your-backend.onrender.com/health
# {"status":"ok","schemas_available":["ecommerce","library"]}
```

---

### Option B: Hugging Face Spaces (Docker)

#### Architecture on HF Spaces

| Local | HF Spaces |
|--------|------------|
| Postgres container | Supabase or Neon (free external Postgres) |
| Chroma container | File-based Chroma (inside backend container) |
| Backend container | HF Docker Space |

---

### Key Difference

HF Spaces runs a single Docker container.  
No `docker-compose`, no separate Chroma service.  
Chroma must run in file-based mode using a persistent `/data` volume.

---

### Step 1 — External Postgres

Create a free database at:

- neon.tech  
- supabase.com  

Run your schema SQL files from the dashboard SQL editor.  

Copy the connection string.

---

### Step 2 — Update ChromaManager for file-based mode

Set:

```text
CHROMA_PERSIST_DIR=/data/chroma
```

in HF Space secrets.

ChromaManager reads this env var and switches to local file mode automatically.

---

### Step 3 — Create HF Space

New Space → Docker → Connect GitHub repo  

Add Secrets (equivalent to env vars):

```text
OPENAI_API_KEY
GROQ_API_KEY
DATABASE_URL=<Neon/Supabase connection string>
CHROMA_PERSIST_DIR=/data/chroma
LLM_PROVIDER=openai
DEFAULT_SCHEMA=ecommerce
```

---

### Step 4 — Run indexing on first start

Add to your Dockerfile `CMD` or an entrypoint script:

```bash
python scripts/startup_index.py && uvicorn app.main:app --host 0.0.0.0 --port 7860
```

HF Spaces serves on port `7860` by default, not `8000`.

---

## Section 3: Adding a New Schema

4 steps, no agent code changes needed.

---

### Step 1 — Write the SQL schema

```bash
# Create database/schemas/yourschema.sql
# Define all tables, constraints, indexes
```

---

### Step 2 — Seed the data

```bash
# Create database/yourschema_seed.sql
# Mount it in docker-compose.yml:
# - ./database/schemas/yourschema.sql:/docker-entrypoint-initdb.d/03-yourschema.sql
```

---

### Step 3 — Register in config

Add to `SCHEMA_PROFILES` in `backend/app/config.py`:

```python
"yourschema": {
    "db_url":          settings.DATABASE_URL,
    "pg_schema":       "yourschema",   # postgres schema name
    "collection_name": "yourschema_collection",
},
```

---

### Step 4 — Index it

```bash
docker-compose run --rm backend python scripts/index_schema.py --schema yourschema
```

Done. The schema is now available via `?schema=yourschema` on all API endpoints.

---

## Section 4: Known Limitations

---

### Cold Start Latency (Render Free Tier)

Render free tier services spin down after 15 minutes of inactivity.  
First request after idle takes 30–60 seconds to respond.

Solution: upgrade to paid tier, or use UptimeRobot to ping `/health` every 10 minutes.

---

### Ephemeral Chroma on HF Spaces

HF Spaces free tier does not guarantee persistent disk across restarts.  
If the Space restarts, Chroma data is lost and `startup_index.py` must re-run.

This happens automatically if the entrypoint script includes the indexing command.

Re-indexing takes ~30 seconds for the current schemas.

Solution: use a paid persistent storage volume, or accept the cold-start re-index.

---

### Embedding Model Download on Cold Start

`sentence-transformers/all-MiniLM-L6-v2` (~90MB) downloads from HuggingFace on first run if not cached.  
This adds ~30 seconds to the first startup.

Solution: bake the model into the Docker image at build time.

---

### Single Database, Multiple Schemas

Currently both `ecommerce` and `library` schemas share one Postgres instance.  

This is fine for a portfolio project but not for production multi-tenant use.

