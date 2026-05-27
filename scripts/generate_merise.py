"""
HorRAGor – Génération des diagrammes Merise (MCD / MLD / MPD)
Exporte les images PNG dans docs/merise/
"""
import os
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

OUTPUT_DIR = Path(__file__).parent.parent / "docs" / "merise"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _box(ax, x, y, w, h, label, attrs=(), header_color="#2d2d2d", text_color="white", attr_color="#1a1a1a"):
    """Dessine une entité/table Merise avec son titre et ses attributs."""
    # Header
    header = FancyBboxPatch((x, y + h - 0.5), w, 0.5,
                             boxstyle="round,pad=0.02", linewidth=1.5,
                             edgecolor="#e74c3c", facecolor=header_color, zorder=3)
    ax.add_patch(header)
    ax.text(x + w / 2, y + h - 0.25, label, ha="center", va="center",
            fontsize=9, fontweight="bold", color=text_color, zorder=4)
    # Body
    body = FancyBboxPatch((x, y), w, h - 0.5,
                           boxstyle="round,pad=0.02", linewidth=1.5,
                           edgecolor="#e74c3c", facecolor=attr_color, zorder=3)
    ax.add_patch(body)
    for i, attr in enumerate(attrs):
        ax.text(x + 0.1, y + (h - 0.5) - 0.3 * (i + 1),
                attr, ha="left", va="center", fontsize=7, color="#ecf0f1", zorder=4)
    return (x + w / 2, y + h / 2)   # centre


def _diamond(ax, x, y, w, h, label, color="#c0392b"):
    """Dessine un losange d'association."""
    cx, cy = x + w / 2, y + h / 2
    diamond = plt.Polygon(
        [(cx, y + h), (x + w, cy), (cx, y), (x, cy)],
        closed=True, linewidth=1.5, edgecolor=color, facecolor="#2c0b0b", zorder=3
    )
    ax.add_patch(diamond)
    ax.text(cx, cy, label, ha="center", va="center",
            fontsize=8, fontweight="bold", color="white", zorder=4)
    return cx, cy


def _arrow(ax, p1, p2, label="", color="#e74c3c"):
    ax.annotate("", xy=p2, xytext=p1,
                arrowprops=dict(arrowstyle="-", color=color, lw=1.2))
    if label:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        ax.text(mx, my, label, fontsize=7, color="#e74c3c", ha="center",
                bbox=dict(boxstyle="round,pad=0.1", fc="#0d0d0d", ec="none"))


def _setup_ax(figsize=(18, 12), title=""):
    fig, ax = plt.subplots(figsize=figsize, facecolor="#0d0d0d")
    ax.set_facecolor("#0d0d0d")
    ax.set_xlim(0, 18); ax.set_ylim(0, 12)
    ax.axis("off")
    ax.set_title(title, color="#e74c3c", fontsize=14, fontweight="bold", pad=12)
    return fig, ax


# ─────────────────────────────────────────────
#  MCD – Modèle Conceptuel des Données
# ─────────────────────────────────────────────

def generate_mcd():
    fig, ax = _setup_ax(title="MCD – Modèle Conceptuel des Données  |  HorRAGor")

    # Entités
    _box(ax, 1, 8, 3, 3, "FILM",
         ["# id (UUID)", "titre", "titre_original", "date_sortie",
          "overview", "tagline", "tmdb_id", "imdb_id", "source"])

    _box(ax, 7, 8.5, 3, 2, "GENRE",
         ["# id (UUID)", "nom"])

    _box(ax, 13, 8, 3, 3, "NOTE",
         ["# id (UUID)", "source", "score_critique",
          "score_audience", "nb_votes", "consensus"])

    _box(ax, 1, 3.5, 3, 3, "DETAIL_RT",
         ["# id (UUID)", "tomatometer", "audience_score",
          "consensus", "url_rt"])

    _box(ax, 7, 3.5, 3, 2, "LOG_INGESTION",
         ["# id (UUID)", "run_id", "source", "nb_extraits",
          "nb_charges", "statut", "duree_s", "ts_debut"])

    # Associations
    d1 = _diamond(ax, 5.5, 8.8, 2, 1.2, "APPARTIENT_A")
    _arrow(ax, (2.5, 9.5), d1)
    _arrow(ax, d1, (7, 9.5))
    ax.text(4.2, 10.2, "0,N", fontsize=7, color="#e74c3c")
    ax.text(6.8, 10.2, "0,N", fontsize=7, color="#e74c3c")

    d2 = _diamond(ax, 11.5, 9, 2, 1, "EVALUE")
    _arrow(ax, (4, 9.5), (11.5, 9.5))
    _arrow(ax, (13.5, 9.5), (13, 9.5))
    ax.text(10.2, 9.8, "1,1", fontsize=7, color="#e74c3c")
    ax.text(13.6, 9.8, "0,N", fontsize=7, color="#e74c3c")

    d3 = _diamond(ax, 2.5, 6.8, 2, 1, "A_DETAIL")
    _arrow(ax, (2.5, 8), (3.5, 7.8))
    _arrow(ax, (3.5, 7.3), (2.5, 6.5))
    ax.text(1.8, 7.5, "0,1", fontsize=7, color="#e74c3c")
    ax.text(2.2, 6.3, "1,1", fontsize=7, color="#e74c3c")

    _arrow(ax, (2.5, 8), (2.5, 6.5))

    plt.tight_layout()
    out = OUTPUT_DIR / "MCD.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="#0d0d0d")
    plt.close(fig)
    print(f"[OK] {out}")


