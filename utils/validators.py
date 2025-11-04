"""
Sistema de validação de dados da API e scraping.
"""
from typing import Optional, Tuple, Any, Dict, List
from utils.logger import logger


def validate_odds(odds_home: Any, odds_draw: Any, odds_away: Any) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Valida e normaliza odds.
    
    Args:
        odds_home: Odd do time da casa
        odds_draw: Odd do empate
        odds_away: Odd do time visitante
    
    Returns:
        Tuple (odds_home, odds_draw, odds_away) normalizadas ou (None, None, None) se inválido
    
    Validações:
    - Odds devem estar entre 1.0 e 100.0
    - Todas as três odds devem estar presentes
    - Valores devem ser numéricos
    """
    try:
        # Converter para float
        home = float(odds_home) if odds_home is not None else None
        draw = float(odds_draw) if odds_draw is not None else None
        away = float(odds_away) if odds_away is not None else None
        
        # Validar range (1.0 a 100.0)
        if home is not None:
            if home < 1.0 or home > 100.0:
                logger.debug(f"Odd home inválida (fora do range): {home}")
                home = None
            elif home == 0:
                logger.debug(f"Odd home inválida (zero): {home}")
                home = None
        
        if draw is not None:
            if draw < 1.0 or draw > 100.0:
                logger.debug(f"Odd draw inválida (fora do range): {draw}")
                draw = None
            elif draw == 0:
                logger.debug(f"Odd draw inválida (zero): {draw}")
                draw = None
        
        if away is not None:
            if away < 1.0 or away > 100.0:
                logger.debug(f"Odd away inválida (fora do range): {away}")
                away = None
            elif away == 0:
                logger.debug(f"Odd away inválida (zero): {away}")
                away = None
        
        # Todas devem estar presentes e válidas
        if not (home and draw and away):
            logger.debug(f"Odds incompletas: home={home}, draw={draw}, away={away}")
            return (None, None, None)
        
        return (home, draw, away)
        
    except (ValueError, TypeError) as e:
        logger.debug(f"Erro ao validar odds: {e}")
        return (None, None, None)


def validate_event_data(
    event_id: Any,
    home: Any,
    away: Any,
    odds_home: Any = None,
    odds_draw: Any = None,
    odds_away: Any = None
) -> Optional[Dict[str, Any]]:
    """
    Valida dados básicos de um evento.
    
    Args:
        event_id: ID do evento
        home: Nome do time da casa
        away: Nome do time visitante
        odds_home: Odd do time da casa (opcional)
        odds_draw: Odd do empate (opcional)
        odds_away: Odd do time visitante (opcional)
    
    Returns:
        Dict com dados validados ou None se inválido
    """
    # Validar event_id
    try:
        event_id = int(event_id) if event_id is not None else None
        if event_id is None or event_id <= 0:
            logger.debug(f"event_id inválido: {event_id}")
            return None
    except (ValueError, TypeError):
        logger.debug(f"event_id não é um número válido: {event_id}")
        return None
    
    # Validar nomes dos times
    if not home or not isinstance(home, str) or not home.strip():
        logger.debug(f"Nome do time da casa inválido: {home}")
        return None
    
    if not away or not isinstance(away, str) or not away.strip():
        logger.debug(f"Nome do time visitante inválido: {away}")
        return None
    
    # Validar odds se fornecidas
    validated_odds = None
    if odds_home is not None or odds_draw is not None or odds_away is not None:
        home_odd, draw_odd, away_odd = validate_odds(odds_home, odds_draw, odds_away)
        if home_odd and draw_odd and away_odd:
            validated_odds = {
                'home': home_odd,
                'draw': draw_odd,
                'away': away_odd
            }
        else:
            # Se odds foram fornecidas mas são inválidas, retornar None
            logger.debug(f"Odds fornecidas mas inválidas para evento {event_id}")
            return None
    
    return {
        'event_id': event_id,
        'home': home.strip(),
        'away': away.strip(),
        'odds': validated_odds
    }


def validate_tournament_data(
    tournament_id: Any,
    tournament_name: Any,
    category_id: Any = None,
    category_name: Any = None
) -> Optional[Dict[str, Any]]:
    """
    Valida dados de um campeonato/torneio.
    
    Args:
        tournament_id: ID do torneio
        tournament_name: Nome do torneio
        category_id: ID da categoria (opcional)
        category_name: Nome da categoria (opcional)
    
    Returns:
        Dict com dados validados ou None se inválido
    """
    # Validar tournament_id
    try:
        tournament_id = int(tournament_id) if tournament_id is not None else None
        if tournament_id is None or tournament_id <= 0:
            logger.debug(f"tournament_id inválido: {tournament_id}")
            return None
    except (ValueError, TypeError):
        logger.debug(f"tournament_id não é um número válido: {tournament_id}")
        return None
    
    # Validar nome do torneio
    if not tournament_name or not isinstance(tournament_name, str) or not tournament_name.strip():
        logger.debug(f"Nome do torneio inválido: {tournament_name}")
        return None
    
    result = {
        'tournament_id': tournament_id,
        'tournament_name': tournament_name.strip()
    }
    
    # Adicionar categoria se fornecida
    if category_id is not None:
        try:
            category_id = int(category_id)
            if category_id >= 0:  # 0 é válido (todas as categorias)
                result['category_id'] = category_id
        except (ValueError, TypeError):
            pass
    
    if category_name:
        result['category_name'] = str(category_name).strip()
    
    return result


def validate_score(home_goals: Any, away_goals: Any) -> Optional[Tuple[int, int]]:
    """
    Valida placar de um jogo.
    
    Args:
        home_goals: Gols do time da casa
        away_goals: Gols do time visitante
    
    Returns:
        Tuple (home_goals, away_goals) validados ou None se inválido
    """
    try:
        home = int(home_goals) if home_goals is not None else None
        away = int(away_goals) if away_goals is not None else None
        
        if home is None or away is None:
            return None
        
        # Gols devem ser >= 0
        if home < 0 or away < 0:
            logger.debug(f"Placar inválido (valores negativos): {home}-{away}")
            return None
        
        # Gols não devem ser absurdamente altos (ex: > 50)
        if home > 50 or away > 50:
            logger.debug(f"Placar inválido (valores muito altos): {home}-{away}")
            return None
        
        return (home, away)
        
    except (ValueError, TypeError):
        logger.debug(f"Erro ao validar placar: home_goals={home_goals}, away_goals={away_goals}")
        return None


def validate_date_string(date_str: Any) -> Optional[str]:
    """
    Valida string de data.
    
    Args:
        date_str: String de data
    
    Returns:
        String de data validada ou None se inválido
    """
    if not date_str:
        return None
    
    if not isinstance(date_str, str):
        try:
            date_str = str(date_str)
        except Exception:
            return None
    
    date_str = date_str.strip()
    
    if not date_str or len(date_str) < 8:  # Mínimo: "YYYYMMDD" ou "DD/MM/YY"
        logger.debug(f"String de data muito curta: {date_str}")
        return None
    
    return date_str


def sanitize_string(s: Any, max_length: int = 200) -> Optional[str]:
    """
    Sanitiza uma string removendo caracteres inválidos.
    
    Args:
        s: Valor a sanitizar
        max_length: Tamanho máximo da string
    
    Returns:
        String sanitizada ou None se inválido
    """
    if s is None:
        return None
    
    try:
        s = str(s).strip()
        if not s:
            return None
        
        # Limitar tamanho
        if len(s) > max_length:
            s = s[:max_length]
            logger.debug(f"String truncada para {max_length} caracteres")
        
        return s
    except Exception:
        return None

