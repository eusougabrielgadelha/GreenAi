"""
Sistema de apostas combinadas para jogos de alta confiança.
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pytz
from models.database import SessionLocal, Game, CombinedBet
from config.settings import HIGH_CONF_THRESHOLD, ZONE
from utils.logger import log_with_context


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


def update_combined_bet_result(combined_bet: CombinedBet, session) -> bool:
    """
    Atualiza o resultado da aposta combinada após os jogos terminarem.
    
    Args:
        combined_bet: Aposta combinada
        session: Sessão do banco
        
    Returns:
        True se atualizado com sucesso
    """
    try:
        # Busca todos os jogos
        games = session.query(Game).filter(Game.id.in_(combined_bet.game_ids)).all()
        
        # Verifica se todos os jogos já terminaram
        all_finished = all(game.status == "ended" and game.outcome is not None for game in games)
        
        if not all_finished:
            return False  # Ainda não terminou
        
        # Cria dicionário de resultados
        outcomes = {}
        all_hit = True
        
        for game in games:
            outcomes[game.id] = game.outcome
            # Verifica se acertou
            if game.outcome != game.pick:
                all_hit = False
        
        # Atualiza aposta combinada
        combined_bet.outcome = outcomes
        combined_bet.hit = all_hit
        combined_bet.status = "won" if all_hit else "lost"
        combined_bet.updated_at = datetime.now(pytz.UTC)
        
        session.commit()
        
        log_with_context(
            "info",
            f"Resultado da aposta combinada atualizado: {'VITÓRIA' if all_hit else 'DERROTA'}",
            stage="update_combined_bet",
            status="success",
            extra_fields={
                "combined_bet_id": combined_bet.id,
                "hit": all_hit,
                "total_games": len(games)
            }
        )
        
        return True
        
    except Exception as e:
        log_with_context(
            "error",
            f"Erro ao atualizar resultado da aposta combinada: {e}",
            stage="update_combined_bet",
            status="failed"
        )
        session.rollback()
        return False


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

