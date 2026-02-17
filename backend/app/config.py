"""
Configuration module for QueryPilot
Supports both Groq (primary) and OpenAI (backup) providers
"""

from pydantic_settings import BaseSettings
from typing import Literal
import os
from pathlib import Path


# Find the project root directory (where .env is located)
def find_project_root():
    """Find project root by looking for .env file"""
    current = Path(__file__).resolve()
    
    # Go up from backend/app/config.py to project root
    # backend/app/config.py -> backend/app -> backend -> project_root
    project_root = current.parent.parent.parent
    
    return project_root


class Settings(BaseSettings):
    """Application settings with environment variable loading"""
    
    # LLM Provider
    LLM_PROVIDER: Literal["groq", "openai"] = "openai"  # Default to Groq
    
    # Groq Configuration (FREE - PRIMARY)
    GROQ_API_KEY: str
    GROQ_MODEL_NAME: str = "llama-3.1-70b-versatile"
    
    # OpenAI Configuration (BACKUP)
    OPENAI_API_KEY: str
    OPENAI_MODEL_NAME: str = "gpt-4o-mini"
    
    # Database
    DATABASE_URL: str
    
    # Chroma DB
    CHROMA_URL: str = "http://localhost:8000"
    
    # System Settings
    MAX_RETRIES: int = 3
    QUERY_TIMEOUT: int = 30
    
    class Config:
        # Dynamically find .env file in project root
        env_file = str(find_project_root() / ".env")
        case_sensitive = True


# Global settings instance
settings = Settings()


def get_llm():
    """
    Factory function to get the configured LLM
    Returns either Groq or OpenAI based on LLM_PROVIDER setting
    """
    if settings.LLM_PROVIDER == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=settings.GROQ_MODEL_NAME,
            api_key=settings.GROQ_API_KEY,
            temperature=0,
        )
    else:  # openai
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.OPENAI_MODEL_NAME,
            api_key=settings.OPENAI_API_KEY,
            temperature=0,
            top_p=1,
        )


# Quick test if running directly
if __name__ == "__main__":
    print(f"LLM Provider: {settings.LLM_PROVIDER}")
    print(f"Groq Model: {settings.GROQ_MODEL_NAME}")
    print(f"Database: {settings.DATABASE_URL}")
    print(f"Chroma: {settings.CHROMA_URL}")
    print(f".env file location: {find_project_root() / '.env'}")
