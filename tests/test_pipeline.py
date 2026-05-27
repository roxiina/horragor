"""
Tests unitaires – HorRAGor Pipeline Partie 1
Couvre : normalisation, dédoublonnage, fusion MDM et filtrage thématique.
"""
import pytest
from src.transformers.normalizer import (
    normalize_date,
    normalize_score_tmdb,
    normalize_score_rt_tomatometer,
    normalize_text,
    normalize_title,
    normalize_record,
)
from src.transformers.deduplicator import deduplicate
from src.transformers.merger import MDMMerger
from src.pipeline import filter_horror_only


# ---------------------------------------------------------------------------
# Tests normalizer.py
# ---------------------------------------------------------------------------

class TestNormalizeDate:
    def test_iso8601_passthrough(self):
        assert normalize_date("2023-10-31") == "2023-10-31"

    def test_year_only_string(self):
        assert normalize_date("2019") == "2019-01-01"

    def test_year_only_int(self):
        assert normalize_date(2019) == "2019-01-01"

    def test_imdb_null_marker(self):
        assert normalize_date(r"\N") is None

    def test_none(self):
        assert normalize_date(None) is None

    def test_empty_string(self):
        assert normalize_date("") is None

    def test_full_iso_date(self):
        result = normalize_date("31/10/2023")
        assert result == "2023-10-31"

    def test_us_format(self):
        result = normalize_date("October 31, 2023")
        assert result == "2023-10-31"


class TestNormalizeScores:
    def test_tmdb_valid(self):
        assert normalize_score_tmdb(7.5) == 7.5

    def test_tmdb_out_of_range(self):
        assert normalize_score_tmdb(11.0) is None

    def test_tmdb_negative(self):
        assert normalize_score_tmdb(-1.0) is None

    def test_tmdb_none(self):
        assert normalize_score_tmdb(None) is None

    def test_rt_tomatometer_valid(self):
        assert normalize_score_rt_tomatometer(85) == 85.0

    def test_rt_tomatometer_out_of_range(self):
        assert normalize_score_rt_tomatometer(105) is None

    def test_rt_string_percent(self):
        # Le score RT peut arriver comme float déjà parsé
        assert normalize_score_rt_tomatometer(92.0) == 92.0


class TestNormalizeText:
    def test_strip_whitespace(self):
        assert normalize_text("  hello world  ") == "hello world"

    def test_collapse_whitespace(self):
        assert normalize_text("hello   world") == "hello world"

    def test_strip_html(self):
        result = normalize_text("<p>This is <b>horror</b>.</p>")
        assert "<" not in result
        assert "horror" in result

    def test_none_returns_none(self):
        assert normalize_text(None) is None

    def test_empty_returns_none(self):
        assert normalize_text("   ") is None

    def test_bytes_utf8(self):
        result = normalize_text("Ça fait peur".encode("utf-8"))
        assert "Ça fait peur" in result


class TestNormalizeTitle:
    def test_lowercase(self):
        assert normalize_title("The Shining") == "the shining"

    def test_punctuation_removed(self):
        result = normalize_title("It's Alive!")
        assert "!" not in result

    def test_none(self):
        assert normalize_title(None) is None


class TestNormalizeRecord:
    def test_full_record_tmdb(self):
        raw = {
            "source": "tmdb",
            "tmdb_id": 694,
            "title": "  The Shining  ",
            "release_date": "1980-05-23",
            "vote_average": 8.4,
            "overview": "<p>A family heads to...</p>",
        }
        result = normalize_record(raw)
        assert result["title"] == "The Shining"
        assert result["release_date"] == "1980-05-23"
        assert result["vote_average"] == 8.4
        assert "<p>" not in (result["overview"] or "")
        assert result["_normalized_title"] == "the shining"


# ---------------------------------------------------------------------------
# Tests deduplicator.py
# ---------------------------------------------------------------------------