# ─────────────────────────────────────────────
#  MLD – Modèle Logique des Données
# ─────────────────────────────────────────────

def generate_mld():
    fig, ax = _setup_ax(title="MLD – Modèle Logique des Données  |  HorRAGor")

    tables = [
        # (x, y, w, h, titre, colonnes)
        (0.5, 8.5, 4, 3.2, "movies",
         ["#PK  id : UUID", "     titre : TEXT", "     titre_original : TEXT",
          "     date_sortie : DATE", "     overview : TEXT", "     tagline : TEXT",
          "     tmdb_id : INT UNIQUE", "     imdb_id : TEXT UNIQUE",
          "     source : TEXT", "     cree_le : TIMESTAMP"]),

        (5.5, 9.5, 3, 2, "genres",
         ["#PK  id : UUID", "     nom : TEXT UNIQUE"]),

        (5.5, 6.5, 3.5, 2.5, "movie_genres",
         ["#PK  id : UUID", "#FK  movie_id → movies.id",
          "#FK  genre_id → genres.id",
          "     UNIQUE(movie_id, genre_id)"]),

        (10, 8.5, 4, 3, "ratings",
         ["#PK  id : UUID", "#FK  movie_id → movies.id",
          "     source : TEXT", "     score_critique : FLOAT",
          "     score_audience : FLOAT", "     nb_votes : INT",
          "     consensus : TEXT", "     UNIQUE(movie_id, source)"]),

        (0.5, 4.5, 4, 2.5, "rt_details",
         ["#PK  id : UUID", "#FK  movie_id → movies.id UNIQUE",
          "     tomatometer : FLOAT", "     audience_score : FLOAT",
          "     consensus : TEXT", "     url_rt : TEXT"]),

        (5.5, 3.5, 4.5, 2.8, "ingestion_logs",
         ["#PK  id : UUID", "     run_id : UUID", "     source : TEXT",
          "     nb_extraits : INT", "     nb_charges : INT",
          "     statut : TEXT", "     duree_s : FLOAT",
          "     ts_debut : TIMESTAMP"]),
    ]

    centers = {}
    for x, y, w, h, titre, cols in tables:
        cx, cy = _box(ax, x, y, w, h, titre, cols)
        centers[titre] = (cx, cy)

    # FK arrows
    fk_links = [
        ("movie_genres", "movies", "movie_id"),
        ("movie_genres", "genres", "genre_id"),
        ("ratings", "movies", "movie_id"),
        ("rt_details", "movies", "movie_id"),
    ]
    for src, dst, lbl in fk_links:
        _arrow(ax, centers[src], centers[dst], lbl)

    plt.tight_layout()
    out = OUTPUT_DIR / "MLD.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="#0d0d0d")
    plt.close(fig)
    print(f"[OK] {out}")


# ─────────────────────────────────────────────
#  MPD – Modèle Physique des Données (SQL DDL)
# ─────────────────────────────────────────────

MPD_SQL = """\
-- ============================================================
--  HorRAGor – Modèle Physique des Données (PostgreSQL / Supabase)
--  Généré automatiquement par scripts/generate_merise.py
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── FILMS ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS movies (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    titre            TEXT NOT NULL,
    titre_original   TEXT,
    date_sortie      DATE,
    overview         TEXT,
    tagline          TEXT,
    tmdb_id          INTEGER UNIQUE,
    imdb_id          TEXT    UNIQUE,
    source           TEXT    NOT NULL,
    cree_le          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_movies_tmdb_id ON movies(tmdb_id);
CREATE INDEX IF NOT EXISTS idx_movies_imdb_id ON movies(imdb_id);
CREATE INDEX IF NOT EXISTS idx_movies_source  ON movies(source);

-- ── GENRES ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS genres (
    id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nom  TEXT UNIQUE NOT NULL
);

-- ── ASSOCIATION FILM ↔ GENRE ────────────────────────────────
CREATE TABLE IF NOT EXISTS movie_genres (
    id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    movie_id  UUID NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    genre_id  UUID NOT NULL REFERENCES genres(id) ON DELETE CASCADE,
    UNIQUE (movie_id, genre_id)
);

-- ── NOTES PAR SOURCE ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS ratings (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    movie_id        UUID NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    source          TEXT NOT NULL,
    score_critique  FLOAT CHECK (score_critique  BETWEEN 0 AND 100),
    score_audience  FLOAT CHECK (score_audience  BETWEEN 0 AND 100),
    nb_votes        INTEGER CHECK (nb_votes >= 0),
    consensus       TEXT,
    UNIQUE (movie_id, source)
);

-- ── DÉTAILS ROTTEN TOMATOES ─────────────────────────────────
CREATE TABLE IF NOT EXISTS rt_details (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    movie_id       UUID UNIQUE NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    tomatometer    FLOAT CHECK (tomatometer    BETWEEN 0 AND 100),
    audience_score FLOAT CHECK (audience_score BETWEEN 0 AND 100),
    consensus      TEXT,
    url_rt         TEXT
);

-- ── JOURNAL D'INGESTION ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS ingestion_logs (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id       UUID NOT NULL,
    source       TEXT NOT NULL,
    nb_extraits  INTEGER DEFAULT 0,
    nb_charges   INTEGER DEFAULT 0,
    statut       TEXT DEFAULT 'OK',
    duree_s      FLOAT,
    ts_debut     TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_logs_run_id ON ingestion_logs(run_id);
CREATE INDEX IF NOT EXISTS idx_logs_source ON ingestion_logs(source);
"""


