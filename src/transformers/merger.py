"""
HorRAGor – Fusion MDM (Master Data Management)
Consolide les enregistrements de 5 sources en une "Source de Vérité" unique.

Logique de priorité décroissante (cahier des charges) :
  Source Maîtresse : TMDB   → identifiants et titres officiels
  Enrichissement 1 : RT     → tomatometer, audience_score, critics_consensus
  Enrichissement 2 : Kaggle → budget, revenue, synopsis alternatif
  Enrichissement 3 : IMDB   → vote_average, vote_count, runtime
  Enrichissement 4 : Spark  → données textuelles supplémentaires

Méthodes de réconciliation (matching) :
  Niveau 1 : correspondance exacte sur tmdb_id
  Niveau 2 : correspondance exacte sur imdb_id
  Niveau 3 : fuzzy matching sur (titre normalisé + année)
             via algorithme token_sort_ratio (RapidFuzz / Levenshtein)
"""
from typing import Any

from loguru import logger
from rapidfuzz import fuzz

from src.config import settings
from src.transformers.normalizer import normalize_title, normalize_date

# Priorité des sources : index plus bas = priorité plus haute
_SOURCE_PRIORITY: dict[str, int] = {
    "tmdb": 0,
    "rotten_tomatoes": 1,
    "kaggle": 2,
    "imdb": 3,
    "spark": 4,
}

# Champs enrichissables par source (premier non-None gagne)
_ENRICHMENT_FIELDS_BY_SOURCE: dict[str, list[str]] = {
    "rotten_tomatoes": ["tomatometer_score", "audience_score", "critics_consensus"],
    "kaggle": ["budget", "revenue", "overview"],
    "imdb": ["vote_average", "vote_count", "runtime_minutes"],
    "spark": ["overview", "popularity"],
}


def _extract_year(date_str: str | None) -> int | None:
    if not date_str:
        return None
    try:
        return int(date_str[:4])
    except (ValueError, TypeError):
        return None


