"""
HorRAGor – Extracteur PySpark (Big Data)
Traitement massivement parallèle des fichiers CSV Kaggle splittés
(plusieurs fichiers partitionnés dans un répertoire).

Chaque partition peut être un fichier CSV compressé ou non.
PySpark filtre sur le genre Horror et retourne les enregistrements
fusionnés en une liste Python pour l'étape de réconciliation MDM.
"""
from pathlib import Path
from typing import Any

from loguru import logger

from src.config import settings

# Colonnes Spark à mapper vers le schéma interne
_SPARK_COLUMN_MAP: dict[str, str] = {
    "id": "tmdb_id",
    "imdb_id": "imdb_id",
    "title": "title",
    "original_title": "original_title",
    "overview": "overview",
    "release_date": "release_date",
    "vote_average": "vote_average",
    "vote_count": "vote_count",
    "popularity": "popularity",
    "poster_path": "poster_path",
    "budget": "budget",
    "revenue": "revenue",
    "runtime": "runtime_minutes",
    "genres": "genres",
}


def _build_spark_session():
    """
    Initialise ou récupère une SparkSession avec les paramètres optimisés
    pour un usage sur un poste de développement.
    """
    try:
        from pyspark.sql import SparkSession  # type: ignore
    except ImportError:
        raise RuntimeError(
            "PySpark n'est pas installé. Ajoutez 'pyspark' aux dépendances."
        )

    return (
        SparkSession.builder
        .appName("HorRAGor-BigData-Extractor")
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.driver.memory", "2g")
        .config("spark.executor.memory", "2g")
        .config("spark.ui.showConsoleProgress", "false")
        # Journalisation Spark moins verbeuse
        .config("spark.eventLog.enabled", "false")
        .getOrCreate()
    )


class SparkExtractor:
    """
    Charge les fichiers CSV splittés avec PySpark, filtre Genre=Horror
    et retourne une liste de dicts compatibles avec le pipeline MDM.
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or settings.spark_data_dir

    def extract(self) -> list[dict[str, Any]]:
        """
        Lance une SparkSession, charge tous les CSV du répertoire
        `spark_data_dir`, filtre sur Horror et retourne des dicts normalisés.

        Returns:
            Liste de dictionnaires représentant les films d'horreur.
        """
        if not self._data_dir.exists() or not any(self._data_dir.iterdir()):
            logger.warning(
                f"Répertoire Spark vide ou inexistant : {self._data_dir}. "
                "Placez les fichiers CSV splittés Kaggle dans ce dossier."
            )
            return []

        logger.info(f"Démarrage SparkSession – lecture de {self._data_dir}")
        spark = None
        records: list[dict[str, Any]] = []

        try:
            from pyspark.sql import functions as F  # type: ignore

            spark = _build_spark_session()
            spark.sparkContext.setLogLevel("WARN")

            # Lecture de tous les CSV du répertoire (splitté ou non)
            df = spark.read.csv(
                str(self._data_dir / "*.csv"),
                header=True,
                inferSchema=True,
                encoding="UTF-8",
            )

            logger.info(f"Spark : {df.count()} lignes brutes chargées")

            # Filtrer sur le genre Horror (colonne 'genres' peut contenir une liste en JSON)
            if "genres" in df.columns:
                df = df.filter(
                    F.lower(F.col("genres")).contains("horror")
                )
            else:
                logger.warning("Colonne 'genres' absente, pas de filtrage Spark.")

            # Renommage selon le mapping interne
            for old, new in _SPARK_COLUMN_MAP.items():
                if old in df.columns and old != new:
                    df = df.withColumnRenamed(old, new)

            # Sélection des colonnes présentes uniquement
            available_cols = [c for c in _SPARK_COLUMN_MAP.values() if c in df.columns]
            df = df.select(*available_cols)

            # Dédoublonnage intra-Spark
            initial_count = df.count()
            df = df.dropDuplicates(["title", "release_date"])
            logger.info(
                f"Spark après dédoublonnage : {initial_count - df.count()} doublons, "
                f"{df.count()} films retenus"
            )

            # Conversion en liste Python (collect)
            logger.info("Spark collect() → conversion en liste Python")
            rows = df.collect()
            for row in rows:
                records.append(self._normalize(row.asDict()))

        except Exception as exc:
            logger.error(f"Erreur PySpark : {exc}")
        finally:
            if spark:
                spark.stop()

        logger.info(f"Spark extraction terminée : {len(records)} films extraits")
        return records

    # ------------------------------------------------------------------
    # Helpers privés
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(row: dict[str, Any]) -> dict[str, Any]:
        """Mappe un enregistrement Spark vers le schéma interne."""
        tmdb_id = row.get("tmdb_id")
        try:
            tmdb_id = int(tmdb_id) if tmdb_id is not None else None
        except (ValueError, TypeError):
            tmdb_id = None

        return {
            "source": "spark",
            "tmdb_id": tmdb_id,
            "imdb_id": row.get("imdb_id"),
            "title": (str(row.get("title") or "")).strip(),
            "original_title": (str(row.get("original_title") or "")).strip(),
            "overview": row.get("overview"),
            "release_date": row.get("release_date"),
            "vote_average": _safe_float(row.get("vote_average")),
            "vote_count": _safe_int(row.get("vote_count")),
            "popularity": _safe_float(row.get("popularity")),
            "poster_path": row.get("poster_path"),
            "tomatometer_score": None,
            "audience_score": None,
            "critics_consensus": None,
            "budget": _safe_int(row.get("budget")),
            "revenue": _safe_int(row.get("revenue")),
            "runtime_minutes": _safe_int(row.get("runtime_minutes")),
        }


def _safe_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def _safe_int(v: Any) -> int | None:
    try:
        return int(float(v)) if v is not None else None
    except (ValueError, TypeError):
        return None
