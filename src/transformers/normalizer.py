"""
HorRAGor – Normalisation des données
Fonctions pures de normalisation appliquées à chaque enregistrement
avant la fusion MDM.

Règles issues du cahier des charges :
  - Dates → ISO 8601 (YYYY-MM-DD), année seule → YYYY-01-01
  - Scores TMDB / IMDB → 0-10 (conservés natifs)
  - Scores Rotten Tomatoes → 0-100 (conservés natifs, métrique distincte)
  - Textes → UTF-8, trim whitespace, sans balises HTML
"""
import re
from typing import Any

from bs4 import BeautifulSoup
from dateutil.parser import parse as dateutil_parse, ParserError
from loguru import logger


# ---------------------------------------------------------------------------
# Normalisation des dates
# ---------------------------------------------------------------------------

_YEAR_ONLY_RE = re.compile(r"^\d{4}$")


def normalize_date(raw: Any) -> str | None:
    """
    Normalise une date vers le format ISO 8601 YYYY-MM-DD.

    Règles :
    - None / chaîne vide → None
    - Entier ou chaîne d'année seule (ex : 2019, "2019") → "2019-01-01"
    - Format TMDB "YYYY-MM-DD" → retourné tel quel (déjà conforme)
    - Autres formats → tentative de parsing via dateutil

    Args:
        raw: valeur brute de la date (str, int ou None).

    Returns:
        Chaîne ISO 8601 ou None si la conversion échoue.
    """
    if raw is None:
        return None

    raw_str = str(raw).strip()

    if not raw_str or raw_str in {r"\N", "N/A", "NA", "null"}:
        return None

    # Année seule (entier ou 4 chiffres)
    if _YEAR_ONLY_RE.match(raw_str):
        return f"{raw_str}-01-01"

    try:
        year = int(raw_str)
        return f"{year:04d}-01-01"
    except ValueError:
        pass

    # Tentative de parsing générique
    try:
        dt = dateutil_parse(raw_str, dayfirst=False)
        return dt.strftime("%Y-%m-%d")
    except (ParserError, ValueError, OverflowError):
        logger.debug(f"Impossible de normaliser la date : {raw!r}")
        return None


# ---------------------------------------------------------------------------
# Normalisation des scores
# ---------------------------------------------------------------------------

def normalize_score_tmdb(raw: Any) -> float | None:
    """
    Conserve le score TMDB sur l'échelle 0-10.
    Retourne None si la valeur est hors plage ou invalide.
    """
    return _clamp_float(raw, 0.0, 10.0)


def normalize_score_imdb(raw: Any) -> float | None:
    """
    Conserve le score IMDB sur l'échelle 0-10.
    Retourne None si la valeur est hors plage ou invalide.
    """
    return _clamp_float(raw, 0.0, 10.0)


def normalize_score_rt_tomatometer(raw: Any) -> float | None:
    """
    Conserve le Tomatometer RT sur l'échelle native 0-100 (%).
    Ne convertit PAS en 0-10 : c'est un % de critiques positives,
    pas une note moyenne (cf. cahier des charges).
    """
    return _clamp_float(raw, 0.0, 100.0)


def normalize_score_rt_audience(raw: Any) -> float | None:
    """Idem Tomatometer mais pour le score audience RT (0-100)."""
    return _clamp_float(raw, 0.0, 100.0)


# ---------------------------------------------------------------------------
# Normalisation des textes
# ---------------------------------------------------------------------------

_MULTI_SPACE_RE = re.compile(r"\s+")


def normalize_text(raw: Any) -> str | None:
    """
    Nettoie un texte brut :
    1. Conversion en str (encoding UTF-8 garanti par Python 3)
    2. Suppression des balises HTML (BeautifulSoup)
    3. Normalisation des espaces (trim + collapse whitespace)
    4. Retourne None si la chaîne résultante est vide

    Args:
        raw: texte brut (str, bytes, None).

    Returns:
        Texte nettoyé ou None.
    """
    if raw is None:
        return None

    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw)

    # Suppression des balises HTML résiduelles
    if "<" in text and ">" in text:
        soup = BeautifulSoup(text, "html.parser")
        text = soup.get_text(separator=" ")

    # Normalisation whitespace
    text = _MULTI_SPACE_RE.sub(" ", text).strip()

    return text if text else None


def normalize_title(raw: Any) -> str | None:
    """
    Normalise un titre de film pour le fuzzy matching :
    minuscules, sans ponctuation superflue.
    """
    text = normalize_text(raw)
    if text is None:
        return None
    # Suppression des caractères non-alphanumériques (hors espaces et traits d'union)
    clean = re.sub(r"[^\w\s\-]", "", text, flags=re.UNICODE)
    return _MULTI_SPACE_RE.sub(" ", clean).strip().lower()


# ---------------------------------------------------------------------------
# Application groupée sur un enregistrement
# ---------------------------------------------------------------------------

def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    Applique toutes les normalisations à un enregistrement.

    Args:
        record: dictionnaire brut issu d'un extracteur.

    Returns:
        Nouveau dictionnaire avec les valeurs normalisées.
    """
    source = record.get("source", "")

    normalized = {**record}

    # Dates
    normalized["release_date"] = normalize_date(record.get("release_date"))

    # Scores selon la source
    if source == "tmdb":
        normalized["vote_average"] = normalize_score_tmdb(record.get("vote_average"))
    elif source == "imdb":
        normalized["vote_average"] = normalize_score_imdb(record.get("vote_average"))

    normalized["tomatometer_score"] = normalize_score_rt_tomatometer(
        record.get("tomatometer_score")
    )
    normalized["audience_score"] = normalize_score_rt_audience(
        record.get("audience_score")
    )

    # Textes
    normalized["title"] = normalize_text(record.get("title"))
    normalized["original_title"] = normalize_text(record.get("original_title"))
    normalized["overview"] = normalize_text(record.get("overview"))
    normalized["critics_consensus"] = normalize_text(record.get("critics_consensus"))

    # Clé de matching normalisée (non persistée en base)
    normalized["_normalized_title"] = normalize_title(record.get("title"))

    return normalized


# ---------------------------------------------------------------------------
# Utilitaires internes
# ---------------------------------------------------------------------------

def _clamp_float(raw: Any, min_val: float, max_val: float) -> float | None:
    """Convertit en float et vérifie la plage [min_val, max_val]."""
    if raw is None:
        return None
    try:
        value = float(raw)
        if not (min_val <= value <= max_val):
            return None
        return value
    except (ValueError, TypeError):
        return None