class MDMMerger:
    """
    Fusionne des enregistrements multi-sources en entités uniques.
    """

    def __init__(self, fuzzy_threshold: int | None = None) -> None:
        self._threshold = fuzzy_threshold or settings.fuzzy_threshold
        # Index de lookup construits lors de la fusion
        self._index_tmdb: dict[int, dict[str, Any]] = {}
        self._index_imdb: dict[str, dict[str, Any]] = {}
        # (title_norm, year) → record maître
        self._index_title_year: dict[tuple[str | None, int | None], dict[str, Any]] = {}

    def merge(self, all_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Fusionne tous les enregistrements toutes sources confondues.

        Args:
            all_records: liste concaténée de tous les extracteurs,
                         déjà normalisés et dédoublonnés intra-source.

        Returns:
            Liste de dicts "Gold" — entités uniques enrichies de toutes sources.
        """
        # Tri par priorité de source (TMDB d'abord)
        sorted_records = sorted(
            all_records,
            key=lambda r: _SOURCE_PRIORITY.get(r.get("source", ""), 99),
        )

        logger.info(f"MDM : fusion de {len(sorted_records)} enregistrements toutes sources")

        for record in sorted_records:
            source = record.get("source", "unknown")
            master = self._find_master(record)

            if master is None:
                # Nouveau film : créer une entrée maître
                master = self._create_master(record)
                self._register(master)
            else:
                # Film déjà connu : enrichir les champs manquants
                self._enrich(master, record, source)

        gold = list(self._index_tmdb.values())

        # Ajouter les films sans tmdb_id indexés par imdb_id
        tmdb_covered_imdb = {r.get("imdb_id") for r in gold if r.get("imdb_id")}
        for imdb_id, r in self._index_imdb.items():
            if r.get("imdb_id") not in tmdb_covered_imdb:
                gold.append(r)

        # Ajouter les films sans tmdb_id ni imdb_id indexés par (titre, année)
        covered_ty = {
            (normalize_title(r.get("title")), _extract_year(r.get("release_date")))
            for r in gold
        }
        for key_ty, r in self._index_title_year.items():
            if key_ty not in covered_ty:
                gold.append(r)

        # Gestion des synopsis manquants : fallback vers la source suivante
        for record in gold:
            self._apply_overview_fallback(record)

        logger.info(f"MDM terminé : {len(gold)} entités Gold générées")
        return gold

    # ------------------------------------------------------------------
    # Recherche d'un master existant
    # ------------------------------------------------------------------

    def _find_master(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """
        Retourne l'enregistrement maître correspondant (ou None).
        Niveau 1 → tmdb_id, Niveau 2 → imdb_id, Niveau 3 → fuzzy.
        """
        # Niveau 1 : tmdb_id exact
        tmdb_id = record.get("tmdb_id")
        if tmdb_id is not None:
            master = self._index_tmdb.get(int(tmdb_id))
            if master:
                return master

        # Niveau 2 : imdb_id exact
        imdb_id = record.get("imdb_id")
        if imdb_id is not None:
            master = self._index_imdb.get(str(imdb_id))
            if master:
                return master

        # Niveau 3 : fuzzy matching (titre + année)
        return self._fuzzy_match(record)

    def _fuzzy_match(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """
        Cherche un enregistrement maître similaire via token_sort_ratio.
        Retourne le master si le score dépasse le seuil configuré.
        """
        title_q = normalize_title(record.get("title"))
        year_q = _extract_year(record.get("release_date"))

        if not title_q:
            return None

        best_score = 0
        best_master = None

        for (title_m, year_m), master in self._index_title_year.items():
            if title_m is None:
                continue
            # Bonus si l'année correspond exactement
            if year_m is not None and year_q is not None and abs(year_m - year_q) > 1:
                continue  # Années trop éloignées → skip rapide

            score = fuzz.token_sort_ratio(title_q, title_m)
            if score > best_score:
                best_score = score
                best_master = master

        if best_score >= self._threshold:
            logger.debug(
                f"Fuzzy match trouvé : '{record.get('title')}' ({year_q}) "
                f"↔ '{best_master.get('title')}' ({_extract_year(best_master.get('release_date'))}) "
                f"[score={best_score}]"
            )
            return best_master

        return None

    # ------------------------------------------------------------------
    # Création et enrichissement
    # ------------------------------------------------------------------

    @staticmethod
    def _create_master(record: dict[str, Any]) -> dict[str, Any]:
        """Crée un enregistrement maître à partir d'un enregistrement source."""
        master = {**record}
        # Clé interne de matching (non persistée)
        master["_normalized_title"] = normalize_title(record.get("title"))
        # Liste des sources contributrices
        master["_sources"] = [record.get("source", "unknown")]
        return master

    @staticmethod
    def _enrich(master: dict[str, Any], record: dict[str, Any], source: str) -> None:
        """
        Enrichit le master avec les champs non-nuls du record secondaire.
        Respecte la hiérarchie des sources : les champs du master (priorité haute)
        ne sont pas écrasés si déjà renseignés.
        """
        fields_for_source = _ENRICHMENT_FIELDS_BY_SOURCE.get(source, [])

        for field in fields_for_source:
            if master.get(field) is None and record.get(field) is not None:
                master[field] = record[field]

        # Champs universels : compléter si absent dans le master
        universal_fields = ["overview", "vote_average", "vote_count",
                            "runtime_minutes", "budget", "revenue", "poster_path"]
        for field in universal_fields:
            if master.get(field) is None and record.get(field) is not None:
                master[field] = record[field]

        # Ajouter la source contributrice
        if source not in master.get("_sources", []):
            master.setdefault("_sources", []).append(source)

        # Mettre à jour les identifiants croisés
        if master.get("tmdb_id") is None and record.get("tmdb_id") is not None:
            master["tmdb_id"] = record["tmdb_id"]
        if master.get("imdb_id") is None and record.get("imdb_id") is not None:
            master["imdb_id"] = record["imdb_id"]

    def _register(self, master: dict[str, Any]) -> None:
        """Indexe un nouveau master dans les trois index de lookup."""
        tmdb_id = master.get("tmdb_id")
        if tmdb_id is not None:
            self._index_tmdb[int(tmdb_id)] = master

        imdb_id = master.get("imdb_id")
        if imdb_id is not None:
            self._index_imdb[str(imdb_id)] = master

        title_norm = normalize_title(master.get("title"))
        year = _extract_year(master.get("release_date"))
        self._index_title_year[(title_norm, year)] = master

    # ------------------------------------------------------------------
    # Fallback synopsis
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_overview_fallback(record: dict[str, Any]) -> None:
        """
        Si TMDB n'a pas fourni de synopsis, bascule sur la source de priorité
        suivante (Kaggle puis Spark), comme spécifié dans le cahier des charges.
        Note : le fallback est déjà appliqué via _enrich(), cette méthode
        sert de vérification finale et de log explicite.
        """
        if record.get("overview") is None:
            logger.debug(
                f"Pas de synopsis pour '{record.get('title')}' "
                f"(sources: {record.get('_sources', [])})"
            )
