"""
HorRAGor - Loader Supabase (via supabase-py REST API)
Persistence de la couche "Gold" dans Supabase via le client Python REST.

Remplace la connexion SQLAlchemy directe (psycopg2) qui necessite IPv6,
non supporte sur certains reseaux. Le client supabase-py utilise HTTPS (IPv4).

Tables cibles : movies, genres, movie_genres, ratings, rt_details, ingestion_logs
"""
import json
import re
import uuid
from typing import Any

from loguru import logger
from supabase import create_client, Client

from src.config import settings


def _parse_genres(raw: Any) -> list[str]:
    if not raw:
        return []
    raw_str = str(raw)
    if raw_str.startswith("["):
        try:
            items = json.loads(raw_str)
            return [item["name"] for item in items if "name" in item]
        except (json.JSONDecodeError, KeyError):
            pass
    return [g.strip() for g in re.split(r"[,|]", raw_str) if g.strip()]


def _safe_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


class SupabaseLoader:
    """
    Charge les enregistrements Gold dans Supabase via le client REST supabase-py.
    Utilise des upserts pour garantir l idempotence du pipeline.
    """

    def __init__(self) -> None:
        self._client: Client = create_client(
            settings.supabase_url,
            settings.supabase_key,
        )

    def create_tables(self) -> None:
        """Verifie que Supabase est accessible et que les tables existent."""
        try:
            self._client.table("movies").select("id").limit(1).execute()
            logger.info("Supabase accessible - tables verifiees via REST API.")
        except Exception as exc:
            logger.error(f"Impossible d atteindre Supabase : {exc}")
            raise

    def load(self, gold_records: list[dict[str, Any]], batch_size: int = 50) -> None:
        """Insere ou met a jour les enregistrements Gold dans Supabase."""
        if not gold_records:
            logger.warning("Loader : aucun enregistrement Gold a charger.")
            return
        logger.info(f"Chargement de {len(gold_records)} enregistrements Gold dans Supabase...")
        success = 0
        errors = 0
        for i, record in enumerate(gold_records):
            try:
                self._upsert_record(record)
                success += 1
            except Exception as exc:
                errors += 1
                logger.error(f"Erreur upsert '{record.get('title')}' : {exc}")
                self._log_error(record, str(exc))
            if (i + 1) % batch_size == 0:
                logger.debug(f"Progression : {i + 1}/{len(gold_records)} enreg. traites")
        logger.info(
            f"Chargement termine : {success} succes, "
            f"{errors} erreurs sur {len(gold_records)} enregistrements."
        )

    def _upsert_record(self, record: dict[str, Any]) -> None:
        movie_id = self._upsert_movie(record)
        if movie_id is None:
            logger.warning(f"Impossible d upsert le film '{record.get('title')}'")
            return
        self._upsert_genres(movie_id, record)
        self._upsert_rating(movie_id, record)
        if any(record.get(k) for k in ["tomatometer_score", "audience_score", "critics_consensus"]):
            self._upsert_rt_detail(movie_id, record)
        self._log_ingestion(movie_id, record)

    def _upsert_movie(self, record: dict[str, Any]) -> str | None:
        tmdb_id = _safe_int(record.get("tmdb_id"))
        imdb_id = record.get("imdb_id")
        if imdb_id:
            imdb_id = str(imdb_id)
        movie_data: dict[str, Any] = {
            "title": record.get("title") or "Unknown",
            "original_title": record.get("original_title"),
            "overview": record.get("overview"),
            "release_date": record.get("release_date"),
            "runtime_minutes": _safe_int(record.get("runtime_minutes")),
            "poster_path": record.get("poster_path"),
            "budget": _safe_int(record.get("budget")),
            "revenue": _safe_int(record.get("revenue")),
            "popularity": _safe_float(record.get("popularity")),
            "sources": ",".join(record.get("_sources", [record.get("source", "")])),
        }
        if tmdb_id is not None:
            movie_data["tmdb_id"] = tmdb_id
        if imdb_id is not None:
            movie_data["imdb_id"] = imdb_id
        existing_id = self._find_movie_id(tmdb_id, imdb_id)
        if existing_id:
            update_data = {k: v for k, v in movie_data.items() if v is not None}
            self._client.table("movies").update(update_data).eq("id", existing_id).execute()
            return existing_id
        else:
            movie_data["id"] = str(uuid.uuid4())
            resp = self._client.table("movies").insert(movie_data).execute()
            if resp.data:
                return resp.data[0]["id"]
            return None

    def _find_movie_id(self, tmdb_id: int | None, imdb_id: str | None) -> str | None:
        if tmdb_id is not None:
            resp = self._client.table("movies").select("id").eq("tmdb_id", tmdb_id).execute()
            if resp.data:
                return resp.data[0]["id"]
        if imdb_id is not None:
            resp = self._client.table("movies").select("id").eq("imdb_id", imdb_id).execute()
            if resp.data:
                return resp.data[0]["id"]
        return None

    def _upsert_genres(self, movie_id: str, record: dict[str, Any]) -> None:
        for name in _parse_genres(record.get("genres")):
            genre_id = self._get_or_create_genre(name)
            if genre_id is None:
                continue
            existing = (
                self._client.table("movie_genres")
                .select("movie_id")
                .eq("movie_id", movie_id)
                .eq("genre_id", genre_id)
                .execute()
            )
            if not existing.data:
                self._client.table("movie_genres").insert(
                    {"movie_id": movie_id, "genre_id": genre_id}
                ).execute()

    def _get_or_create_genre(self, name: str) -> int | None:
        resp = self._client.table("genres").select("id").eq("name", name).execute()
        if resp.data:
            return resp.data[0]["id"]
        ins = self._client.table("genres").insert({"name": name}).execute()
        if ins.data:
            return ins.data[0]["id"]
        return None

    def _upsert_rating(self, movie_id: str, record: dict[str, Any]) -> None:
        source = record.get("source", "tmdb")
        if source not in ("tmdb", "imdb", "rotten_tomatoes", "kaggle", "spark"):
            return
        score = _safe_float(record.get("vote_average") or record.get("tomatometer_score"))
        vote_count = _safe_int(record.get("vote_count"))
        scale = "0-100" if source == "rotten_tomatoes" else "0-10"
        existing = (
            self._client.table("ratings")
            .select("id")
            .eq("movie_id", movie_id)
            .eq("source", source)
            .execute()
        )
        if existing.data:
            update: dict[str, Any] = {}
            if score is not None:
                update["score"] = score
            if vote_count is not None:
                update["vote_count"] = vote_count
            if update:
                self._client.table("ratings").update(update).eq("id", existing.data[0]["id"]).execute()
        else:
            self._client.table("ratings").insert({
                "movie_id": movie_id,
                "source": source,
                "score": score,
                "vote_count": vote_count,
                "scale": scale,
            }).execute()

    def _upsert_rt_detail(self, movie_id: str, record: dict[str, Any]) -> None:
        existing = (
            self._client.table("rt_details")
            .select("id")
            .eq("movie_id", movie_id)
            .execute()
        )
        data: dict[str, Any] = {
            "tomatometer_score": _safe_float(record.get("tomatometer_score")),
            "audience_score": _safe_float(record.get("audience_score")),
            "critics_consensus": record.get("critics_consensus"),
        }
        if existing.data:
            self._client.table("rt_details").update(data).eq("id", existing.data[0]["id"]).execute()
        else:
            data["movie_id"] = movie_id
            self._client.table("rt_details").insert(data).execute()

    def _log_ingestion(self, movie_id: str, record: dict[str, Any]) -> None:
        self._client.table("ingestion_logs").insert({
            "movie_id": movie_id,
            "source_name": record.get("source", "unknown"),
            "status": "success",
            "records_ingested": 1,
        }).execute()

    def _log_error(self, record: dict[str, Any], error_msg: str) -> None:
        try:
            self._client.table("ingestion_logs").insert({
                "movie_id": None,
                "source_name": record.get("source", "unknown"),
                "status": "error",
                "records_ingested": 0,
                "error_message": error_msg[:500],
            }).execute()
        except Exception:
            pass