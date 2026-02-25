from fastapi import FastAPI
from app.api.routes import router

app = FastAPI(
    title="QueryPilot",
    version="1.0.0",
    description="Natural language to SQL pipeline with self-correction.",
)

app.include_router(router)
