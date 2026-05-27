"""
HorRAGor – Orchestrateur Principal du Pipeline
Exécute les 5 extracteurs en parallèle, applique les transformations,
fusionne les données (MDM) et charge le résultat dans Supabase.

Flux complet :
  1. Extraction parallèle (ThreadPoolExecutor) des 5 sources
  2. Normalisation de chaque enregistrement
  3. Dédoublonnage intra-source
  4. Fusion MDM inter-sources (fuzzy matching)
  5. Filtrage thématique final (horreur uniquement)
  6. Export Parquet (jeu de données Gold)
  7. Chargement dans Supabase

Usage :
  python -m src.pipeline
  horragor-pipeline           # via le script défini dans pyproject.toml
"""
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from src.config import settings
from src.extractors.imdb_extractor import IMDBExtractor
from src.extractors.kaggle_extractor import KaggleExtractor
from src.extractors.rotten_tomatoes_scraper import RottenTomatoesScraper
from src.extractors.spark_extractor import SparkExtractor
from src.extractors.tmdb_extractor import TMDBExtractor
from src.loaders.supabase_loader import SupabaseLoader
from src.transformers.deduplicator import deduplicate
from src.transformers.merger import MDMMerger
from src.transformers.normalizer import normalize_record

# ---------------------------------------------------------------------------
# Configuration du logger
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    log_dir = settings.log_file.parent
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level, colorize=True,
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
    logger.add(
        settings.log_file,
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Extracteurs individuels (wrappés pour ThreadPoolExecutor)
# ---------------------------------------------------------------------------

def _run_tmdb() -> list[dict[str, Any]]:
    logger.info("━━━ [TMDB] Démarrage extraction ━━━")
    return TMDBExtractor().extract()


def _run_rotten_tomatoes(max_movies: int = 50) -> list[dict[str, Any]]:
    logger.info("━━━ [Rotten Tomatoes] Démarrage scraping ━━━")
    return RottenTomatoesScraper().extract(max_movies=max_movies)


def _run_kaggle() -> list[dict[str, Any]]:
    logger.info("━━━ [Kaggle/Polars] Démarrage lecture CSV ━━━")
    return KaggleExtractor().extract()


def _run_imdb() -> list[dict[str, Any]]:
    logger.info("━━━ [IMDB/SQLite] Démarrage extraction ━━━")
    return IMDBExtractor().extract()


def _run_spark() -> list[dict[str, Any]]:
    logger.info("━━━ [PySpark] Démarrage extraction Big Data ━━━")
    return SparkExtractor().extract()


_EXTRACTORS = {
    "tmdb": _run_tmdb,
    "rotten_tomatoes": _run_rotten_tomatoes,
    "kaggle": _run_kaggle,
    "imdb": _run_imdb,
    "spark": _run_spark,
}

# PySpark ne supporte pas bien le multithreading → lancer séparément
_SEQUENTIAL_EXTRACTORS = {"spark"}


# ---------------------------------------------------------------------------
# Étapes du pipeline
# ---------------------------------------------------------------------------

def extract_all(skip_sources: set[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    """
    Lance les extracteurs en parallèle (sauf Spark) et retourne
    un dictionnaire {source_name: [records]}.
    """
    results: dict[str, list[dict[str, Any]]] = {}
    skip = skip_sources or set()

    # Extraction parallèle (sans Spark)
    parallel_extractors = {k: v for k, v in _EXTRACTORS.items()
                           if k not in _SEQUENTIAL_EXTRACTORS and k not in skip}
    with ThreadPoolExecutor(max_workers=len(parallel_extractors), thread_name_prefix="extractor") as executor:
        futures = {executor.submit(fn): name for name, fn in parallel_extractors.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                records = future.result()
                results[name] = records
                logger.info(f"[{name.upper()}] {len(records)} enregistrements bruts récupérés")
            except Exception as exc:
                logger.error(f"[{name.upper()}] Échec de l'extraction : {exc}")
                results[name] = []

    # Extraction séquentielle (Spark)
    for name in _SEQUENTIAL_EXTRACTORS:
        try:
            records = _EXTRACTORS[name]()
            results[name] = records
            logger.info(f"[{name.upper()}] {len(records)} enregistrements bruts récupérés")
        except Exception as exc:
            logger.error(f"[{name.upper()}] Échec de l'extraction Spark : {exc}")
            results[name] = []

    return results


def normalize_and_deduplicate(
    raw_by_source: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """
    Normalise et dédoublonne chaque source, puis concatène tout.
    """
    all_records: list[dict[str, Any]] = []
    for source_name, records in raw_by_source.items():
        normalized = [normalize_record(r) for r in records]
        deduped = deduplicate(normalized, source_label=source_name)
        all_records.extend(deduped)
        logger.info(f"[{source_name.upper()}] Après norm+dedup : {len(deduped)} records")
    return all_records


def filter_horror_only(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Filtrage thématique final : ne garder que les films d'horreur/gore.
    Vérifie la présence du terme 'horror' dans les genres ou le titre.
    """
    horror_keywords = {"horror", "gore", "horreur", "épouvante", "slasher"}

    def is_horror(record: dict[str, Any]) -> bool:
        genres_str = str(record.get("genres") or "").lower()
        title_str = str(record.get("title") or "").lower()
        overview_str = str(record.get("overview") or "").lower()
        source_str = record.get("source", "")

        # Si extrait depuis une source déjà filtrée sur Horror → conserver
        if source_str in ("tmdb", "imdb", "spark"):
            return True  # Ces extracteurs filtrent déjà en amont

        # Vérification sur les genres
        if any(kw in genres_str for kw in horror_keywords):
            return True

        # Dernier recours : titre ou synopsis
        text = f"{title_str} {overview_str}"
        return any(kw in text for kw in horror_keywords)

    filtered = [r for r in records if is_horror(r)]
    removed = len(records) - len(filtered)
    logger.info(f"Filtrage horreur : {removed} films hors-sujet exclus, {len(filtered)} conservés")
    return filtered


def export_parquet(gold_records: list[dict[str, Any]], output_path: Path) -> None:
    """
    Exporte le jeu de données Gold au format Parquet pour vérification.

    Args:
        gold_records: liste de dicts constituant la couche Gold.
        output_path: chemin du fichier Parquet à créer.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Suppression des clés internes (préfixées par _)
    clean_records = [
        {k: v for k, v in r.items() if not k.startswith("_")}
        for r in gold_records
    ]

    df = pd.DataFrame(clean_records)

    # Typage explicite des colonnes pour Arrow
    numeric_cols = ["tmdb_id", "vote_count", "runtime_minutes", "budget", "revenue"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    float_cols = ["vote_average", "popularity", "tomatometer_score", "audience_score"]
    for col in float_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df.to_parquet(output_path, index=False, engine="pyarrow")
    logger.info(f"Export Parquet Gold : {len(df)} films → {output_path}")


# ---------------------------------------------------------------------------
# Pipeline complet
# ---------------------------------------------------------------------------

def run_pipeline(
    load_to_supabase: bool = True,
    export_gold: bool = True,
    skip_sources: set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Exécute le pipeline d'ingestion complet.

    Args:
        load_to_supabase: si True, charge les données dans Supabase.
        export_gold: si True, exporte le jeu de données Gold en Parquet.
        skip_sources: ensemble de noms de sources à ignorer (ex: {"rotten_tomatoes"}).

    Returns:
        Liste des entités Gold (pour tests et démo live).
    """
    logger.info("═══════════════════════════════════════════")
    logger.info("   HorRAGor – Pipeline d'ingestion Partie 1")
    logger.info("═══════════════════════════════════════════")

    # Étape 1 : Extraction parallèle
    logger.info("ÉTAPE 1/5 – Extraction des 5 sources")
    raw_by_source = extract_all(skip_sources=skip_sources)
    total_raw = sum(len(v) for v in raw_by_source.values())
    logger.info(f"Total brut : {total_raw} enregistrements depuis {len(raw_by_source)} sources")

    # Étape 2 : Normalisation + dédoublonnage intra-source
    logger.info("ÉTAPE 2/5 – Normalisation et dédoublonnage intra-source")
    all_normalized = normalize_and_deduplicate(raw_by_source)
    logger.info(f"Après norm+dedup : {len(all_normalized)} enregistrements")

    # Étape 3 : Fusion MDM inter-sources
    logger.info("ÉTAPE 3/5 – Fusion MDM inter-sources (fuzzy matching)")
    merger = MDMMerger()
    gold_records = merger.merge(all_normalized)
    logger.info(f"Après fusion MDM : {len(gold_records)} entités uniques")

    # Étape 4 : Filtrage thématique final
    logger.info("ÉTAPE 4/5 – Filtrage thématique horreur")
    gold_records = filter_horror_only(gold_records)

    # Étape 5a : Export Parquet
    if export_gold:
        logger.info("ÉTAPE 5/5 – Export Parquet (Gold)")
        gold_path = Path("data/gold/horror_gold.parquet")
        export_parquet(gold_records, gold_path)

    # Étape 5b : Chargement Supabase
    if load_to_supabase:
        logger.info("ÉTAPE 5/5 – Chargement dans Supabase")
        loader = SupabaseLoader()
        loader.create_tables()
        loader.load(gold_records)

    logger.info("═══════════════════════════════════════════")
    logger.info(f"   Pipeline terminé – {len(gold_records)} films Gold")
    logger.info("═══════════════════════════════════════════")

    return gold_records


def main() -> None:
    """Point d'entrée CLI."""
    import argparse

    parser = argparse.ArgumentParser(
        description="HorRAGor – Pipeline d'ingestion données horreur"
    )
    parser.add_argument(
        "--no-supabase",
        action="store_true",
        help="Désactive le chargement dans Supabase (mode dry-run)",
    )
    parser.add_argument(
        "--no-parquet",
        action="store_true",
        help="Désactive l'export Parquet",
    )
    parser.add_argument(
        "--no-rt",
        action="store_true",
        help="Désactive le scraping Rotten Tomatoes (Selenium)",
    )
    args = parser.parse_args()

    _setup_logging()
    run_pipeline(
        load_to_supabase=not args.no_supabase,
        export_gold=not args.no_parquet,
        skip_sources={"rotten_tomatoes"} if args.no_rt else None,
    )


if __name__ == "__main__":
    main()
