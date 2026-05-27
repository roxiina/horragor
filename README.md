# HorRAGor – Bot Conversationnel Horreur · Partie 1 : Pipeline d'Ingestion

> Agent conversationnel spécialisé dans l'univers de l'horreur (cinéma, littérature, jeux vidéo) alimenté par une architecture RAG.

---

## Architecture du Pipeline

```
┌──────────────────────────────────────────────────────────────────┐
│                   5 SOURCES D'EXTRACTION                         │
│                                                                  │
│  [TMDB API]  [Rotten Tomatoes]  [Kaggle CSV]  [IMDB SQLite]  [Spark] │
│      │            │  Selenium      │  Polars      │                │
└──────┴────────────┴───────────────┴─────────────┴────────────────┘
                           │  Extraction parallèle (ThreadPoolExecutor)
                           ▼
              ┌────────────────────────┐
              │  Normalisation         │  dates ISO 8601, scores, textes UTF-8
              │  Dédoublonnage         │  par source (tmdb_id → imdb_id → titre+année)
              └────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │  Fusion MDM            │  Niveau 1: tmdb_id exact
              │  (Master Data Mgmt)    │  Niveau 2: imdb_id exact
              │                        │  Niveau 3: Fuzzy (Levenshtein)
              └────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │  Filtrage Horreur      │  Exclusion stricte hors-sujet
              └────────────────────────┘
                     │           │
                     ▼           ▼
              [Supabase]    [Parquet Gold]
```

---

## Structure du Projet

```
HorRAGor/
├── src/
│   ├── config.py                    # Configuration (Pydantic Settings)
│   ├── pipeline.py                  # Orchestrateur principal ★
│   ├── extractors/
│   │   ├── tmdb_extractor.py        # API TMDB (source maîtresse)
│   │   ├── rotten_tomatoes_scraper.py  # Selenium scraping
│   │   ├── kaggle_extractor.py      # Polars / CSV Kaggle
│   │   ├── imdb_extractor.py        # SQLite IMDB
│   │   └── spark_extractor.py       # PySpark Big Data
│   ├── transformers/
│   │   ├── normalizer.py            # Normalisation dates/scores/textes
│   │   ├── deduplicator.py          # Dédoublonnage intra-source
│   │   └── merger.py                # Fusion MDM + Fuzzy Matching
│   ├── models/
│   │   └── schema.py                # SQLAlchemy ORM 3NF
│   └── loaders/
│       └── supabase_loader.py       # Chargement Supabase (upsert batch)
├── scripts/
│   └── build_imdb_db.py             # Construction base SQLite IMDB
├── data/
│   ├── raw/                         # Sources brutes (non versionnées)
│   ├── processed/                   # Données intermédiaires
│   └── gold/                        # Export Parquet final
├── docs/
│   └── merise/                      # Diagrammes MCD / MLD / MPD
├── tests/
│   └── test_pipeline.py             # Tests unitaires (pytest)
├── .env.example                     # Template de configuration
├── pyproject.toml                   # Dépendances et métadonnées
└── README.md
```

---

## Installation

```bash
# 1. Cloner le dépôt
git clone <url-du-depot>
cd HorRAGor

# 2. Créer un environnement virtuel
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Linux/macOS

# 3. Installer les dépendances
pip install -e ".[dev]"

# 4. Configurer les variables d'environnement
cp .env.example .env
# Éditez .env avec votre clé TMDB et vos credentials Supabase
```

---

## Prérequis des Données

### Kaggle
Téléchargez le dataset **Horror Movies** depuis Kaggle et placez-le dans :
```
data/raw/horror_movies_kaggle.csv
```
Dataset recommandé : [The Horror Movie Dataset](https://www.kaggle.com/datasets/sujaykapadnis/horror-movies-dataset)

### IMDB (SQLite)
Téléchargez les fichiers Non-Commercial IMDB :
```bash
# Depuis https://datasets.imdbws.com/
Invoke-WebRequest -Uri "https://datasets.imdbws.com/title.basics.tsv.gz" -OutFile "data/raw/title.basics.tsv.gz"
Invoke-WebRequest -Uri "https://datasets.imdbws.com/title.ratings.tsv.gz" -OutFile "data/raw/title.ratings.tsv.gz"

# Construire la base SQLite (filtrée sur Horror)
python scripts/build_imdb_db.py \
    --basics data/raw/title.basics.tsv.gz \
    --ratings data/raw/title.ratings.tsv.gz
```

### PySpark (fichiers splittés)
Placez les partitions CSV dans :
```
data/raw/spark_chunks/part_001.csv
data/raw/spark_chunks/part_002.csv
...
```

---

## Utilisation

### Lancer le pipeline complet

```bash
python -m src.pipeline
# ou
horragor-pipeline
```

### Mode dry-run (sans Supabase)

```bash
python -m src.pipeline --no-supabase
```

### Sans export Parquet

```bash
python -m src.pipeline --no-parquet
```

### Tests unitaires

```bash
pytest tests/ -v --tb=short
```

---

## Modélisation (Merise / 3NF)

### Entités principales

| Table | Description |
|---|---|
| `movies` | Entité centrale – un film unique (UUID stable) |
| `genres` | Référentiel des genres (Horror, Thriller…) |
| `movie_genres` | Liaison M-N films ↔ genres |
| `ratings` | Scores par source (TMDB 0-10, RT 0-100) |
| `rt_details` | Données spécifiques Rotten Tomatoes (1-1) |
| `ingestion_logs` | Audit trail RGPD (source, statut, date) |

**Clés de réconciliation** : `tmdb_id` (UNIQUE) et `imdb_id` (UNIQUE) sur `movies`.

Les diagrammes MCD/MLD/MPD se trouvent dans `docs/merise/`.

---

## Règles de Normalisation

| Données | Règle |
|---|---|
| Dates | ISO 8601 `YYYY-MM-DD` ; année seule → `YYYY-01-01` |
| Scores TMDB/IMDB | Échelle native `0-10` (décimal) |
| Scores RT | Échelle native `0-100` (% critiques positives) |
| Textes | UTF-8, trim, sans balises HTML |

---

## Priorité de Fusion MDM

```
TMDB (maître) → RT→ Kaggle → IMDB → Spark
```

| Niveau | Méthode |
|---|---|
| 1 | Correspondance exacte `tmdb_id` |
| 2 | Correspondance exacte `imdb_id` |
| 3 | Fuzzy matching `token_sort_ratio` ≥ 85 sur (titre + année) |

---

## Livrables

- [x] Code source organisé (ce dépôt)
- [x] `pyproject.toml` (dépendances reproductibles)
- [ ] Documentation Merise (MCD/MLD/MPD) → `docs/merise/`
- [ ] Instance Supabase opérationnelle (fournir credentials)
- [ ] Jeu de données Gold Parquet → `data/gold/horror_gold.parquet`
