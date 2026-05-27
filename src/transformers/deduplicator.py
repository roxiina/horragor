"""
HorRAGor – Dédoublonnage intra-source
Supprime les doublons au sein d'une même source avant la fusion MDM.

Stratégie :
  1. Si tmdb_id présent → garder la première occurrence (la plus complète)
  2. Sinon, si imdb_id présent → idem
  3. Sinon → grouper par (title normalisé, année) et garder le meilleur
"""
from typing import Any

from loguru import logger

from src.transformers.normalizer import normalize_title, normalize_date


def _extract_year(date_str: str | None) -> int | None:
    """Extrait l'année d'une date ISO 8601 ou retourne None."""
    if not date_str:
        return None
    try:
        return int(date_str[:4])
    except (ValueError, TypeError):
        return None


def _completeness_score(record: dict[str, Any]) -> int:
    """
    Score de complétude d'un enregistrement :
    +1 par champ critique non-nul.
    Utilisé pour choisir le "meilleur" doublon.
    """
    critical_fields = [
        "overview", "release_date", "vote_average", "vote_count",
        "poster_path", "runtime_minutes",
    ]
    return sum(1 for f in critical_fields if record.get(f) is not None)


def deduplicate(records: list[dict[str, Any]], source_label: str = "") -> list[dict[str, Any]]:
    """
    Dédoublonne une liste d'enregistrements d'une même source.

    Priorité de déduplication :
      1. tmdb_id (si non None)
      2. imdb_id (si non None)
      3. (titre normalisé, année) — fuzzy-safe

    En cas de conflit, conserve l'enregistrement le plus complet.

    Args:
        records: liste de dicts déjà normalisés.
        source_label: nom de la source (pour les logs).

    Returns:
        Liste dédoublonnée.
    """
    initial = len(records)
    seen_tmdb: dict[int, dict[str, Any]] = {}
    seen_imdb: dict[str, dict[str, Any]] = {}
    seen_title_year: dict[tuple[str | None, int | None], dict[str, Any]] = {}

    for record in records:
        tmdb_id = record.get("tmdb_id")
        imdb_id = record.get("imdb_id")
        title_norm = normalize_title(record.get("title"))
        year = _extract_year(record.get("release_date"))

        # Niveau 1 : tmdb_id
        if tmdb_id is not None:
            key = int(tmdb_id)
            existing = seen_tmdb.get(key)
            if existing is None or _completeness_score(record) > _completeness_score(existing):
                seen_tmdb[key] = record
            continue

        # Niveau 2 : imdb_id
        if imdb_id is not None:
            existing = seen_imdb.get(str(imdb_id))
            if existing is None or _completeness_score(record) > _completeness_score(existing):
                seen_imdb[str(imdb_id)] = record
            continue

        # Niveau 3 : (titre normalisé, année)
        key_ty = (title_norm, year)
        existing = seen_title_year.get(key_ty)
        if existing is None or _completeness_score(record) > _completeness_score(existing):
            seen_title_year[key_ty] = record

    # Fusion des trois dictionnaires : tmdb_id prime sur imdb_id, etc.
    deduplicated: list[dict[str, Any]] = []
    deduplicated.extend(seen_tmdb.values())

    # Ajouter les enregistrements sans tmdb_id depuis seen_imdb
    tmdb_covered_imdb = {r.get("imdb_id") for r in seen_tmdb.values() if r.get("imdb_id")}
    for imdb_id, record in seen_imdb.items():
        if imdb_id not in tmdb_covered_imdb:
            deduplicated.append(record)

    # Ajouter les enregistrements sans tmdb_id ni imdb_id depuis seen_title_year
    existing_title_years = {
        (normalize_title(r.get("title")), _extract_year(r.get("release_date")))
        for r in deduplicated
    }
    for key_ty, record in seen_title_year.items():
        if key_ty not in existing_title_years:
            deduplicated.append(record)

    removed = initial - len(deduplicated)
    if source_label:
        logger.info(f"Déduplication [{source_label}] : {removed} doublons supprimés, {len(deduplicated)} retenus")

    return deduplicated
