"""Modelos de banco de dados e setup."""
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Text, DateTime, Boolean, JSON, func, UniqueConstraint, text, Index, ForeignKey
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from config.settings import DB_URL

Base = declarative_base()
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Game(Base):
    __tablename__ = "games"
    id = Column(Integer, primary_key=True)
    ext_id = Column(String, index=True)
    betradar_match_id = Column(Integer, nullable=True, index=True)  # Identificador universal (Betano → cross-source matching)
    source_link = Column(Text)
    game_url = Column(Text)
    competition = Column(String)
    country = Column(String, nullable=True, index=True)
    team_home = Column(String)
    team_away = Column(String)
    home_team_id = Column(Integer, nullable=True, index=True)  # FK opcional pra teams.id (sem FK formal — evita lock issues no SQLite)
    away_team_id = Column(Integer, nullable=True, index=True)
    start_time = Column(DateTime, index=True)  # UTC
    odds_home = Column(Float)
    odds_draw = Column(Float)
    odds_away = Column(Float)
    pick = Column(String)  # home|draw|away
    pick_reason = Column(Text)
    pick_prob = Column(Float)
    pick_ev = Column(Float)
    will_bet = Column(Boolean, default=False)
    pick_notified_at = Column(DateTime, nullable=True, index=True)  # Quando foi enviada a notificação do palpite
    status = Column(String, default="scheduled")  # scheduled|live|ended
    outcome = Column(String, nullable=True)  # home|draw|away
    hit = Column(Boolean, nullable=True)
    final_score_home = Column(Integer, nullable=True)  # Gols do time da casa
    final_score_away = Column(Integer, nullable=True)  # Gols do time visitante
    final_score = Column(String, nullable=True)  # "2-1" (formato legível)
    result_fetched_at = Column(DateTime, nullable=True)  # Quando o resultado foi obtido
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # Relacionamentos
    tracker = relationship("LiveGameTracker", back_populates="game", uselist=False, cascade="all, delete-orphan")
    odd_history = relationship("OddHistory", back_populates="game", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("ext_id", "start_time", name="uq_game_extid_start"),
        Index('idx_game_status', 'status'),
        Index('idx_game_will_bet', 'will_bet'),
        Index('idx_game_pick', 'pick'),
        Index('idx_game_outcome', 'outcome'),
        Index('idx_game_hit', 'hit'),
        Index('idx_game_pick_notified', 'pick_notified_at'),
        Index('idx_game_country', 'country'),
        Index('idx_game_betradar', 'betradar_match_id'),
        Index('idx_game_home_team', 'home_team_id'),
        Index('idx_game_away_team', 'away_team_id'),
    )


class Team(Base):
    """Times de futebol coletados via páginas de liga Betano.

    Identificação canônica: betano_team_id (extraído do bloco participants).
    Sem FK formal pro Game.home_team_id/away_team_id — escolha consciente pra
    evitar lock issues no SQLite e permitir Games sem team_id (legado).
    """
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True)
    betano_team_id = Column(Integer, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False, index=True)
    country = Column(String, nullable=True, index=True)
    league_id = Column(Integer, nullable=True, index=True)  # league_id Betano (ex: 10016 = Brasileirão Série A)
    slug = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    __table_args__ = (
        Index('idx_team_name', 'name'),
    )


class Stat(Base):
    __tablename__ = "stats"
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, index=True)
    value = Column(JSON)


class LiveGameTracker(Base):
    __tablename__ = "live_game_trackers"
    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey('games.id', ondelete='CASCADE'), nullable=False, index=True)  # referência a Game.id
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
    
    # Relacionamentos
    game = relationship("Game", back_populates="tracker")

    __table_args__ = (
        UniqueConstraint("game_id", name="uq_live_tracker_game_id"),
        Index('idx_tracker_ext_id', 'ext_id'),
        Index('idx_tracker_last_analysis', 'last_analysis_time'),
    )


class OddHistory(Base):
    __tablename__ = "odd_history"
    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey('games.id', ondelete='CASCADE'), nullable=False, index=True)  # Referência ao Game.id
    ext_id = Column(String, index=True)
    timestamp = Column(DateTime, server_default=func.now())
    odds_home = Column(Float)
    odds_draw = Column(Float)
    odds_away = Column(Float)
    # Multi-market support (additive — campos 1x2 acima mantidos pra compat)
    market = Column(String, nullable=True, index=True)   # 'match_result'|'total_goals'|'btts'|...
    option = Column(String, nullable=True)               # 'home'|'draw'|'away'|'Mais de 2.5'|'Menos de 2.5'|'Sim'|'Não'
    line = Column(Float, nullable=True)                  # 0.5/1.5/2.5/3.5 quando aplicável
    odd_value = Column(Float, nullable=True)             # odd snapshot
    created_at = Column(DateTime, server_default=func.now())

    # Relacionamentos
    game = relationship("Game", back_populates="odd_history")

    __table_args__ = (
        Index('idx_odd_history_ext_id', 'ext_id'),
        Index('idx_odd_history_timestamp', 'timestamp'),
        Index('idx_odd_history_market_option', 'game_id', 'market', 'option', 'line'),
    )