class TestDeduplicate:
    def _make_record(self, title, year, tmdb_id=None, imdb_id=None, overview=None):
        return {
            "source": "tmdb",
            "tmdb_id": tmdb_id,
            "imdb_id": imdb_id,
            "title": title,
            "release_date": f"{year}-01-01" if year else None,
            "overview": overview,
            "vote_average": 7.0,
            "vote_count": 1000,
            "poster_path": None,
            "runtime_minutes": 90,
        }

    def test_dedup_by_tmdb_id(self):
        records = [
            self._make_record("The Shining", 1980, tmdb_id=694),
            self._make_record("The Shining", 1980, tmdb_id=694, overview="A family..."),
        ]
        result = deduplicate(records)
        assert len(result) == 1
        # Doit conserver le plus complet (avec overview)
        assert result[0].get("overview") == "A family..."

    def test_dedup_by_title_year(self):
        records = [
            self._make_record("Hereditary", 2018),
            self._make_record("Hereditary", 2018),
        ]
        result = deduplicate(records)
        assert len(result) == 1

    def test_keep_distinct_films(self):
        records = [
            self._make_record("The Shining", 1980, tmdb_id=694),
            self._make_record("Hereditary", 2018, tmdb_id=493),
        ]
        result = deduplicate(records)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Tests merger.py (MDMMerger)
# ---------------------------------------------------------------------------

def _make_movie(title, year, source, tmdb_id=None, imdb_id=None, **kwargs):
    return {
        "source": source,
        "tmdb_id": tmdb_id,
        "imdb_id": imdb_id,
        "title": title,
        "original_title": title,
        "overview": None,
        "release_date": f"{year}-01-01",
        "vote_average": None,
        "vote_count": None,
        "popularity": None,
        "poster_path": None,
        "tomatometer_score": None,
        "audience_score": None,
        "critics_consensus": None,
        "budget": None,
        "revenue": None,
        "runtime_minutes": None,
        "_normalized_title": normalize_title(title),
        **kwargs,
    }


class TestMDMMerger:
    def test_merge_by_tmdb_id(self):
        records = [
            _make_movie("The Shining", 1980, "tmdb", tmdb_id=694, overview="Main overview"),
            _make_movie("The Shining", 1980, "imdb", imdb_id="tt0081505",
                        vote_average=8.4, vote_count=950000),
        ]
        merger = MDMMerger(fuzzy_threshold=80)
        gold = merger.merge(records)
        assert len(gold) == 1
        film = gold[0]
        assert film["tmdb_id"] == 694
        assert film["overview"] == "Main overview"
        assert film["vote_average"] == 8.4

    def test_merge_fuzzy_match(self):
        records = [
            _make_movie("Hereditary", 2018, "tmdb", tmdb_id=493, overview="Aster film"),
            _make_movie("Hereditary", 2018, "kaggle", budget=10_000_000),
        ]
        merger = MDMMerger(fuzzy_threshold=80)
        gold = merger.merge(records)
        assert len(gold) == 1
        assert gold[0]["budget"] == 10_000_000
        assert gold[0]["overview"] == "Aster film"

    def test_no_false_merge_different_years(self):
        records = [
            _make_movie("Halloween", 1978, "tmdb", tmdb_id=948),
            _make_movie("Halloween", 2018, "tmdb", tmdb_id=363088),
        ]
        merger = MDMMerger(fuzzy_threshold=85)
        gold = merger.merge(records)
        assert len(gold) == 2

    def test_overview_fallback(self):
        """TMDB sans overview → Kaggle doit fournir le synopsis."""
        records = [
            _make_movie("Midsommar", 2019, "tmdb", tmdb_id=530385, overview=None),
            _make_movie("Midsommar", 2019, "kaggle", overview="A couple travels to Sweden..."),
        ]
        merger = MDMMerger(fuzzy_threshold=80)
        gold = merger.merge(records)
        assert len(gold) == 1
        assert gold[0]["overview"] == "A couple travels to Sweden..."


# ---------------------------------------------------------------------------
# Tests pipeline.py – filtre thématique
# ---------------------------------------------------------------------------

class TestFilterHorrorOnly:
    def test_keeps_horror(self):
        records = [{"source": "tmdb", "title": "The Shining", "genres": "Horror", "overview": ""}]
        result = filter_horror_only(records)
        assert len(result) == 1

    def test_removes_comedy(self):
        records = [{"source": "kaggle", "title": "The Comedy", "genres": "Comedy", "overview": "funny"}]
        result = filter_horror_only(records)
        assert len(result) == 0

    def test_tmdb_source_always_kept(self):
        """Les sources TMDB/IMDB/Spark sont filtrées en amont → toujours gardées."""
        records = [{"source": "tmdb", "title": "Unknown", "genres": "", "overview": ""}]
        result = filter_horror_only(records)
        assert len(result) == 1
