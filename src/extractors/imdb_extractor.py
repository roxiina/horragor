"""
HorRAGor – Extracteur IMDB / SQLite
Extraction depuis une base SQLite locale construite à partir des fichiers
IMDB Non-Commercial Datasets (title.basics.tsv + title.ratings.tsv).

Requête : jointure title_basics ↔ title_ratings filtrée sur genre Horror
Seuil qualité : numVotes >= settings.imdb_min_votes

Colonnes extraites : tconst (imdb_id), primaryTitle, originalTitle,
                     startYear, averageRating, numVotes
"""
import sqlite3
from pathlib import Path
from typing import Any

from loguru import logger

from src.config import settings

# DDL pour créer la base SQLite à partir des TSV IMDB (utilisé par build_imdb_db.py)
_CREATE_TABLE_BASICS = """
CREATE TABLE IF NOT EXISTS title_basics (
    tconst        TEXT PRIMARY KEY,
    titleType     TEXT,
    primaryTitle  TEXT,
    originalTitle TEXT,
    isAdult       INTEGER,
    startYear     TEXT,
    endYear       TEXT,
    runtimeMinutes TEXT,
    genres        TEXT
);
"""

_CREATE_TABLE_RATINGS = """
CREATE TABLE IF NOT EXISTS title_ratings (
    tconst        TEXT PRIMARY KEY,
    averageRating REAL,
    numVotes      INTEGER,
    FOREIGN KEY (tconst) REFERENCES title_basics(tconst)
);
"""

_CREATE_INDEX_GENRES = """
CREATE INDEX IF NOT EXISTS idx_genres ON title_basics(genres);
"""

# Requête principale : jointure filtrée sur Horror & seuil de votes
_QUERY_HORROR = """
SELECT
    b.tconst          AS imdb_id,
    b.primaryTitle    AS title,
    b.originalTitle   AS original_title,
    b.startYear       AS start_year,
    b.runtimeMinutes  AS runtime_minutes,
    r.averageRating   AS vote_average,
    r.numVotes        AS vote_count
FROM title_basics AS b
INNER JOIN title_ratings AS r ON b.tconst = r.tconst
WHERE b.genres LIKE '%Horror%'
  AND b.titleType = 'movie'
  AND r.numVotes >= :min_votes
  AND b.startYear != '\\N'
ORDER BY r.numVotes DESC;
"""


class IMDBExtractor:
    """
    Extrait les films d'horreur depuis une base SQLite IMDB locale.
    Si la base n'existe pas, propose de la construire à partir des TSV.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or settings.imdb_sqlite_path

    def extract(self) -> list[dict[str, Any]]:
        """
        Exécute la requête de jointure IMDB et retourne des dicts normalisés.

        Returns:
            Liste de dictionnaires représentant les films d'horreur IMDB.
        """
        if not self._db_path.exists():
            logger.warning(
                f"Base IMDB introuvable : {self._db_path}. "
                "Lancez `python scripts/build_imdb_db.py` pour la construire."
            )
            return []

        logger.info(f"Connexion SQLite IMDB : {self._db_path}")
        records: list[dict[str, Any]] = []

        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(_QUERY_HORROR, {"min_votes": settings.imdb_min_votes})
            rows = cursor.fetchall()

            for row in rows:
                records.append(self._normalize(dict(row)))

            conn.close()

        except sqlite3.Error as exc:
            logger.error(f"Erreur SQLite IMDB : {exc}")

        logger.info(f"IMDB extraction terminée : {len(records)} films extraits")
        return records

    # ------------------------------------------------------------------
    # Méthodes privées
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(row: dict[str, Any]) -> dict[str, Any]:
        """Mappe un enregistrement SQLite IMDB vers le schéma interne."""
        start_year = row.get("start_year")
        # IMDB stocke l'année comme texte (ex : "2019") ou "\N"
        release_date = None
        if start_year and start_year != r"\N":
            try:
                release_date = f"{int(start_year)}-01-01"
            except ValueError:
                pass

        runtime_raw = row.get("runtime_minutes")
        runtime = None
        if runtime_raw and runtime_raw != r"\N":
            try:
                runtime = int(runtime_raw)
            except ValueError:
                pass

        return {
            "source": "imdb",
            "tmdb_id": None,
            "imdb_id": row.get("imdb_id"),
            "title": (str(row.get("title") or "")).strip(),
            "original_title": (str(row.get("original_title") or "")).strip(),
            "overview": None,
            "release_date": release_date,
            "vote_average": row.get("vote_average"),   # Échelle 0-10 (IMDB natif)
            "vote_count": row.get("vote_count"),
            "popularity": None,
            "poster_path": None,
            "tomatometer_score": None,
            "audience_score": None,
            "critics_consensus": None,
            "budget": None,
            "revenue": None,
            "runtime_minutes": runtime,
        }
