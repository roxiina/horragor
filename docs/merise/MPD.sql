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