def generate_mpd():
    """Sauvegarde le fichier SQL MPD."""
    sql_path = OUTPUT_DIR / "MPD.sql"
    sql_path.write_text(MPD_SQL, encoding="utf-8")
    print(f"[OK] {sql_path}")

    # Image texte pour illustration
    fig, ax = _setup_ax(figsize=(16, 14), title="MPD – Modèle Physique des Données  |  HorRAGor (PostgreSQL)")

    tables_mpd = [
        (0.3, 8.5, 5.5, 3.2, "movies",
         ["id UUID PK DEFAULT uuid_generate_v4()",
          "titre TEXT NOT NULL",
          "titre_original TEXT",
          "date_sortie DATE",
          "overview TEXT",
          "tagline TEXT",
          "tmdb_id INTEGER UNIQUE",
          "imdb_id TEXT UNIQUE",
          "source TEXT NOT NULL",
          "cree_le TIMESTAMPTZ DEFAULT NOW()"]),

        (7, 9.5, 4, 2, "genres",
         ["id UUID PK DEFAULT uuid_generate_v4()",
          "nom TEXT UNIQUE NOT NULL"]),

        (7, 6.5, 5, 2.5, "movie_genres",
         ["id UUID PK",
          "movie_id UUID FK→movies.id ON DELETE CASCADE",
          "genre_id UUID FK→genres.id ON DELETE CASCADE",
          "UNIQUE(movie_id, genre_id)"]),

        (12.5, 8, 5, 3.5, "ratings",
         ["id UUID PK",
          "movie_id UUID FK→movies.id ON DELETE CASCADE",
          "source TEXT NOT NULL",
          "score_critique FLOAT CHECK(0–100)",
          "score_audience FLOAT CHECK(0–100)",
          "nb_votes INTEGER CHECK(≥0)",
          "consensus TEXT",
          "UNIQUE(movie_id, source)"]),

        (0.3, 4.5, 5.5, 3, "rt_details",
         ["id UUID PK",
          "movie_id UUID UNIQUE FK→movies.id ON DELETE CASCADE",
          "tomatometer FLOAT CHECK(0–100)",
          "audience_score FLOAT CHECK(0–100)",
          "consensus TEXT",
          "url_rt TEXT"]),

        (7, 3, 5.5, 3, "ingestion_logs",
         ["id UUID PK",
          "run_id UUID NOT NULL (INDEX)",
          "source TEXT NOT NULL (INDEX)",
          "nb_extraits INTEGER DEFAULT 0",
          "nb_charges INTEGER DEFAULT 0",
          "statut TEXT DEFAULT 'OK'",
          "duree_s FLOAT",
          "ts_debut TIMESTAMPTZ DEFAULT NOW()"]),
    ]

    centers = {}
    for x, y, w, h, titre, cols in tables_mpd:
        cx, cy = _box(ax, x, y, w, h, titre, cols)
        centers[titre] = (cx, cy)

    fk_links = [
        ("movie_genres", "movies", "movie_id FK"),
        ("movie_genres", "genres", "genre_id FK"),
        ("ratings", "movies", "movie_id FK"),
        ("rt_details", "movies", "movie_id FK"),
    ]
    for src, dst, lbl in fk_links:
        _arrow(ax, centers[src], centers[dst], lbl)

    plt.tight_layout()
    img_path = OUTPUT_DIR / "MPD.png"
    fig.savefig(img_path, dpi=150, bbox_inches="tight", facecolor="#0d0d0d")
    plt.close(fig)
    print(f"[OK] {img_path}")


# ─────────────────────────────────────────────
#  Point d'entrée
# ─────────────────────────────────────────────

if __name__ == "__main__":
    generate_mcd()
    generate_mld()
    generate_mpd()
    print("\nDiagrammes Merise générés dans :", OUTPUT_DIR)
