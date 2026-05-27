"""
HorRAGor – Configuration centralisée
Lecture et validation des variables d'environnement via Pydantic Settings.
"""
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- TMDB ---
    tmdb_api_key: str | None = Field(None, description="Clé API The Movie Database")
    tmdb_base_url: str = "https://api.themoviedb.org/3"
    tmdb_max_pages: int = Field(20, ge=1, le=500)

    # --- Supabase ---
    supabase_url: str | None = Field(None, description="URL du projet Supabase")
    supabase_key: str | None = Field(None, description="Clé API Supabase (anon ou service role)")
    supabase_db_url: str | None = Field(
        None,
        description=(
            "URL de connexion PostgreSQL via Session Pooler (IPv4). "
            "Récupérer dans Supabase Dashboard → Connect → Session pooler. "
            "Format : postgresql://postgres.REF:PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres"
        ),
    )

    # --- Chemins des sources ---
    kaggle_csv_path: Path = Path("data/raw/horror_movies_kaggle.csv")
    imdb_sqlite_path: Path = Path("data/raw/imdb_horror.db")
    spark_data_dir: Path = Path("data/raw/spark_chunks/")

    # --- Seuils qualité ---
    imdb_min_votes: int = Field(1000, ge=0)
    fuzzy_threshold: int = Field(85, ge=0, le=100)

    # --- Selenium ---
    selenium_headless: bool = True
    chrome_binary_path: str | None = None

    # --- Logs ---
    log_level: str = "INFO"
    log_file: Path = Path("logs/horragor.log")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level doit être parmi {allowed}")
        return v.upper()


# Instance globale (singleton)
settings = Settings()
