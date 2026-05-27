"""
HorRAGor – Extracteur TMDB (Source Maîtresse)
Interroge l'API The Movie Database pour récupérer les métadonnées
des films d'horreur (genre ID 27).

Champs extraits : tmdb_id, title, original_title, overview,
                  release_date, vote_average, popularity, poster_path
"""
import time
from typing import Any

import requests
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.config import settings


# ID du genre "Horreur" dans TMDB
TMDB_HORROR_GENRE_ID = 27
_TMDB_DISCOVER_URL = f"{settings.tmdb_base_url}/discover/movie"
_TMDB_CREDITS_URL = f"{settings.tmdb_base_url}/movie/{{movie_id}}/credits"


class TMDBExtractor:
    """Interroge l'API TMDB et retourne des films d'horreur normalisés."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        self._params_base: dict[str, Any] = {
            "api_key": settings.tmdb_api_key,
            "with_genres": TMDB_HORROR_GENRE_ID,
            "language": "fr-FR",
            "sort_by": "popularity.desc",
            "include_adult": "false",
        }

    @retry(
        retry=retry_if_exception_type(requests.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _get_page(self, page: int) -> dict[str, Any]:
        """Récupère une page de résultats depuis l'API TMDB."""
        params = {**self._params_base, "page": page}
        response = self._session.get(_TMDB_DISCOVER_URL, params=params, timeout=10)
        response.raise_for_status()
        return response.json()

    def extract(self) -> list[dict[str, Any]]:
        """
        Extrait tous les films d'horreur jusqu'à `settings.tmdb_max_pages`.

        Returns:
            Liste de dictionnaires normalisés représentant chaque film.
        """
        records: list[dict[str, Any]] = []

        logger.info("Début extraction TMDB (horreur, genre_id=27)")

        # Récupération de la première page pour connaître le total
        try:
            first_page = self._get_page(1)
        except requests.RequestException as exc:
            logger.error(f"Impossible de contacter l'API TMDB : {exc}")
            return records

        total_pages = min(first_page.get("total_pages", 1), settings.tmdb_max_pages)
        logger.info(f"TMDB : {first_page.get('total_results', 0)} films sur {total_pages} page(s)")

        for page_num in range(1, total_pages + 1):
            try:
                data = self._get_page(page_num) if page_num > 1 else first_page
                for movie in data.get("results", []):
                    records.append(self._normalize(movie))
                logger.debug(f"TMDB page {page_num}/{total_pages} : {len(data.get('results', []))} films")
                # Respect du rate-limit TMDB (40 req/10s)
                time.sleep(0.25)
            except requests.HTTPError as exc:
                logger.warning(f"TMDB page {page_num} ignorée après retries : {exc}")
            except Exception as exc:
                logger.error(f"Erreur inattendue TMDB page {page_num} : {exc}")

        logger.info(f"TMDB extraction terminée : {len(records)} films extraits")
        return records

    # ------------------------------------------------------------------
    # Helpers privés
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
        """Mappe un objet brut TMDB vers le schéma interne."""
        return {
            "source": "tmdb",
            "tmdb_id": raw.get("id"),
            "imdb_id": None,  # Disponible via /movie/{id}/external_ids
            "title": (raw.get("title") or "").strip(),
            "original_title": (raw.get("original_title") or "").strip(),
            "overview": (raw.get("overview") or "").strip(),
            "release_date": raw.get("release_date"),   # Format YYYY-MM-DD (ISO 8601 natif)
            "vote_average": raw.get("vote_average"),    # Échelle 0-10
            "vote_count": raw.get("vote_count"),
            "popularity": raw.get("popularity"),
            "poster_path": raw.get("poster_path"),
            "tomatometer_score": None,
            "audience_score": None,
            "critics_consensus": None,
            "budget": None,
            "revenue": None,
            "runtime_minutes": raw.get("runtime"),
        }
