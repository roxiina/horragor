"""
HorRAGor – Modèles SQLAlchemy ORM (3NF) 
Modélisation relationnelle conforme à la 3ème Forme Normale.

Architecture (Merise → MPD) :
  movies               Table principale
  genres               Référentiel des genres
  movie_genres         Liaison M-N films ↔ genres
  ratings              Scores par source (TMDB, IMDB, RT)
  rt_details           Données spécifiques Rotten Tomatoes (1-1 avec movies)
  ingestion_logs       Audit trail des ingestions (source, date, statut)

Toutes les clés étrangères ont des contraintes d'intégrité référentielle.
La colonne UUID est utilisée comme identifiant métier stable (RGPD-compatible).
"""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Classe de base commune à tous les modèles."""
    pass


# ---------------------------------------------------------------------------
# Table movies – entité principale (3NF : dépendances fonctionnelles directes
# vers la clé primaire id uniquement)
# ---------------------------------------------------------------------------

class Movie(Base):
    __tablename__ = "movies"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Identifiant interne UUID (stable, RGPD-compatible)",
    )
    tmdb_id = Column(Integer, unique=True, nullable=True, index=True,
                     comment="ID The Movie Database (référence maîtresse)")
    imdb_id = Column(String(20), unique=True, nullable=True, index=True,
                     comment="ID IMDB au format tt0000000")
    title = Column(String(500), nullable=False,
                   comment="Titre officiel (issu de TMDB en priorité)")
    original_title = Column(String(500), nullable=True,
                            comment="Titre dans la langue d'origine")
    overview = Column(Text, nullable=True,
                      comment="Synopsis (TMDB en priorité, puis Kaggle, puis Spark)")
    release_date = Column(Date, nullable=True, index=True,
                          comment="Date de sortie ISO 8601")
    runtime_minutes = Column(Integer, nullable=True,
                             comment="Durée en minutes")
    poster_path = Column(String(500), nullable=True,
                         comment="Chemin relatif TMDB pour l'affiche")
    budget = Column(Integer, nullable=True,
                    comment="Budget en USD (Kaggle/TMDB)")
    revenue = Column(Integer, nullable=True,
                     comment="Recettes en USD (Kaggle/TMDB)")
    popularity = Column(Float, nullable=True,
                        comment="Score de popularité TMDB")
    sources = Column(String(200), nullable=True,
                     comment="Sources contributrices séparées par virgule")
    created_at = Column(DateTime(timezone=True), server_default=func.now(),
                        nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now(), nullable=False)

    # Relations
    genres = relationship("Genre", secondary="movie_genres", back_populates="movies")
    ratings = relationship("Rating", back_populates="movie", cascade="all, delete-orphan")
    rt_detail = relationship("RTDetail", back_populates="movie", uselist=False,
                              cascade="all, delete-orphan")
    ingestion_logs = relationship("IngestionLog", back_populates="movie",
                                  cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("runtime_minutes > 0 OR runtime_minutes IS NULL",
                        name="chk_runtime_positive"),
    )

    def __repr__(self) -> str:
        return f"<Movie id={self.id} title={self.title!r} tmdb_id={self.tmdb_id}>"


# ---------------------------------------------------------------------------
# Table genres – référentiel (3NF : pas de dépendances transitives)
# ---------------------------------------------------------------------------

class Genre(Base):
    __tablename__ = "genres"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, index=True,
                  comment="Nom du genre (ex : Horror, Thriller)")
    tmdb_genre_id = Column(Integer, nullable=True,
                           comment="ID TMDB du genre si disponible")

    movies = relationship("Movie", secondary="movie_genres", back_populates="genres")

    def __repr__(self) -> str:
        return f"<Genre id={self.id} name={self.name!r}>"


# ---------------------------------------------------------------------------
# Table de liaison movie_genres (M-N avec contrainte d'unicité)
# ---------------------------------------------------------------------------

class MovieGenre(Base):
    __tablename__ = "movie_genres"

    movie_id = Column(UUID(as_uuid=True), ForeignKey("movies.id", ondelete="CASCADE"),
                      primary_key=True)
    genre_id = Column(Integer, ForeignKey("genres.id", ondelete="CASCADE"),
                      primary_key=True)


# ---------------------------------------------------------------------------
# Table ratings – scores par source (évite la dénormalisation dans movies)
# 3NF : chaque attribut dépend entièrement de (movie_id, source)
# ---------------------------------------------------------------------------

_RATING_SOURCES = ("tmdb", "imdb", "rotten_tomatoes", "kaggle", "spark")


class Rating(Base):
    __tablename__ = "ratings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    movie_id = Column(UUID(as_uuid=True), ForeignKey("movies.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    source = Column(
        Enum(*_RATING_SOURCES, name="rating_source_enum"),
        nullable=False,
        comment="Source du score (tmdb | imdb | rotten_tomatoes | kaggle | spark)",
    )
    score = Column(Float, nullable=True,
                   comment="Note moyenne (0-10 pour TMDB/IMDB, 0-100 pour RT Tomatometer)")
    vote_count = Column(Integer, nullable=True,
                        comment="Nombre de votes/critiques")
    scale = Column(String(10), nullable=False, default="0-10",
                   comment="Échelle du score : '0-10' ou '0-100'")

    movie = relationship("Movie", back_populates="ratings")

    __table_args__ = (
        UniqueConstraint("movie_id", "source", name="uq_rating_movie_source"),
        CheckConstraint("score >= 0 OR score IS NULL", name="chk_score_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<Rating movie_id={self.movie_id} source={self.source} score={self.score}>"


# ---------------------------------------------------------------------------
# Table rt_details – données spécifiques à Rotten Tomatoes (1-1 avec movies)
# Séparée de movies pour respecter la 3NF : ces attributs dépendent
# fonctionnellement de la source RT, pas de l'identité du film.
# ---------------------------------------------------------------------------

class RTDetail(Base):
    __tablename__ = "rt_details"

    id = Column(Integer, primary_key=True, autoincrement=True)
    movie_id = Column(UUID(as_uuid=True), ForeignKey("movies.id", ondelete="CASCADE"),
                      nullable=False, unique=True)
    tomatometer_score = Column(Float, nullable=True,
                               comment="Score Tomatometer RT (0-100 %)")
    audience_score = Column(Float, nullable=True,
                            comment="Score audience RT (0-100 %)")
    critics_consensus = Column(Text, nullable=True,
                               comment="Synopsis de la critique agrégée")
    scraped_at = Column(DateTime(timezone=True), server_default=func.now(),
                        nullable=False)

    movie = relationship("Movie", back_populates="rt_detail")

    __table_args__ = (
        CheckConstraint(
            "(tomatometer_score >= 0 AND tomatometer_score <= 100) OR tomatometer_score IS NULL",
            name="chk_tomatometer_range",
        ),
        CheckConstraint(
            "(audience_score >= 0 AND audience_score <= 100) OR audience_score IS NULL",
            name="chk_audience_score_range",
        ),
    )


# ---------------------------------------------------------------------------
# Table ingestion_logs – audit trail (traçabilité RGPD)
# ---------------------------------------------------------------------------

_LOG_STATUS = ("success", "partial", "error")


class IngestionLog(Base):
    __tablename__ = "ingestion_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    movie_id = Column(UUID(as_uuid=True), ForeignKey("movies.id", ondelete="SET NULL"),
                      nullable=True, index=True)
    source_name = Column(String(50), nullable=False,
                         comment="Nom de la source (tmdb, imdb, …)")
    status = Column(
        Enum(*_LOG_STATUS, name="log_status_enum"),
        nullable=False,
        default="success",
    )
    records_ingested = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    ingested_at = Column(DateTime(timezone=True), server_default=func.now(),
                         nullable=False)

    movie = relationship("Movie", back_populates="ingestion_logs")

    def __repr__(self) -> str:
        return (
            f"<IngestionLog source={self.source_name!r} "
            f"status={self.status!r} at={self.ingested_at}>"
        )
