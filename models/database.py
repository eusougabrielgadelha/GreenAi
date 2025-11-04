"""Modelos de banco de dados e setup."""
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Text, DateTime, Boolean, JSON, func, UniqueConstraint, text
)
from sqlalchemy.orm import declarative_base, sessionmaker
from config.settings import DB_URL

Base = declarative_base()
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Game(Base):
    __tablename__ = "games"
    id = Column(Integer, primary_key=True)
    ext_id = Column(String, index=True)
    source_link = Column(Text)
    game_url = Column(Text)
    competition = Column(String)
    team_home = Column(String)
    team_away = Column(String)
    start_time = Column(DateTime, index=True)  # UTC
    odds_home = Column(Float)
    odds_draw = Column(Float)
    odds_away = Column(Float)
    pick = Column(String)  # home|draw|away
    pick_reason = Column(Text)
    pick_prob = Column(Float)
    pick_ev = Column(Float)
    will_bet = Column(Boolean, default=False)
    status = Column(String, default="scheduled")  # scheduled|live|ended
    outcome = Column(String, nullable=True)  # home|draw|away
    hit = Column(Boolean, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("ext_id", "start_time", name="uq_game_extid_start"),
    )


class Stat(Base):
    __tablename__ = "stats"
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, index=True)
    value = Column(JSON)


class LiveGameTracker(Base):
    __tablename__ = "live_game_trackers"
    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, nullable=False, index=True)  # referência a Game.id
    ext_id = Column(String, index=True)

    last_analysis_time = Column(DateTime, server_default=func.now())
    last_pick_sent = Column(DateTime, nullable=True)  # último palpite enviado
    last_pick_market = Column(String, nullable=True)
    last_pick_option = Column(String, nullable=True)
    last_pick_key = Column(String, nullable=True)  # ex: "btts|Não"

    current_score = Column(String, nullable=True)  # "1 - 0"
    current_minute = Column(String, nullable=True)  # "45'+2'", "HT", "FT"
    
    # Estatísticas expandidas (JSON para flexibilidade)
    stats_snapshot = Column(JSON, nullable=True)  # Snapshot das estatísticas no momento da última análise

    game_url = Column(Text, nullable=True)  # deep link do evento
    cooldown_until = Column(DateTime, nullable=True)
    notifications_sent = Column(Integer, default=0)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("game_id", name="uq_live_tracker_game_id"),
    )


class OddHistory(Base):
    __tablename__ = "odd_history"
    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, nullable=False, index=True)  # Referência ao Game.id
    ext_id = Column(String, index=True)
    timestamp = Column(DateTime, server_default=func.now())
    odds_home = Column(Float)
    odds_draw = Column(Float)
    odds_away = Column(Float)
    created_at = Column(DateTime, server_default=func.now())


class AnalyticsEvent(Base):
    """Eventos de analytics para análise detalhada do sistema."""
    __tablename__ = "analytics_events"
    id = Column(Integer, primary_key=True)
    event_type = Column(String, nullable=False, index=True)  # extraction, calculation, decision, telegram, etc
    event_category = Column(String, nullable=False, index=True)  # scraping, betting, notification, etc
    timestamp = Column(DateTime, server_default=func.now(), index=True)
    game_id = Column(Integer, nullable=True, index=True)  # Referência ao Game.id (pode ser None)
    ext_id = Column(String, nullable=True, index=True)
    source_link = Column(Text, nullable=True)
    # Dados do evento (JSON)
    event_data = Column(JSON, nullable=True)  # Dados estruturados do evento
    # Status e resultado
    success = Column(Boolean, default=True)
    reason = Column(Text, nullable=True)  # Motivo da supressão/envio/não envio
    # Metadados (renomeado de 'metadata' para evitar conflito com SQLAlchemy)
    event_metadata = Column(JSON, nullable=True)  # Informações adicionais
    created_at = Column(DateTime, server_default=func.now())


def _safe_add_column(table: str, coldef: str):
    """Adiciona coluna de forma segura (evita erro se já existir)."""
    try:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {coldef}"))
    except Exception:
        pass  # já existe


def _safe_migrate_metadata_column():
    """Migra coluna 'metadata' para 'event_metadata' se necessário."""
    try:
        with engine.begin() as conn:
            # Verifica se a coluna 'metadata' existe e 'event_metadata' não existe
            result = conn.execute(text("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='analytics_events'
            """))
            if result.fetchone():
                # Verifica se metadata existe
                result = conn.execute(text("PRAGMA table_info(analytics_events)"))
                columns = {row[1]: row for row in result.fetchall()}
                
                if 'metadata' in columns and 'event_metadata' not in columns:
                    # Renomeia a coluna usando SQLite ALTER TABLE (SQLite 3.25.0+)
                    conn.execute(text("""
                        ALTER TABLE analytics_events 
                        RENAME COLUMN metadata TO event_metadata
                    """))
    except Exception as e:
        # Se falhar, tenta método alternativo para SQLite antigo
        try:
            with engine.begin() as conn:
                # Verifica se precisa migrar
                result = conn.execute(text("PRAGMA table_info(analytics_events)"))
                columns = {row[1]: row for row in result.fetchall()}
                
                if 'metadata' in columns and 'event_metadata' not in columns:
                    # Método alternativo: criar nova tabela, copiar dados, renomear
                    conn.execute(text("""
                        CREATE TABLE analytics_events_new AS 
                        SELECT 
                            id, event_type, event_category, timestamp, game_id, ext_id,
                            source_link, event_data, success, reason, 
                            metadata AS event_metadata, created_at
                        FROM analytics_events
                    """))
                    conn.execute(text("DROP TABLE analytics_events"))
                    conn.execute(text("ALTER TABLE analytics_events_new RENAME TO analytics_events"))
        except Exception:
            pass  # Ignora erro se não conseguir migrar


def init_database():
    """Inicializa o banco de dados criando todas as tabelas e migrações."""
    Base.metadata.create_all(engine)
    Base.metadata.create_all(engine, tables=[OddHistory.__table__], checkfirst=True)
    Base.metadata.create_all(engine, tables=[AnalyticsEvent.__table__], checkfirst=True)

    # Migrações rápidas
    _safe_add_column("games", "game_url TEXT")
    _safe_add_column("live_game_trackers", "game_url TEXT")
    _safe_add_column("live_game_trackers", "cooldown_until DATETIME")
    _safe_add_column("live_game_trackers", "notifications_sent INTEGER")
    _safe_add_column("live_game_trackers", "last_pick_key TEXT")
    _safe_add_column("live_game_trackers", "last_pick_sent DATETIME")
    # Migração: renomear coluna 'metadata' para 'event_metadata' em analytics_events
    _safe_migrate_metadata_column()


# Inicializa o banco ao importar o módulo
init_database()

