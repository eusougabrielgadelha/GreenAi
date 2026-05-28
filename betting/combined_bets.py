"""
Sistema de apostas combinadas para jogos de alta confiança.
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pytz
from models.database import SessionLocal, Game, CombinedBet
from config.settings import (
    HIGH_CONF_THRESHOLD,
    ZONE,
    COMBINED_BET_MAX_GAMES,
    COMBINED_BET_MIN_GAMES,
    COMBINED_BET_MIN_ODD,
    COMBINED_BET_EXCLUDE_DRAWS,
    COMBINED_BET_RANK_BY,
    COMBINED_BET_ONE_PER_COMPETITION,
    COMBINED_BET_ONE_PER_TEAM,
)
from utils.logger import log_with_context, logger


def get_high_confidence_games_for_date(target_date: datetime, session) -> List[Game]:
    """
    Busca todos os jogos de alta confiança do dia que estão marcados para aposta.
    
    Args:
        target_date: Data do dia (em UTC)
        session: Sessão do banco de dados
        
    Returns:
        Lista de jogos com will_bet=True e pick_prob >= HIGH_CONF_THRESHOLD
    """
    # Início e fim do dia (00:00 às 23:59:59)
    start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    
    # Busca jogos do dia com alta confiança
    games = session.query(Game).filter(
        Game.will_bet == True,
        Game.pick_prob >= HIGH_CONF_THRESHOLD,
        Game.pick.isnot(None),
        Game.pick != "",
        Game.start_time >= start_of_day,
        Game.start_time < end_of_day,
        Game.status.in_(["scheduled", "live"])  # Apenas jogos que ainda não terminaram
    ).order_by(Game.start_time.asc()).all()
    
    return games


def calculate_combined_odd(games: List[Game]) -> Tuple[float, List[float], List[str]]:
    """
    Calcula a odd combinada multiplicando todas as odds dos jogos.
    
    Args:
        games: Lista de jogos
        
    Returns:
        Tupla: (odd_combinada, lista_odds_ individuais, lista_picks)
    """
    if not games:
        return 1.0, [], []
    
    odds_list = []
    picks_list = []
    
    for game in games:
        # Determina a odd baseada no pick
        if game.pick == "home":
            odd = float(game.odds_home or 0.0)
        elif game.pick == "draw":
            odd = float(game.odds_draw or 0.0)
        elif game.pick == "away":
            odd = float(game.odds_away or 0.0)
        else:
            continue  # Skip se não tiver pick válido
        
        if odd <= 0:
            continue  # Skip se odd inválida
        
        odds_list.append(odd)
        # Armazenar o pick como NOME DO TIME (ou 'Empate') em vez de 'home/away'
        if game.pick == "home":
            picks_list.append(game.team_home)
        elif game.pick == "away":
            picks_list.append(game.team_away)
        else:
            picks_list.append("Empate")
    
    # Calcula odd combinada (multiplicação)
    combined_odd = 1.0
    for odd in odds_list:
        combined_odd *= odd
    
    return combined_odd, odds_list, picks_list


def calculate_potential_return(combined_odd: float, stake: float = 10.0) -> float:
    """
    Calcula o retorno potencial de uma aposta combinada.
    
    Args:
        combined_odd: Odd combinada
        stake: Valor da aposta (padrão R$ 10)
        
    Returns:
        Retorno potencial (odd_combinada * stake)
    """
    return combined_odd * stake


def calculate_avg_confidence(games: List[Game]) -> float:
    """
    Calcula a média de confiança (pick_prob) dos jogos.
    
    Args:
        games: Lista de jogos
        
    Returns:
        Média de pick_prob
    """
    if not games:
        return 0.0
    
    total_prob = sum(float(game.pick_prob or 0.0) for game in games)
    return total_prob / len(games)


def _odd_for_pick(game: Game) -> float:
    """Retorna a odd correspondente ao pick do jogo (0.0 se inválida)."""
    if game.pick == "home":
        return float(game.odds_home or 0.0)
    if game.pick == "draw":
        return float(game.odds_draw or 0.0)
    if game.pick == "away":
        return float(game.odds_away or 0.0)
    return 0.0


def _score_for_game(game: Game, rank_by: str) -> float:
    """
    Calcula o score de ranking pra um jogo conforme COMBINED_BET_RANK_BY.

    rank_by:
        - "pick_prob"   → score = pick_prob
        - "pick_ev"     → score = pick_ev (0.0 se None)
        - "prob_x_odd"  → score = pick_prob * odd_picked
    """
    pick_prob = float(game.pick_prob or 0.0)
    if rank_by == "pick_ev":
        return float(game.pick_ev or 0.0)
    if rank_by == "prob_x_odd":
        return pick_prob * _odd_for_pick(game)
    # Default e "pick_prob"
    return pick_prob


def select_games_for_combined_bet(session, date_filter: Optional[datetime] = None) -> List[Game]:
    """
    Seleciona jogos elegíveis pra uma aposta múltipla, com ranking, diversificação
    e validação de mínimos.

    Pipeline:
        1. Candidatos: will_bet=True, pick_prob >= HIGH_CONF_THRESHOLD,
           status='scheduled', pick válido, no dia (se date_filter).
        2. Filtra draws se COMBINED_BET_EXCLUDE_DRAWS=true.
        3. Ranqueia por COMBINED_BET_RANK_BY (pick_prob | pick_ev | prob_x_odd).
        4. Greedy: 1 por competição/time (se ligado), até COMBINED_BET_MAX_GAMES.
        5. Valida COMBINED_BET_MIN_GAMES e COMBINED_BET_MIN_ODD.

    Args:
        session: sessão SQLAlchemy
        date_filter: data de referência (UTC). Se None, considera "hoje" em UTC.

    Returns:
        Lista de Game selecionados. Vazia se múltipla foi descartada por qualquer
        critério (poucos jogos elegíveis, abaixo do mínimo, odd combinada baixa).
    """
    # 1. Janela do dia
    if date_filter is None:
        date_filter = datetime.now(pytz.UTC)
    start_of_day = date_filter.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    # 2. Busca candidatos elegíveis
    candidates = session.query(Game).filter(
        Game.will_bet == True,
        Game.pick_prob >= HIGH_CONF_THRESHOLD,
        Game.pick.isnot(None),
        Game.pick != "",
        Game.start_time >= start_of_day,
        Game.start_time < end_of_day,
        Game.status == "scheduled",
    ).all()

    total_eligible = len(candidates)

    # 3. Filtra draws se configurado
    if COMBINED_BET_EXCLUDE_DRAWS:
        candidates = [g for g in candidates if g.pick != "draw"]

    # 4. Ranqueia por score (desc)
    candidates.sort(key=lambda g: _score_for_game(g, COMBINED_BET_RANK_BY), reverse=True)

    # 5. Greedy com diversificação
    selected: List[Game] = []
    seen_competitions: set = set()
    seen_teams: set = set()

    for game in candidates:
        if len(selected) >= COMBINED_BET_MAX_GAMES:
            break

        if COMBINED_BET_ONE_PER_COMPETITION:
            comp_key = (game.country or "", game.competition or "")
            if comp_key in seen_competitions:
                continue

        if COMBINED_BET_ONE_PER_TEAM:
            if game.team_home in seen_teams or game.team_away in seen_teams:
                continue

        selected.append(game)
        if COMBINED_BET_ONE_PER_COMPETITION:
            seen_competitions.add((game.country or "", game.competition or ""))
        if COMBINED_BET_ONE_PER_TEAM:
            seen_teams.add(game.team_home)
            seen_teams.add(game.team_away)

    # 6. Valida piso de jogos
    if len(selected) < COMBINED_BET_MIN_GAMES:
        logger.info(
            "Múltipla descartada: poucos jogos (selecionados=%d, mínimo=%d, elegíveis_iniciais=%d)",
            len(selected), COMBINED_BET_MIN_GAMES, total_eligible,
        )
        return []

    # 7. Valida odd combinada mínima
    combined_odd = 1.0
    for game in selected:
        odd = _odd_for_pick(game)
        if odd <= 0:
            continue
        combined_odd *= odd

    if combined_odd < COMBINED_BET_MIN_ODD:
        logger.info(
            "Múltipla descartada: odd combinada muito baixa (combined_odd=%.3f, mínimo=%.2f, jogos=%d)",
            combined_odd, COMBINED_BET_MIN_ODD, len(selected),
        )
        return []

    logger.info(
        "Múltipla selecionada: %d jogos (elegíveis_iniciais=%d, combined_odd=%.2f, rank_by=%s)",
        len(selected), total_eligible, combined_odd, COMBINED_BET_RANK_BY,
    )
    return selected


def create_combined_bet(
    games: List[Game],
    bet_date: datetime,
    example_stake: float = 10.0,
    session = None
) -> Optional[CombinedBet]:
    """
    Cria uma aposta combinada no banco de dados.
    
    Args:
        games: Lista de jogos para incluir na aposta
        bet_date: Data da aposta (dia dos jogos)
        example_stake: Valor de exemplo da aposta (padrão R$ 10)
        session: Sessão do banco (se None, cria nova)
        
    Returns:
        Objeto CombinedBet criado ou None se falhar
    """
    if not games:
        return None
    
    # Calcula valores
    combined_odd, odds_list, picks_list = calculate_combined_odd(games)
    potential_return = calculate_potential_return(combined_odd, example_stake)
    avg_confidence = calculate_avg_confidence(games)
    game_ids = [game.id for game in games]
    
    # Verifica se já existe aposta combinada para este dia
    should_create_session = session is None
    if should_create_session:
        session = SessionLocal()
    
    try:
        # Verifica se já existe aposta combinada para este dia
        start_of_day = bet_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        
        existing = session.query(CombinedBet).filter(
            CombinedBet.bet_date >= start_of_day,
            CombinedBet.bet_date < end_of_day,
            CombinedBet.status == "pending"
        ).first()
        
        if existing:
            # Atualiza aposta existente
            existing.game_ids = game_ids
            existing.picks = picks_list
            existing.odds = odds_list
            existing.combined_odd = combined_odd
            existing.example_stake = example_stake
            existing.potential_return = potential_return
            existing.avg_confidence = avg_confidence
            existing.total_games = len(games)
            session.commit()
            return existing
        
        # Cria nova aposta combinada
        combined_bet = CombinedBet(
            bet_date=bet_date,
            game_ids=game_ids,
            picks=picks_list,
            odds=odds_list,
            combined_odd=combined_odd,
            example_stake=example_stake,
            potential_return=potential_return,
            avg_confidence=avg_confidence,
            total_games=len(games),
            status="pending"
        )
        
        session.add(combined_bet)
        session.commit()
        session.refresh(combined_bet)
        
        log_with_context(
            "info",
            f"Aposta combinada criada: {len(games)} jogos, odd {combined_odd:.2f}, retorno potencial R$ {potential_return:.2f}",
            stage="create_combined_bet",
            status="success",
            extra_fields={
                "combined_bet_id": combined_bet.id,
                "total_games": len(games),
                "combined_odd": combined_odd,
                "potential_return": potential_return
            }
        )
        
        return combined_bet
        
    except Exception as e:
        log_with_context(
            "error",
            f"Erro ao criar aposta combinada: {e}",
            stage="create_combined_bet",
            status="failed"
        )
        if should_create_session:
            session.rollback()
            session.close()
        return None
    finally:
        if should_create_session:
            session.close()


def update_combined_bet_result(combined_bet: CombinedBet, session) -> Optional[str]:
    """
    Atualiza o resultado da aposta combinada conforme os jogos terminam.

    Suporta early-cancel: se QUALQUER jogo da combinada já errou (hit=False),
    a múltipla é marcada como 'lost' imediatamente, sem esperar os demais.

    Idempotente: se a aposta já não está em status 'pending', retorna None
    sem fazer nada — evita reprocessar combinadas finalizadas.

    Args:
        combined_bet: Aposta combinada
        session: Sessão do banco

    Returns:
        'won'  — combinada ganhou (todos os jogos terminaram e nenhum errou)
        'lost' — combinada perdeu (algum jogo errou ou foi finalizada como lost)
        None   — ainda pending (nem todos os jogos terminaram) ou já processada
    """
    try:
        # Idempotência: já processada → sai sem mexer
        if combined_bet.status != "pending":
            return None

        # Busca todos os jogos da combinada
        games = session.query(Game).filter(Game.id.in_(combined_bet.game_ids)).all()

        # Early-cancel: algum jogo já errou? Matematicamente já perdeu.
        errors = [g for g in games if g.hit is False]
        if errors:
            combined_bet.status = "lost"
            combined_bet.hit = False
            combined_bet.outcome = {str(g.id): g.outcome for g in games if g.outcome}
            combined_bet.updated_at = datetime.now(pytz.UTC)

            log_with_context(
                "info",
                f"Aposta combinada {combined_bet.id} marcada como LOST por early-cancel ({len(errors)} jogo(s) erraram)",
                stage="update_combined_bet",
                status="success",
                extra_fields={
                    "combined_bet_id": combined_bet.id,
                    "hit": False,
                    "early_cancel": True,
                    "errored_games": [g.id for g in errors],
                    "total_games": len(games)
                }
            )
            return "lost"

        # Ainda há jogos sem resultado? Espera.
        pending_games = [g for g in games if g.hit is None]
        if pending_games:
            return None  # Ainda esperando

        # Todos terminaram e nenhum errou → ganhou
        combined_bet.status = "won"
        combined_bet.hit = True
        combined_bet.outcome = {str(g.id): g.outcome for g in games}
        combined_bet.updated_at = datetime.now(pytz.UTC)

        log_with_context(
            "info",
            f"Aposta combinada {combined_bet.id} marcada como WON (todos os {len(games)} jogos acertaram)",
            stage="update_combined_bet",
            status="success",
            extra_fields={
                "combined_bet_id": combined_bet.id,
                "hit": True,
                "total_games": len(games)
            }
        )
        return "won"

    except Exception as e:
        log_with_context(
            "error",
            f"Erro ao atualizar resultado da aposta combinada: {e}",
            stage="update_combined_bet",
            status="failed"
        )
        session.rollback()
        return None


def calculate_combined_bets_accuracy(session, days: int = 30) -> Dict[str, float]:
    """
    Calcula a taxa de assertividade das apostas combinadas.
    
    Args:
        session: Sessão do banco
        days: Número de dias para calcular (padrão 30)
        
    Returns:
        Dict com estatísticas: {
            'total': total de apostas,
            'won': apostas ganhas,
            'lost': apostas perdidas,
            'accuracy': taxa de assertividade (0-1)
        }
    """
    cutoff_date = datetime.now(pytz.UTC) - timedelta(days=days)
    
    # Busca apostas finalizadas
    bets = session.query(CombinedBet).filter(
        CombinedBet.status.in_(["won", "lost"]),
        CombinedBet.created_at >= cutoff_date
    ).all()
    
    total = len(bets)
    won = sum(1 for bet in bets if bet.hit is True)
    lost = sum(1 for bet in bets if bet.hit is False)
    
    accuracy = (won / total * 100) if total > 0 else 0.0
    
    return {
        'total': total,
        'won': won,
        'lost': lost,
        'accuracy': accuracy,
        'accuracy_percent': accuracy
    }

