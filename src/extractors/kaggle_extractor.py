"""
HorRAGor – Extracteur Kaggle / Fichiers Locaux (Polars)
Lecture haute performance des CSV Kaggle contenant les classiques
de l'horreur (cinéma et littérature).

Dataset attendu : horror_movies_kaggle.csv
Colonnes typiques : id, title, original_title, release_date, budget,
                    revenue, overview, vote_average, vote_count,
                    popularity, genres, poster_path, imdb_id
"""
from pathlib import Path
from typing import Any

import polars as pl
from loguru import logger

from src.config import settings

# Colonnes requises dans le CSV Kaggle (après normalisation en minuscules)
_REQUIRED_COLUMNS = {"title", "release_date"}

# Colonnes candidates à lire (toutes les variantes connues de datasets Kaggle horreur)
_COLUMN_MAP: dict[str, str] = {
    "id": "tmdb_id",
    "imdb_id": "imdb_id",
    "title": "title",
    "original_title": "original_title",
    "overview": "overview",
    "description": "overview",       # variante dataset IMDB générique
    "release_date": "release_date",
    "year": "release_date",          # variante "Year" → release_date
    "vote_average": "vote_average",
    "rating": "vote_average",        # variante "Rating"
    "vote_count": "vote_count",
    "votes": "vote_count",           # variante "Votes"
    "popularity": "popularity",
    "poster_path": "poster_path",
    "budget": "budget",
    "revenue": "revenue",
    "runtime": "runtime_minutes",
    "runtime (minutes)": "runtime_minutes",  # variante avec unité
    "genres": "genres",
    "genre": "genres",               # variante singulier
}


class KaggleExtractor:
    """
    Lit un ou plusieurs fichiers CSV Kaggle avec Polars et retourne
    des enregistrements normalisés de films d'horreur.
    """

    def __init__(self, csv_path: Path | None = None) -> None:
        self._path = csv_path or settings.kaggle_csv_path

    def extract(self) -> list[dict[str, Any]]:
        """
        Charge le CSV Kaggle, filtre sur le genre horreur,
        dédoublonne sur (title, release_date) et retourne des dicts.

        Returns:
            Liste de dictionnaires normalisés.
        """
        if not self._path.exists():
            logger.warning(f"Fichier Kaggle introuvable : {self._path}")
            return []

        logger.info(f"Lecture Polars du fichier Kaggle : {self._path}")

        try:
            df = pl.read_csv(
                self._path,
                infer_schema_length=5000,
                null_values=["", "N/A", "NA", "null", "None"],
                ignore_errors=True,
                encoding="utf8-lossy",
            )
        except Exception as exc:
            logger.error(f"Erreur lecture CSV Kaggle : {exc}")
            return []

        logger.info(f"Kaggle : {df.height} lignes brutes chargées ({df.width} colonnes)")

        # Normalisation des noms de colonnes en minuscules pour gérer PascalCase / MAJUSCULES
        df = df.rename({c: c.lower() for c in df.columns})

        # Vérification des colonnes obligatoires
        missing = _REQUIRED_COLUMNS - set(df.columns)
        if missing:
            logger.error(f"Colonnes manquantes dans le CSV Kaggle : {missing}")
            return []

        # Filtrage sur le genre horreur
        df = self._filter_horror(df)
        logger.info(f"Kaggle après filtrage horreur : {df.height} lignes")

        # Normalisation des colonnes disponibles
        df = self._rename_columns(df)

        # Dédoublonnement sur (title, release_date) – critère du cahier des charges
        initial_count = df.height
        df = df.unique(subset=["title", "release_date"], keep="first")
        logger.info(
            f"Kaggle dédoublonnage : {initial_count - df.height} doublons supprimés, "
            f"{df.height} films retenus"
        )

        # Conversion en liste de dicts et ajout du champ source
        records: list[dict[str, Any]] = []
        for row in df.to_dicts():
            records.append(self._normalize(row))

        logger.info(f"Kaggle extraction terminée : {len(records)} films extraits")
        return records

    # ------------------------------------------------------------------
    # Méthodes privées
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_horror(df: pl.DataFrame) -> pl.DataFrame:
        """
        Conserve uniquement les films dont les genres contiennent 'Horror'.
        Fonctionne que la colonne genres soit une chaîne ou une liste JSON.
        """
        if "genres" not in df.columns:
            # Pas de colonne genres → on suppose que le dataset est déjà filtré
            logger.debug("Colonne 'genres' absente, aucun filtrage thématique appliqué.")
            return df

        return df.filter(
            pl.col("genres").cast(pl.Utf8).str.to_lowercase().str.contains("horror")
        )

    @staticmethod
    def _rename_columns(df: pl.DataFrame) -> pl.DataFrame:
        """Renomme les colonnes selon le mapping interne."""
        renames = {old: new for old, new in _COLUMN_MAP.items() if old in df.columns and old != new}
        if renames:
            df = df.rename(renames)
        # Ajouter les colonnes manquantes avec valeur nulle
        for col in _COLUMN_MAP.values():
            if col not in df.columns:
                df = df.with_columns(pl.lit(None).alias(col))
        return df

    @staticmethod
    def _normalize(row: dict[str, Any]) -> dict[str, Any]:
        """Mappe un enregistrement Kaggle vers le schéma interne."""
        # Convertir tmdb_id en int si possible
        tmdb_id = row.get("tmdb_id")
        if tmdb_id is not None:
            try:
                tmdb_id = int(tmdb_id)
            except (ValueError, TypeError):
                tmdb_id = None

        return {
            "source": "kaggle",
            "tmdb_id": tmdb_id,
            "imdb_id": row.get("imdb_id"),
            "title": (str(row.get("title") or "")).strip(),
            "original_title": (str(row.get("original_title") or "")).strip(),
            "overview": row.get("overview"),
            "release_date": row.get("release_date"),
            "vote_average": _to_float(row.get("vote_average")),
            "vote_count": _to_int(row.get("vote_count")),
            "popularity": _to_float(row.get("popularity")),
            "poster_path": row.get("poster_path"),
            "tomatometer_score": None,
            "audience_score": None,
            "critics_consensus": None,
            "budget": _to_int(row.get("budget")),
            "revenue": _to_int(row.get("revenue")),
            "runtime_minutes": _to_int(row.get("runtime_minutes")),
        }


# ---------------------------------------------------------------------------
# Utilitaires de conversion sécurisée
# ---------------------------------------------------------------------------

def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None