class Pick(Base):
    __tablename__ = "picks"

    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey('games.id', ondelete='CASCADE'),
                    nullable=False, index=True)

    market = Column(String, nullable=False)  # 'match_result' | 'total_goals'
    line = Column(Float, nullable=True)      # null pra match_result; 0.5/1.5/2.5/3.5 pra total_goals

    pick = Column(String, nullable=False)    # 'home'|'draw'|'away' | 'over'|'under'
    pick_prob = Column(Float)
    pick_ev = Column(Float)
    pick_odd = Column(Float)                 # snapshot da odd no momento da decisão
    pick_reason = Column(Text)

    will_bet = Column(Boolean, default=False, index=True)
    notified_at = Column(DateTime, nullable=True, index=True)

    outcome = Column(String, nullable=True)  # 'home'|'draw'|'away'|'over'|'under'|'void'
    hit = Column(Boolean, nullable=True)
    result_verified_at = Column(DateTime, nullable=True)

    decision_source = Column(String, nullable=True)   # 'scanner'|'night_scan'|'hourly_rescan'|'watchlist_upgrade'|'backfill'
    decision_metadata = Column(JSON, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    game = relationship("Game", backref="picks")

    __table_args__ = (
        Index('idx_pick_game', 'game_id'),
        Index('idx_pick_market', 'market'),
        Index('idx_pick_will_bet', 'will_bet'),
        Index('idx_pick_notified', 'notified_at'),
        Index('idx_pick_hit', 'hit'),
        UniqueConstraint('game_id', 'market', 'line', name='uq_pick_game_market_line'),
    )


class AnalyticsEvent(Base):
    """Eventos de analytics para análise detalhada do sistema."""
    __tablename__ = "analytics_events"
    id = Column(Integer, primary_key=True)
    event_type = Column(String, nullable=False, index=True)  # extraction, calculation, decision, telegram, etc
    event_category = Column(String, nullable=False, index=True)  # scraping, betting, notification, etc
    timestamp = Column(DateTime, server_default=func.now(), index=True)
    game_id = Column(Integer, ForeignKey('games.id', ondelete='SET NULL'), nullable=True, index=True)  # Referência ao Game.id (pode ser None)
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
    
    __table_args__ = (
        Index('idx_analytics_event_type_category', 'event_type', 'event_category'),
        Index('idx_analytics_timestamp_game', 'timestamp', 'game_id'),
    )


class CombinedBet(Base):
    """Apostas combinadas com múltiplos jogos de alta confiança."""
    __tablename__ = "combined_bets"
    id = Column(Integer, primary_key=True)
    market = Column(String, nullable=True, default='match_result', index=True)  # 'match_result' | 'handicap_asian' | ...
    bet_date = Column(DateTime, nullable=False, index=True)  # Data da aposta (dia dos jogos)
    game_ids = Column(JSON, nullable=False)  # Lista de IDs dos jogos incluídos [1, 2, 3]
    picks = Column(JSON, nullable=False)  # Lista de picks (nomes dos times ou "Empate")
    odds = Column(JSON, nullable=False)  # Lista de odds correspondentes [1.5, 2.0, 1.8]
    combined_odd = Column(Float, nullable=False)  # Odd combinada (multiplicação de todas)
    example_stake = Column(Float, default=10.0)  # Valor de exemplo da aposta (padrão R$ 10)
    potential_return = Column(Float, nullable=False)  # Retorno potencial (combined_odd * example_stake)
    avg_confidence = Column(Float, nullable=True)  # Média de confiança (pick_prob) dos jogos
    total_games = Column(Integer, nullable=False)  # Número de jogos na aposta
    sent_at = Column(DateTime, nullable=True)  # Quando foi enviada a notificação
    status = Column(String, default="pending")  # pending | completed | won | lost
    outcome = Column(JSON, nullable=True)  # Resultados dos jogos após finalização {"game_id": "home", ...}
    hit = Column(Boolean, nullable=True)  # True se acertou, False se errou, None se ainda pendente
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    
    __table_args__ = (
        Index('idx_combined_bet_date', 'bet_date'),
        Index('idx_combined_bet_status', 'status'),
        Index('idx_combined_bet_hit', 'hit'),
        Index('idx_combined_bet_market', 'market'),
    )


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


def _backfill_picks_from_games():
    """One-shot backfill. Cada Game com pick 1x2 vira 1 Pick(market='match_result').
    Idempotente via Stat key 'picks_backfill_v1_done'."""
    from sqlalchemy.exc import IntegrityError
    with SessionLocal() as s:
        flag = s.query(Stat).filter_by(key="picks_backfill_v1_done").one_or_none()
        if flag and flag.value is True:
            return

        games = s.query(Game).filter(Game.pick.isnot(None), Game.pick != "").all()
        created = 0
        for g in games:
            exists = s.query(Pick).filter_by(game_id=g.id, market="match_result", line=None).first()
            if exists:
                continue
            odd_map = {"home": g.odds_home, "draw": g.odds_draw, "away": g.odds_away}
            p = Pick(
                game_id=g.id,
                market="match_result",
                line=None,
                pick=g.pick,
                pick_prob=g.pick_prob,
                pick_ev=g.pick_ev,
                pick_odd=odd_map.get(g.pick),
                pick_reason=g.pick_reason,
                will_bet=bool(g.will_bet),
                notified_at=g.pick_notified_at,
                outcome=g.outcome,
                hit=g.hit,
                result_verified_at=g.result_fetched_at,
                decision_source="backfill",
            )
            s.add(p)
            try:
                s.flush()
                created += 1
            except IntegrityError:
                s.rollback()
                continue

        # Marca backfill como concluído
        flag = s.query(Stat).filter_by(key="picks_backfill_v1_done").one_or_none()
        if flag:
            flag.value = True
        else:
            s.add(Stat(key="picks_backfill_v1_done", value=True))
        s.commit()
        try:
            from utils.logger import logger
            logger.info(f"Backfill picks v1: {created} pick(s) criado(s) a partir de Game.")
        except Exception:
            pass


def init_database():
    """Inicializa o banco de dados criando todas as tabelas e migrações."""
    # Write-Ahead Logging: permite múltiplas leituras + 1 escrita concorrente
    # sem locks excessivos. Reduz drasticamente "database is locked" em ambiente
    # multi-task. Persiste no banco (idempotente, só seta 1ª vez se necessário).
    try:
        with engine.begin() as conn:
            result = conn.execute(text("PRAGMA journal_mode=WAL;")).fetchone()
            mode = result[0] if result else "?"
            conn.execute(text("PRAGMA synchronous=NORMAL;"))  # NORMAL é OK com WAL e é mais rápido
            conn.execute(text("PRAGMA busy_timeout=5000;"))  # 5s antes de levantar SQLITE_BUSY
        import logging
        logging.getLogger("betauto").info(
            f"📚 SQLite mode: journal_mode={mode}, synchronous=NORMAL, busy_timeout=5000ms"
        )
    except Exception:
        pass  # Best-effort, não bloqueia init

    Base.metadata.create_all(engine)
    Base.metadata.create_all(engine, tables=[OddHistory.__table__], checkfirst=True)
    Base.metadata.create_all(engine, tables=[AnalyticsEvent.__table__], checkfirst=True)
    Base.metadata.create_all(engine, tables=[CombinedBet.__table__], checkfirst=True)

    # Migrações rápidas
    _safe_add_column("games", "game_url TEXT")
    _safe_add_column("live_game_trackers", "game_url TEXT")
    _safe_add_column("live_game_trackers", "cooldown_until DATETIME")
    _safe_add_column("live_game_trackers", "notifications_sent INTEGER")
    _safe_add_column("live_game_trackers", "last_pick_key TEXT")
    _safe_add_column("live_game_trackers", "last_pick_sent DATETIME")
    _safe_add_column("games", "pick_notified_at DATETIME")  # Rastrear quando palpite foi notificado
    # Migração: placar final e timestamp do resultado
    _safe_add_column("games", "final_score_home INTEGER")
    _safe_add_column("games", "final_score_away INTEGER")
    _safe_add_column("games", "final_score TEXT")
    _safe_add_column("games", "result_fetched_at DATETIME")
    # Migração: país (category_name da API) — separado do nome da liga
    _safe_add_column("games", "country TEXT")
    # Migração: betradar match id (Betano → cross-source matching)
    _safe_add_column("games", "betradar_match_id INTEGER")
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_game_betradar ON games(betradar_match_id)"
            ))
    except Exception:
        pass  # idempotente
    # Migração: renomear coluna 'metadata' para 'event_metadata' em analytics_events
    _safe_migrate_metadata_column()

    # Migração: tabela picks (multi-market 1:N com Game)
    Base.metadata.create_all(engine, tables=[Pick.__table__], checkfirst=True)

    # Migração: colunas multi-market em odd_history (additive, mantém 1x2)
    _safe_add_column("odd_history", "market TEXT")
    _safe_add_column("odd_history", "option TEXT")
    _safe_add_column("odd_history", "line REAL")
    _safe_add_column("odd_history", "odd_value REAL")

    # Índice novo em odd_history pra busca multi-market
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_odd_history_market_option ON odd_history(game_id, market, option, line)"))
    except Exception:
        pass

    # Migração: combined_bets ganha coluna 'market' (default 'match_result')
    _safe_add_column("combined_bets", "market TEXT DEFAULT 'match_result'")
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_combined_bet_market ON combined_bets(market)"
            ))
    except Exception:
        pass  # idempotente

    # Backfill one-shot: Game.pick → Pick(market='match_result')
    try:
        _backfill_picks_from_games()
    except Exception:
        pass

    # Migração: tabela teams (nova) — coleta proativa via páginas de liga Betano
    Base.metadata.create_all(engine, tables=[Team.__table__], checkfirst=True)

    # Migração: colunas team_id no Game (idempotentes)
    _safe_add_column("games", "home_team_id INTEGER")
    _safe_add_column("games", "away_team_id INTEGER")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_game_home_team ON games(home_team_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_game_away_team ON games(away_team_id)"))
    except Exception:
        pass


# Inicializa o banco ao importar o módulo
init_database()

