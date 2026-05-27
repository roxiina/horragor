"""
Script utilitaire : construction de la base IMDB SQLite
à partir des fichiers TSV téléchargés depuis https://datasets.imdbws.com/

Usage :
    python scripts/build_imdb_db.py \
        --basics data/raw/title.basics.tsv.gz \
        --ratings data/raw/title.ratings.tsv.gz \
        --output data/raw/imdb_horror.db

Téléchargement des sources :
    https://datasets.imdbws.com/title.basics.tsv.gz
    https://datasets.imdbws.com/title.ratings.tsv.gz
"""
import argparse
import sqlite3
from pathlib import Path

from loguru import logger

_CREATE_TABLE_BASICS = """
CREATE TABLE IF NOT EXISTS title_basics (
    tconst         TEXT PRIMARY KEY,
    titleType      TEXT,
    primaryTitle   TEXT,
    originalTitle  TEXT,
    isAdult        INTEGER,
    startYear      TEXT,
    endYear        TEXT,
    runtimeMinutes TEXT,
    genres         TEXT
);
"""

_CREATE_TABLE_RATINGS = """
CREATE TABLE IF NOT EXISTS title_ratings (
    tconst        TEXT PRIMARY KEY,
    averageRating REAL,
    numVotes      INTEGER
);
"""

_CREATE_INDEX_GENRES = "CREATE INDEX IF NOT EXISTS idx_basics_genres ON title_basics(genres);"
_CREATE_INDEX_TYPE   = "CREATE INDEX IF NOT EXISTS idx_basics_type   ON title_basics(titleType);"


def _open_tsv(path: Path):
    """Ouvre un TSV (compressé .gz ou non) et retourne un générateur de lignes."""
    import gzip, io
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, encoding="utf-8", errors="replace")


def _load_basics(conn: sqlite3.Connection, path: Path, min_votes_filter: bool = True) -> None:
    """Charge title.basics.tsv → table title_basics (films uniquement)."""
    logger.info(f"Chargement title_basics depuis {path}")
    cursor = conn.cursor()
    inserted = 0

    with _open_tsv(path) as f:
        header = f.readline().strip().split("\t")
        idx = {col: i for i, col in enumerate(header)}

        batch = []
        for line in f:
            cols = line.strip().split("\t")
            if len(cols) < len(header):
                continue

            title_type = cols[idx.get("titleType", 0)]
            if title_type != "movie":
                continue  # Filtre précoce : films uniquement

            genres = cols[idx.get("genres", -1)] if "genres" in idx else r"\N"
            if "Horror" not in genres:
                continue  # Filtre précoce : horreur uniquement

            batch.append((
                cols[idx["tconst"]],
                title_type,
                cols[idx.get("primaryTitle", 1)],
                cols[idx.get("originalTitle", 2)],
                cols[idx.get("isAdult", 3)],
                cols[idx.get("startYear", 4)],
                cols[idx.get("endYear", 5)],
                cols[idx.get("runtimeMinutes", 6)],
                genres,
            ))

            if len(batch) >= 5000:
                cursor.executemany(
                    "INSERT OR IGNORE INTO title_basics VALUES (?,?,?,?,?,?,?,?,?)", batch
                )
                inserted += len(batch)
                batch.clear()

        if batch:
            cursor.executemany(
                "INSERT OR IGNORE INTO title_basics VALUES (?,?,?,?,?,?,?,?,?)", batch
            )
            inserted += len(batch)

    conn.commit()
    logger.info(f"title_basics : {inserted} films d'horreur insérés")


def _load_ratings(conn: sqlite3.Connection, path: Path) -> None:
    """Charge title.ratings.tsv → table title_ratings."""
    logger.info(f"Chargement title_ratings depuis {path}")
    cursor = conn.cursor()
    inserted = 0

    with _open_tsv(path) as f:
        f.readline()  # Skip header
        batch = []
        for line in f:
            cols = line.strip().split("\t")
            if len(cols) < 3:
                continue
            batch.append((cols[0], cols[1], cols[2]))
            if len(batch) >= 10000:
                cursor.executemany(
                    "INSERT OR IGNORE INTO title_ratings VALUES (?,?,?)", batch
                )
                inserted += len(batch)
                batch.clear()

        if batch:
            cursor.executemany(
                "INSERT OR IGNORE INTO title_ratings VALUES (?,?,?)", batch
            )
            inserted += len(batch)

    conn.commit()
    logger.info(f"title_ratings : {inserted} entrées insérées")


def build_db(basics_path: Path, ratings_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Création de la base SQLite IMDB → {output_path}")
    conn = sqlite3.connect(output_path)

    conn.execute(_CREATE_TABLE_BASICS)
    conn.execute(_CREATE_TABLE_RATINGS)
    conn.commit()

    _load_basics(conn, basics_path)
    _load_ratings(conn, ratings_path)

    conn.execute(_CREATE_INDEX_GENRES)
    conn.execute(_CREATE_INDEX_TYPE)
    conn.commit()
    conn.close()

    logger.info("Base IMDB SQLite construite avec succès.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Construit la base IMDB SQLite")
    parser.add_argument("--basics",  required=True, type=Path, help="Chemin vers title.basics.tsv(.gz)")
    parser.add_argument("--ratings", required=True, type=Path, help="Chemin vers title.ratings.tsv(.gz)")
    parser.add_argument("--output",  default=Path("data/raw/imdb_horror.db"), type=Path)
    args = parser.parse_args()
    build_db(args.basics, args.ratings, args.output)
