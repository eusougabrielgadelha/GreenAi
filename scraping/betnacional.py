"""Parsing específico da BetNacional."""
import json
import re
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from types import SimpleNamespace as NS
import pytz
import requests

from config.settings import ZONE, USER_AGENT, API_TIMEOUT
from utils.logger import logger

# Mapeamento de meses em português
_PT_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


@dataclass
class EventRow:
    competition: str
    team_home: str
    team_away: str
    start_local_str: str
    odds_home: Optional[float]
    odds_draw: Optional[float]
    odds_away: Optional[float]
    ext_id: Optional[str] = None
    is_live: bool = False


# ============================================
# API XHR - Funções para buscar dados via API
# ============================================

def extract_ids_from_url(url: str) -> Optional[Tuple[int, int, int]]:
    """
    Extrai sport_id, category_id e tournament_id de uma URL do BetNacional.
    
    Exemplo: https://betnacional.bet.br/events/1/0/7
    Retorna: (1, 0, 7) -> (sport_id, category_id, tournament_id)
    """
    pattern = r'/events/(\d+)/(\d+)/(\d+)'
    match = re.search(pattern, url)
    if match:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def fetch_events_from_api(sport_id: int, category_id: int = 0, tournament_id: int = 0, 
                          market_id: int = 1, rate_limiter=None) -> Optional[Dict[str, Any]]:
    """
    Busca eventos diretamente da API XHR da BetNacional.
    
    Args:
        sport_id: ID do esporte (1 = futebol)
        category_id: ID da categoria (0 = todas)
        tournament_id: ID do torneio/campeonato (0 = todos)
        market_id: ID do mercado (1 = 1x2)
        rate_limiter: Rate limiter opcional (não usado diretamente aqui, mas para compatibilidade)
    
    Returns:
        Dict com a resposta JSON da API ou None em caso de erro
    """
    from utils.anti_block import (
        get_enhanced_headers_for_api, api_throttle, 
        add_random_delay
    )
    from utils.bypass_detection import get_bypass_detector
    
    api_url = "https://prod-global-bff-events.bet6.com.br/api/odds/1/events-by-seasons"
    
    params = {
        'sport_id': str(sport_id),
        'category_id': str(category_id),
        'tournament_id': str(tournament_id),
        'markets': str(market_id),
        'filter_time_event': ''
    }
    
    # Usar bypass detector para requisições mais robustas
    detector = get_bypass_detector()
    session = detector.create_stealth_session(use_cookies=True)
    
    # Verificar se precisa fazer warm-up da sessão (se não há cookies)
    from utils.cookie_manager import get_cookie_manager
    manager = get_cookie_manager()
    stats = manager.get_stats()
    if stats['valid_cookies'] == 0:
        logger.debug("Nenhum cookie válido, fazendo warm-up de sessão...")
        # Tentar fazer warm-up síncrono (visitando página principal)
        try:
            warmup_url = "https://betnacional.bet.br/"
            warmup_response = session.get(warmup_url, timeout=10)
            if warmup_response.status_code == 200:
                from utils.cookie_manager import update_cookies_from_response
                update_cookies_from_response(warmup_response)
                logger.debug("Warm-up de sessão bem-sucedido")
        except Exception as e:
            logger.debug(f"Erro durante warm-up: {e}")
    
    # Usar headers otimizados com rotação de User-Agent
    headers = get_enhanced_headers_for_api()
    
    try:
        # Fazer requisição com bypass automático (has_fallback=True reduz verbosidade)
        response = detector.make_request_with_bypass(
            session=session,
            url=api_url,
            method="GET",
            params=params,
            headers=headers,
            max_retries=3,
            use_cookies=True,
            has_fallback=True  # Há fallback HTML disponível
        )
        
        if response is None:
            # Não logar warning quando há fallback - apenas debug
            logger.debug("Falha ao fazer requisição com bypass, retornando None (fallback HTML disponível)")
            return None
        
        response.raise_for_status()
        return response.json()
    except Exception as e:
        from utils.error_handler import log_error_with_context
        log_error_with_context(
            e,
            context={
                "sport_id": sport_id,
                "category_id": category_id,
                "tournament_id": tournament_id,
                "market_id": market_id,
                "stage": "fetch_events_from_api"
            },
            level="warning",
            reraise=False,
            suppress_403_if_fallback=True  # Reduz verbosidade de 403 quando há fallback HTML
        )
        return None


def parse_events_from_api(json_data: Dict[str, Any], source_url: str) -> List[Any]:
    """
    Converte dados JSON da API para o formato esperado pelo sistema.
    
    Args:
        json_data: Dados JSON retornados pela API
        source_url: URL de origem (para metadata)
    
    Returns:
        Lista de eventos no formato SimpleNamespace
    """
    events = []
    
    if not json_data or 'odds' not in json_data:
        return events
    
    odds_list = json_data.get('odds', [])
    
    # Agrupar odds por event_id para ter as 3 odds (home, draw, away)
    events_dict = {}
    
    for odd_item in odds_list:
        event_id = odd_item.get('event_id')
        if not event_id:
            continue
        
        # FILTRAR POR MARKET_STATUS_ID: só processar mercados disponíveis (>= 0)
        market_status_id = odd_item.get('market_status_id', 1)
        if market_status_id < 0:  # -1 = mercado fechado/suspenso
            logger.debug(f"Market {odd_item.get('market_id')} do evento {event_id} ignorado: status {market_status_id} (fechado)")
            continue
        
        # Só processar Market ID 1 (Resultado Final) para eventos pré-jogo
        market_id = odd_item.get('market_id', 1)
        if market_id != 1:
            continue  # Outros mercados são processados separadamente
        
        if event_id not in events_dict:
            events_dict[event_id] = {
                'event_id': event_id,
                'home': odd_item.get('home', ''),
                'away': odd_item.get('away', ''),
                'date_start': odd_item.get('date_start', ''),
                'date_start_original': odd_item.get('date_start_original', ''),
                'tournament_name': odd_item.get('tournament_name', ''),
                'category_name': odd_item.get('category_name', ''),
                'is_live': bool(odd_item.get('is_live', 0)),
                'odds': {},
                'odds_previous': {}  # Para tracking de mudanças
            }
        
        # Extrair odds por outcome_id (1=home, 2=draw, 3=away)
        outcome_id = odd_item.get('outcome_id', '')
        odd_value = odd_item.get('odd')
        previous_odd = odd_item.get('previous_odd')
        
        if outcome_id and odd_value:
            try:
                events_dict[event_id]['odds'][outcome_id] = float(odd_value)
                
                # Armazenar previous_odd se disponível para detectar mudanças
                if previous_odd is not None:
                    try:
                        events_dict[event_id]['odds_previous'][outcome_id] = float(previous_odd)
                    except (ValueError, TypeError):
                        pass
            except (ValueError, TypeError):
                pass
    
    # Converter para formato esperado
    from utils.validators import validate_odds, validate_event_data
    
    for event_id, event_data in events_dict.items():
        odds = event_data['odds']
        
        # Extrair odds (1=home, 2=draw, 3=away)
        odds_home = odds.get('1')
        odds_draw = odds.get('2')
        odds_away = odds.get('3')
        
        # Validar odds
        home_odd, draw_odd, away_odd = validate_odds(odds_home, odds_draw, odds_away)
        if not (home_odd and draw_odd and away_odd):
            logger.debug(f"Evento {event_id} ignorado: odds inválidas")
            continue
        
        # Validar dados do evento antes de processar
        validated_event = validate_event_data(
            event_id=event_id,
            home=event_data.get('home', ''),
            away=event_data.get('away', ''),
            odds_home=home_odd,
            odds_draw=draw_odd,
            odds_away=away_odd
        )
        
        if not validated_event:
            logger.debug(f"Evento {event_id} ignorado: dados inválidos")
            continue
        
        # Converter data para formato local
        date_start = event_data.get('date_start', '')
        start_local_str = ''
        
        if date_start:
            try:
                # Formato da API: "2025-11-04 14:45:00"
                dt = datetime.strptime(date_start, "%Y-%m-%d %H:%M:%S")
                # Assumir que a data está no timezone local
                dt_local = ZONE.localize(dt)
                start_local_str = dt_local.strftime("%H:%M %d/%m/%Y")
            except Exception as e:
                logger.debug(f"Erro ao converter data {date_start}: {e}")
                start_local_str = date_start
        
        # Usar dados validados
        validated_home = validated_event['home']
        validated_away = validated_event['away']
        validated_odds = validated_event['odds']
        
        # Construir URL do jogo
        game_url = f"https://betnacional.bet.br/event/{event_id}/1/1"
        
        events.append(NS(
            ext_id=str(event_id),
            source_link=source_url,
            game_url=game_url,
            competition=event_data.get('tournament_name', ''),
            team_home=validated_home,
            team_away=validated_away,
            start_local_str=start_local_str,
            odds_home=validated_odds['home'],
            odds_draw=validated_odds['draw'],
            odds_away=validated_odds['away'],
            is_live=event_data.get('is_live', False),
        ))
    
    from utils.logger import log_with_context
    log_with_context(
        "info",
        f"Eventos extraídos via API XHR: {len(events)} eventos",
        url=source_url,
        stage="parse_events_api",
        status="success",
        extra_fields={"events_count": len(events), "method": "api_xhr"}
    )
    return events


async def fetch_events_from_api_async(sport_id: int, category_id: int = 0, 
                                       tournament_id: int = 0, market_id: int = 1) -> Optional[Dict[str, Any]]:
    """
    Wrapper assíncrono para fetch_events_from_api com rate limiting e retry.
    """
    from utils.rate_limiter import api_rate_limiter, retry_with_backoff
    import requests
    
    async def _fetch():
        # Usar rate limiter antes de fazer requisição
        await api_rate_limiter.acquire()
        
        # Executar função síncrona em thread separada
        return await asyncio.to_thread(fetch_events_from_api, sport_id, category_id, tournament_id, market_id)
    
    # Tentar com retry (especialmente para 403 errors)
    try:
        return await retry_with_backoff(
            _fetch,
            max_retries=3,
            initial_delay=2.0,
            max_delay=30.0,
            exponential_base=2.0,
            exceptions=(requests.exceptions.HTTPError, requests.exceptions.RequestException, Exception),
            rate_limiter=None  # Já usamos dentro de _fetch
        )
    except Exception as e:
        logger.warning(f"Erro ao buscar eventos da API após retries: {e}")
        return None


def extract_event_id_from_url(url: str) -> Optional[int]:
    """
    Extrai event_id de uma URL de evento individual do BetNacional.
    
    Exemplo: https://betnacional.bet.br/event/1/1/62155186
    Retorna: 62155186
    """
    pattern = r'/event/\d+/\d+/(\d+)'
    match = re.search(pattern, url)
    if match:
        return int(match.group(1))
    return None


def fetch_event_odds_from_api(event_id: int, language_id: int = 1, 
                               status_id: int = 1) -> Optional[Dict[str, Any]]:
    """
    Busca dados de um evento individual (incluindo odds) via API XHR.
    
    Args:
        event_id: ID do evento
        language_id: ID do idioma (1 = português)
        status_id: ID do status (1 = ativo)
    
    Returns:
        Dict com a resposta JSON da API ou None em caso de erro
    """
    from utils.anti_block import (
        get_enhanced_headers_for_api, get_realistic_referer
    )
    from utils.bypass_detection import get_bypass_detector
    
    api_url = f"https://prod-global-bff-events.bet6.com.br/api/event-odds/{event_id}"
    
    params = {
        'languageId': str(language_id),
        'marketIds': '',
        'outcomeIds': '',
        'statusId': str(status_id),
    }
    
    # Usar bypass detector para requisições mais robustas
    detector = get_bypass_detector()
    session = detector.create_stealth_session(use_cookies=True)
    
    # Verificar se precisa fazer warm-up da sessão (se não há cookies)
    from utils.cookie_manager import get_cookie_manager
    manager = get_cookie_manager()
    stats = manager.get_stats()
    if stats['valid_cookies'] == 0:
        logger.debug("Nenhum cookie válido, fazendo warm-up de sessão...")
        # Tentar fazer warm-up síncrono (visitando página principal)
        try:
            warmup_url = "https://betnacional.bet.br/"
            warmup_response = session.get(warmup_url, timeout=10)
            if warmup_response.status_code == 200:
                from utils.cookie_manager import update_cookies_from_response
                update_cookies_from_response(warmup_response)
                logger.debug("Warm-up de sessão bem-sucedido")
        except Exception as e:
            logger.debug(f"Erro durante warm-up: {e}")
    
    # Usar headers otimizados com referer realista
    referer = get_realistic_referer(f"https://betnacional.bet.br/event/1/1/{event_id}")
    headers = get_enhanced_headers_for_api()
    headers['Referer'] = referer
    
    try:
        # Fazer requisição com bypass automático (has_fallback=True reduz verbosidade)
        response = detector.make_request_with_bypass(
            session=session,
            url=api_url,
            method="GET",
            params=params,
            headers=headers,
            max_retries=3,
            use_cookies=True,
            has_fallback=True  # Há fallback HTML disponível
        )
        
        if response is None:
            # Não logar warning quando há fallback - apenas debug
            logger.debug("Falha ao fazer requisição com bypass, retornando None (fallback HTML disponível)")
            return None
        
        response.raise_for_status()
        return response.json()
    except Exception as e:
        from utils.error_handler import log_error_with_context
        log_error_with_context(
            e,
            context={
                "event_id": event_id,
                "language_id": language_id,
                "status_id": status_id,
                "stage": "fetch_event_odds_from_api"
            },
            level="warning",
            reraise=False,
            suppress_403_if_fallback=True  # Reduz verbosidade de 403 quando há fallback HTML
        )
        return None


def parse_event_odds_from_api(json_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converte dados JSON da API de evento individual para o formato esperado.
    
    Args:
        json_data: Dados JSON retornados pela API
    
    Returns:
        Dict com estrutura: {stats: {}, markets: {match_result: {...}, ...}}
    """
    data = {
        "stats": {},
        "markets": {}
    }
    
    if not json_data or 'events' not in json_data:
        return data
    
    events = json_data.get('events', [])
    if not events:
        return data
    
    # Pegar o primeiro evento (geralmente só há um)
    event = events[0]
    
    # Extrair informações básicas do evento
    event_id = event.get('event_id')
    home = event.get('home', '')
    away = event.get('away', '')
    event_status_id = event.get('event_status_id', 0)
    date_start = event.get('date_start', '')
    
    # Estatísticas básicas (se disponíveis na API)
    data["stats"]["event_id"] = event_id
    data["stats"]["home"] = home
    data["stats"]["away"] = away
    data["stats"]["event_status_id"] = event_status_id
    data["stats"]["date_start"] = date_start
    
    # Processar odds
    odds_list = event.get('odds', [])
    
    # Agrupar odds por market_id
    markets_dict = {}
    
    for odd_item in odds_list:
        market_id = odd_item.get('market_id')
        if not market_id:
            continue
        
        # FILTRAR POR MARKET_STATUS_ID: só processar mercados disponíveis (>= 0)
        market_status_id = odd_item.get('market_status_id', 1)
        if market_status_id < 0:  # -1 = mercado fechado/suspenso
            logger.debug(f"Market {market_id} ignorado: status {market_status_id} (fechado)")
            continue
        
        if market_id not in markets_dict:
            # Usar market_name se disponível para identificar o tipo de mercado
            market_name = odd_item.get('market_name', '')
            markets_dict[market_id] = {
                'market_id': market_id,
                'market_name': market_name,  # Nome do mercado para identificação
                'market_status_id': market_status_id,
                'odds': {},
                'odds_previous': {}  # Para tracking de mudanças
            }
        
        outcome_id = odd_item.get('outcome_id', '')
        outcome_name = odd_item.get('outcome_name', '')  # Nome do outcome
        odd_value = odd_item.get('odd')
        previous_odd = odd_item.get('previous_odd')
        
        if outcome_id and odd_value:
            try:
                odd_float = float(odd_value)
                # Validar range (1.0 a 100.0)
                if 1.0 <= odd_float <= 100.0:
                    # Armazenar outcome com nome se disponível
                    outcome_data = {
                        'odd': odd_float,
                        'name': outcome_name if outcome_name else None
                    }
                    
                    # Se previous_odd disponível, armazenar para detectar mudanças
                    if previous_odd is not None:
                        try:
                            prev_odd_float = float(previous_odd)
                            if 1.0 <= prev_odd_float <= 100.0:
                                outcome_data['previous_odd'] = prev_odd_float
                                # Calcular variação percentual
                                variation = ((odd_float - prev_odd_float) / prev_odd_float) * 100
                                outcome_data['variation_pct'] = variation
                        except (ValueError, TypeError):
                            pass
                    
                    markets_dict[market_id]['odds'][outcome_id] = outcome_data
                else:
                    logger.debug(f"Odd {outcome_id} inválida (fora do range): {odd_float}")
            except (ValueError, TypeError) as e:
                logger.debug(f"Erro ao converter odd {outcome_id}: {e}")
                pass
    
    # Mapeamento de market_id para tipo de mercado
    # Baseado na estrutura da API BetNacional
    MARKET_ID_MAP = {
        1: {"key": "match_result", "display_name": "Resultado Final"},
        # Placar Exato / Gols Exatos geralmente são market_id 2 ou 3
        # Handicap Asiático geralmente é market_id 4 ou 5
        # Vamos processar dinamicamente todos os mercados
    }
    
    # Converter markets para formato esperado
    # Market 1 = Resultado Final (1x2)
    if 1 in markets_dict:
        market_1 = markets_dict[1]
        odds = market_1.get('odds', {})
        market_name = market_1.get('market_name', 'Resultado Final')
        
        match_result = {}
        for outcome_id in ['1', '2', '3']:
            if outcome_id in odds:
                outcome_data = odds[outcome_id]
                if isinstance(outcome_data, dict):
                    odd_value = outcome_data.get('odd', outcome_data)
                    match_result['Casa' if outcome_id == '1' else 'Empate' if outcome_id == '2' else 'Fora'] = odd_value
                else:
                    match_result['Casa' if outcome_id == '1' else 'Empate' if outcome_id == '2' else 'Fora'] = outcome_data
        
        if match_result:
            data["markets"]["match_result"] = {
                "display_name": market_name if market_name else "Resultado Final",
                "options": match_result,
                "market_id": 1
            }
    
    # Processar outros mercados dinamicamente
    # Usar market_name para identificar o tipo de mercado quando disponível
    
    for market_id, market_data in markets_dict.items():
        if market_id == 1:  # Já processado acima
            continue
        
        odds = market_data.get('odds', {})
        if not odds:
            continue
        
        market_name = market_data.get('market_name', '').lower() if market_data.get('market_name') else ''
        outcome_ids = list(odds.keys())
        
        # USAR MARKET_NAME PARA IDENTIFICAR TIPO DE MERCADO
        market_key = None
        display_name = market_data.get('market_name', f'Market {market_id}')
        
        # Identificar por market_name
        if 'placar' in market_name or 'exato' in market_name or 'gols exatos' in market_name:
            market_key = "correct_score"
            display_name = "Placar Exato" if 'placar' in market_name else "Gols Exatos"
        elif 'handicap' in market_name and 'asiático' in market_name:
            market_key = "asian_handicap"
            display_name = "Handicap Asiático"
        elif 'ambos' in market_name and 'marcam' in market_name:
            market_key = "btts"
            display_name = "Ambos os Times Marcam"
        elif 'total' in market_name and 'gols' in market_name:
            market_key = "total_goals"
            display_name = "Total de Gols"
        
        # Se não identificou por market_name, tentar por outcome_ids
        if not market_key:
            # PLACAR EXATO / GOLS EXATOS
            # Outcomes especiais: pre:outcometext: ou ccc:outcometext: ou formato "0-0"
            if any(oid.startswith('pre:outcometext:') or oid.startswith('ccc:outcometext:') for oid in outcome_ids):
                market_key = "correct_score"
                display_name = "Placar Exato"
            elif any('-' in oid or 'x' in oid.lower() for oid in outcome_ids):
                score_pattern = re.compile(r'^\d+[-x]\d+$', re.IGNORECASE)
                if any(score_pattern.match(oid) for oid in outcome_ids):
                    market_key = "correct_score"
                    display_name = "Placar Exato"
            
            # HANDICAP ASIÁTICO
            if not market_key:
                handicap_pattern = re.compile(r'^H[-]?[\d.]+$|^AH[-]?[\d.]+$', re.IGNORECASE)
                if any(handicap_pattern.match(oid) for oid in outcome_ids):
                    market_key = "asian_handicap"
                    display_name = "Handicap Asiático"
        
        # Se ainda não identificou, usar nome genérico
        if not market_key:
            market_key = f"market_{market_id}"
            display_name = market_data.get('market_name', f'Market {market_id}')
        
        # Processar odds do mercado
        market_options = {}
        for oid, outcome_data in odds.items():
            if isinstance(outcome_data, dict):
                odd_value = outcome_data.get('odd', outcome_data)
                # Usar outcome_name se disponível, senão usar outcome_id
                outcome_display = outcome_data.get('name') or oid
                
                # Se tem previous_odd, incluir informação de mudança
                option_info = {'odd': odd_value}
                if 'previous_odd' in outcome_data:
                    option_info['previous_odd'] = outcome_data['previous_odd']
                if 'variation_pct' in outcome_data:
                    option_info['variation_pct'] = outcome_data['variation_pct']
                
                market_options[outcome_display] = option_info
            else:
                # Formato antigo (apenas número)
                market_options[oid] = outcome_data
        
        if market_options:
            data["markets"][market_key] = {
                "display_name": display_name,
                "options": market_options,
                "market_id": market_id,
                "market_status_id": market_data.get('market_status_id', 1)
            }
    
    logger.debug(f"📊 Evento {event_id}: {len(markets_dict)} mercados extraídos via API")
    return data


async def fetch_event_odds_from_api_async(event_id: int, language_id: int = 1, 
                                          status_id: int = 1) -> Optional[Dict[str, Any]]:
    """
    Wrapper assíncrono para fetch_event_odds_from_api com rate limiting e retry.
    """
    from utils.rate_limiter import api_rate_limiter, retry_with_backoff
    import requests
    
    async def _fetch():
        # Usar rate limiter antes de fazer requisição
        await api_rate_limiter.acquire()
        
        # Executar função síncrona em thread separada
        return await asyncio.to_thread(fetch_event_odds_from_api, event_id, language_id, status_id)
    
    # Tentar com retry (especialmente para 403 errors)
    try:
        return await retry_with_backoff(
            _fetch,
            max_retries=3,
            initial_delay=2.0,
            max_delay=30.0,
            exponential_base=2.0,
            exceptions=(requests.exceptions.HTTPError, requests.exceptions.RequestException, Exception),
            rate_limiter=None  # Já usamos dentro de _fetch
        )
    except Exception as e:
        logger.warning(f"Erro ao buscar odds do evento {event_id} após retries: {e}")
        return None


def num_from_text(s: str) -> Optional[float]:
    """Extrai um número de um texto."""
    if not s:
        return None
    s = s.replace(",", ".")
    s = "".join(ch for ch in s if ch.isdigit() or ch == ".")
    try:
        v = float(s)
        return v if v >= 1.01 else None
    except:
        return None


def _num(txt: str) -> Optional[float]:
    """Extrai número de um texto usando regex."""
    if not txt:
        return None
    txt = txt.strip().replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", txt)
    return float(m.group(0)) if m else None


def parse_local_datetime(s: str) -> Optional[datetime]:
    """
    Converte string de data/hora local para datetime UTC aware.
    Suporta formatos: ISO-8601, "H:M d/m/Y", "H:M", etc.
    """
    if not s:
        return None
    s = s.strip()
    
    # 1) tentar ISO-8601 (com Z ou offset)
    try:
        s_iso = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s_iso)
        if dt.tzinfo is None:
            dt_local = ZONE.localize(dt)
            return dt_local.astimezone(pytz.UTC)
        return dt.astimezone(pytz.UTC)
    except Exception:
        pass
    
    # 2) formatos legados
    fmts = [
        "%H:%M %d/%m/%Y", "%H:%M %d/%m/%y",
        "%d/%m/%Y %H:%M", "%d/%m/%y %H:%M",
        "%d/%m %H:%M", "%H:%M",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            if "%Y" not in fmt and "%y" not in fmt:
                nowl = datetime.now(ZONE)
                dt = dt.replace(year=nowl.year)
            if fmt == "%H:%M":
                nowl = datetime.now(ZONE)
                dt = dt.replace(day=nowl.day, month=nowl.month, year=nowl.year)
            dt_local = ZONE.localize(dt)
            return dt_local.astimezone(pytz.UTC)
        except Exception as e:
            # Erro ao parsear data - não é crítico, continuar tentando outros formatos
            logger.debug(f"Erro ao parsear data '{s}' com formato '{fmt}': {e}")
            continue
    return None


def _date_from_header_text(txt: str) -> Optional[datetime]:
    """
    Converte textos como "Hoje", "Amanhã", "13 setembro" em um datetime local com hora 00:00.
    """
    t = (txt or "").strip().lower()
    if not t:
        return None
    if "hoje" in t:
        nowl = datetime.now(ZONE)
        return nowl.replace(hour=0, minute=0, second=0, microsecond=0)
    if "amanhã" in t or "amanha" in t:
        nowl = datetime.now(ZONE) + timedelta(days=1)
        return nowl.replace(hour=0, minute=0, second=0, microsecond=0)
    if "ontem" in t:
        nowl = datetime.now(ZONE) - timedelta(days=1)
        return nowl.replace(hour=0, minute=0, second=0, microsecond=0)
    m = re.search(r"(\d{1,2})\s+([a-zç]+)", t)
    if m:
        day = int(m.group(1))
        mon_name = m.group(2)
        mon = _PT_MONTHS.get(mon_name, None)
        if mon:
            nowl = datetime.now(ZONE)
            dt = nowl.replace(month=mon, day=day, hour=0, minute=0, second=0, microsecond=0)
            return dt
    return None


def _try_parse_from_next_data(html: str, url: str) -> List[Any]:
    """
    Tenta extrair eventos do JSON __NEXT_DATA__ quando o HTML estático não tem conteúdo renderizado.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if not script_tag:
            return []
        
        data = json.loads(script_tag.string)
        
        # Navegar pela estrutura do Next.js para encontrar eventos
        # A estrutura pode variar, então tentamos vários caminhos
        events_data = None
        if "props" in data and "pageProps" in data["props"]:
            page_props = data["props"]["pageProps"]
            if "initialState" in page_props:
                events_data = page_props["initialState"].get("events", {}).get("queries", {})
        
        if not events_data:
            logger.debug("Não foi possível encontrar dados de eventos no __NEXT_DATA__")
            return []
        
        # TODO: Implementar parsing completo do JSON quando conhecermos a estrutura exata
        logger.info("Dados encontrados no __NEXT_DATA__, mas estrutura precisa ser mapeada")
        return []
        
    except Exception as e:
        logger.debug(f"Erro ao extrair dados do __NEXT_DATA__: {e}")
        return []


def try_parse_events(html: str, url: str) -> List[Any]:
    """
    Parser adaptado ao HTML do BetNacional.
    Processa a estrutura de cabeçalhos de data seguidos pelos jogos correspondentes.
    Tenta primeiro parsing HTML, depois fallback para JSON __NEXT_DATA__.
    """
    soup = BeautifulSoup(html, "html.parser")
    evs = []
    
    all_elements = soup.find_all(['div'])
    
    current_date_header = None
    current_date = None
    
    for element in all_elements:
        # Verifica se é um cabeçalho de data
        classes = element.get('class', [])
        if any('text-odds-subheader-text' in cls for cls in classes):
            header_text = element.get_text(strip=True)
            current_date_header = header_text
            current_date = _date_from_header_text(header_text)
            logger.info(f"📅 Processando jogos de: {header_text} -> {current_date}")
            continue
            
        # Verifica se é um cartão de jogo
        if element.get('data-testid') == 'preMatchOdds':
            if not current_date:
                logger.warning("Jogo encontrado sem cabeçalho de data precedente")
                continue
                
            a = element.select_one('a[href*="/event/"]')
            if not a:
                continue
                
            href = a.get("href", "")
            m = re.search(r"/event/\d+/\d+/(\d+)", href)
            ext_id = m.group(1) if m else ""
            
            # URL completa da página do jogo
            game_url = urljoin(url, href)

            # nomes
            title = a.get_text(" ", strip=True)
            team_home, team_away = "", ""
            if " x " in title:
                team_home, team_away = [p.strip() for p in title.split(" x ", 1)]
            else:
                names = [s.get_text(strip=True) for s in a.select("span.text-ellipsis")]
                if len(names) >= 2:
                    team_home, team_away = names[0], names[1]

            # detectar "Ao Vivo" - múltiplas estratégias
            is_live = False
            
            # Estratégia 1: Procurar por texto "Ao Vivo" em qualquer lugar do elemento
            live_texts = ["Ao Vivo", "Ao vivo", "LIVE", "Live", "live"]
            element_text = element.get_text(strip=True).lower()
            for live_text in live_texts:
                if live_text.lower() in element_text:
                    is_live = True
                    break
            
            # Estratégia 2: Procurar por badges ou indicadores visuais
            if not is_live:
                # Procurar por classes CSS comuns de jogos ao vivo
                live_indicators = element.select(
                    '[class*="live"], [class*="Live"], [class*="LIVE"], '
                    '[class*="ao-vivo"], [class*="ao_vivo"], '
                    '[data-live="true"], [data-status="live"]'
                )
                if live_indicators:
                    is_live = True
            
            # Estratégia 3: Procurar por atributos específicos do BetNacional
            if not is_live:
                # Verificar se o elemento pai ou filhos têm indicadores de live
                parent = element.parent
                if parent:
                    parent_text = parent.get_text(strip=True).lower()
                    for live_text in live_texts:
                        if live_text.lower() in parent_text:
                            is_live = True
                            break
                
                # Verificar badges de status ao vivo
                live_badges = element.select('[data-testid*="live"], [data-testid*="Live"]')
                if live_badges:
                    is_live = True
            
            # Estratégia 4: Verificar se o href contém indicadores de live
            if not is_live and href:
                if "/live/" in href.lower() or "live=true" in href.lower():
                    is_live = True

            # hora local
            t = element.select_one(".text-text-light-secondary")
            hour_local = t.get_text(strip=True) if t else ""
            
            # Combina a data do cabeçalho com a hora do jogo
            start_local_str = hour_local
            if hour_local and current_date:
                hour_match = re.search(r"(\d{1,2}):(\d{2})", hour_local)
                if hour_match:
                    hour = int(hour_match.group(1))
                    minute = int(hour_match.group(2))
                    combined_dt = current_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    start_local_str = combined_dt.strftime("%H:%M %d/%m/%Y")
                    logger.debug(f"  → {team_home} vs {team_away} às {start_local_str}")
                else:
                    start_local_str = current_date.strftime("%d/%m/%Y")

            # odds
            def pick_cell(i: int):
                if ext_id:
                    c = element.select_one(f"[data-testid='odd-{ext_id}_1_{i}_']")
                    if c:
                        return _num(c.get_text(" ", strip=True))
                return None

            odd_home = pick_cell(1)
            odd_draw = pick_cell(2)
            odd_away = pick_cell(3)

            if odd_home is None or odd_draw is None or odd_away is None:
                cells = element.select("[data-testid^='odd-'][data-testid$='_']")
                if ext_id:
                    cells = [c for c in cells if c.get("data-testid", "").startswith(f"odd-{ext_id}_1_")]
                def col_index(c):
                    mm = re.search(r"_1_(\d)_", c.get("data-testid", ""))
                    return int(mm.group(1)) if mm else 99
                cells = sorted(cells, key=col_index)
                vals = [_num(c.get_text(" ", strip=True)) for c in cells[:3]]
                if len(vals) >= 3:
                    odd_home, odd_draw, odd_away = vals

            evs.append(NS(
                ext_id=ext_id,
                source_link=url,
                game_url=game_url, 
                competition="",
                team_home=team_home,
                team_away=team_away,
                start_local_str=start_local_str,
                odds_home=odd_home,
                odds_draw=odd_draw,
                odds_away=odd_away,
                is_live=is_live,
            ))

    from utils.logger import log_with_context
    log_with_context(
        "info",
        f"Eventos extraídos via HTML: {len(evs)} eventos",
        url=url,
        stage="parse_events_html",
        status="success",
        extra_fields={"events_count": len(evs), "method": "html"}
    )
    
    # Se não encontrou eventos no HTML renderizado, tenta extrair do JSON
    if not evs:
        logger.info("Tentando extrair eventos do JSON __NEXT_DATA__...")
        evs_from_json = _try_parse_from_next_data(html, url)
        if evs_from_json:
            logger.info(f"✅ Eventos extraídos do JSON: {len(evs_from_json)}")
            return evs_from_json
    
    return evs


def scrape_game_result(html: str, ext_id: str) -> Optional[str]:
    """
    Tenta extrair o resultado final (home/draw/away) da página HTML de um jogo encerrado.
    
    Usa múltiplas estratégias para maior robustez:
    1. Detectar se jogo está finalizado (procurar por "Término", "Finalizado", etc.)
    2. Extrair do placar final do live-tracker-component (MAIS CONFIÁVEL)
    3. Extrair do placar final do scoreboard (data-testid="scoreboard")
    4. Buscar em elementos de resultado final
    5. Procurar texto "Vencedor" (fallback)
    6. Procurar classes CSS de vencedor (fallback)
    """
    soup = BeautifulSoup(html, "html.parser")

    # PRIMEIRO: Verificar se o jogo está finalizado
    # Procurar por indicadores de jogo finalizado
    ended_indicators = [
        "Término", "Finalizado", "Encerrado", "Terminado", "Final",
        "FT", "Fim", "Terminou", "Acabou"
    ]
    html_text_lower = html.lower()
    is_ended = any(indicator.lower() in html_text_lower for indicator in ended_indicators)
    
    if not is_ended:
        # Procurar por status no live-tracker-component
        lmt_tracker = soup.find("div", {"data-testid": "liveMatchTracker"})
        if lmt_tracker:
            tracker_text = lmt_tracker.get_text(" ", strip=True).lower()
            is_ended = any(indicator.lower() in tracker_text for indicator in ended_indicators)
    
    # Se não detectou que está finalizado, ainda pode tentar extrair resultado (pode estar em transição)
    if not is_ended:
        logger.debug(f"Jogo {ext_id}: não detectado como finalizado, mas tentando extrair resultado mesmo assim")

    # ESTRATÉGIA 1: Extrair do placar final do live-tracker-component (MAIS CONFIÁVEL)
    # Procurar primeiro no data-testid="liveMatchTracker" conforme especificado pelo usuário
    lmt_tracker = soup.find("div", {"data-testid": "liveMatchTracker"})
    if lmt_tracker:
        lmt_container = lmt_tracker.find("div", id="lmt-match-preview") or lmt_tracker.find("div", class_=lambda x: x and "live-tracker-component" in str(x))
        if lmt_container:
            try:
                # Tentar extrair placar do scoreboard dentro do live-tracker
                scoreboard = lmt_container.find("div", {"data-testid": "scoreboard"})
                if scoreboard:
                    # Procurar por placar na estrutura do scoreboard
                    score_elements = scoreboard.select(".sr-lmt-1-sbr__score, [class*='score']")
                    if len(score_elements) >= 2:
                        home_goals_raw = score_elements[0].get_text(strip=True)
                        away_goals_raw = score_elements[1].get_text(strip=True)
                        
                        # Validar placar antes de usar
                        from utils.validators import validate_score
                        validated_score = validate_score(home_goals_raw, away_goals_raw)
                        if validated_score:
                            home_goals, away_goals = validated_score
                            
                            # Determinar resultado pelo placar
                            from utils.logger import log_with_context
                            if home_goals > away_goals:
                                result = "home"
                                log_with_context(
                                    "info",
                                    f"Resultado extraído do placar final (live-tracker): {home_goals}-{away_goals} → home",
                                    ext_id=ext_id,
                                    stage="scrape_result",
                                    status="success",
                                    extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "live_tracker_scoreboard"}
                                )
                                return result
                            elif away_goals > home_goals:
                                result = "away"
                                log_with_context(
                                    "info",
                                    f"Resultado extraído do placar final (live-tracker): {home_goals}-{away_goals} → away",
                                    ext_id=ext_id,
                                    stage="scrape_result",
                                    status="success",
                                    extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "live_tracker_scoreboard"}
                                )
                                return result
                            else:
                                result = "draw"
                                log_with_context(
                                    "info",
                                    f"Resultado extraído do placar final (live-tracker): {home_goals}-{away_goals} → draw",
                                    ext_id=ext_id,
                                    stage="scrape_result",
                                    status="success",
                                    extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "live_tracker_scoreboard"}
                                )
                                return result
                
                # Fallback: tentar extrair placar diretamente do lmt-container
                score_elements = lmt_container.select(".sr-lmt-1-sbr__score")
                if len(score_elements) >= 2:
                    home_goals_raw = score_elements[0].get_text(strip=True)
                    away_goals_raw = score_elements[1].get_text(strip=True)
                    
                    # Validar placar antes de usar
                    from utils.validators import validate_score
                    validated_score = validate_score(home_goals_raw, away_goals_raw)
                    if validated_score:
                        home_goals, away_goals = validated_score
                        
                        # Determinar resultado pelo placar
                        from utils.logger import log_with_context
                        if home_goals > away_goals:
                            result = "home"
                            log_with_context(
                                "info",
                                f"Resultado extraído do placar final (lmt-container): {home_goals}-{away_goals} → home",
                                ext_id=ext_id,
                                stage="scrape_result",
                                status="success",
                                extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "lmt_container"}
                            )
                            return result
                        elif away_goals > home_goals:
                            result = "away"
                            log_with_context(
                                "info",
                                f"Resultado extraído do placar final (lmt-container): {home_goals}-{away_goals} → away",
                                ext_id=ext_id,
                                stage="scrape_result",
                                status="success",
                                extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "lmt_container"}
                            )
                            return result
                        else:
                            result = "draw"
                            log_with_context(
                                "info",
                                f"Resultado extraído do placar final (lmt-container): {home_goals}-{away_goals} → draw",
                                ext_id=ext_id,
                                stage="scrape_result",
                                status="success",
                                extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "lmt_container"}
                            )
                            return result
                    else:
                        logger.debug(f"Placar inválido ignorado para {ext_id}: {home_goals_raw}-{away_goals_raw}")
            except (ValueError, IndexError, AttributeError) as e:
                logger.debug(f"Erro ao extrair placar do live-tracker: {e}")

    # ESTRATÉGIA 2: Extrair do scoreboard principal (data-testid="scoreboard")
    scoreboard = soup.find("div", {"data-testid": "scoreboard"})
    if scoreboard:
        try:
            # Tentar extrair placar da tabela do scoreboard
            table = scoreboard.find("table")
            if table:
                rows = table.find_all("tr")
                if len(rows) >= 3:
                    # Linha 1: time da casa (geralmente linha 1)
                    home_row = rows[1]
                    home_cells = home_row.find_all("td")
                    if len(home_cells) >= 6:
                        home_goals_raw = home_cells[5].get_text(strip=True)  # Última coluna geralmente é gols
                        
                    # Linha 2: time visitante (geralmente linha 2)
                    away_row = rows[2]
                    away_cells = away_row.find_all("td")
                    if len(away_cells) >= 6:
                        away_goals_raw = away_cells[5].get_text(strip=True)
                        
                        # Validar placar antes de usar
                        from utils.validators import validate_score
                        validated_score = validate_score(home_goals_raw, away_goals_raw)
                        if validated_score:
                            home_goals, away_goals = validated_score
                            
                            # Determinar resultado pelo placar
                            from utils.logger import log_with_context
                            if home_goals > away_goals:
                                result = "home"
                                log_with_context(
                                    "info",
                                    f"Resultado extraído do scoreboard: {home_goals}-{away_goals} → home",
                                    ext_id=ext_id,
                                    stage="scrape_result",
                                    status="success",
                                    extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "scoreboard_table"}
                                )
                                return result
                            elif away_goals > home_goals:
                                result = "away"
                                log_with_context(
                                    "info",
                                    f"Resultado extraído do scoreboard: {home_goals}-{away_goals} → away",
                                    ext_id=ext_id,
                                    stage="scrape_result",
                                    status="success",
                                    extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "scoreboard_table"}
                                )
                                return result
                            else:
                                result = "draw"
                                log_with_context(
                                    "info",
                                    f"Resultado extraído do scoreboard: {home_goals}-{away_goals} → draw",
                                    ext_id=ext_id,
                                    stage="scrape_result",
                                    status="success",
                                    extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "scoreboard_table"}
                                )
                                return result
        except (ValueError, IndexError, AttributeError) as e:
            logger.debug(f"Erro ao extrair placar do scoreboard: {e}")

    # ESTRATÉGIA 3: Extrair do placar final (fallback para estrutura antiga)
    lmt_container = soup.find("div", id="lmt-match-preview")
    if lmt_container:
        try:
            score_elements = lmt_container.select(".sr-lmt-1-sbr__score")
            if len(score_elements) >= 2:
                home_goals_raw = score_elements[0].get_text(strip=True)
                away_goals_raw = score_elements[1].get_text(strip=True)
                
                # Validar placar antes de usar
                from utils.validators import validate_score
                validated_score = validate_score(home_goals_raw, away_goals_raw)
                if validated_score:
                    home_goals, away_goals = validated_score
                    
                    # Determinar resultado pelo placar
                    from utils.logger import log_with_context
                    if home_goals > away_goals:
                        result = "home"
                        log_with_context(
                            "info",
                            f"Resultado extraído do placar: {home_goals}-{away_goals} → home",
                            ext_id=ext_id,
                            stage="scrape_result",
                            status="success",
                            extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "placar_final"}
                        )
                        return result
                    elif away_goals > home_goals:
                        result = "away"
                        log_with_context(
                            "info",
                            f"Resultado extraído do placar: {home_goals}-{away_goals} → away",
                            ext_id=ext_id,
                            stage="scrape_result",
                            status="success",
                            extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "placar_final"}
                        )
                        return result
                    else:
                        result = "draw"
                        log_with_context(
                            "info",
                            f"Resultado extraído do placar: {home_goals}-{away_goals} → draw",
                            ext_id=ext_id,
                            stage="scrape_result",
                            status="success",
                            extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "placar_final"}
                        )
                        return result
                else:
                    logger.debug(f"Placar inválido ignorado para {ext_id}: {home_goals_raw}-{away_goals_raw}")
        except (ValueError, IndexError, AttributeError) as e:
            logger.debug(f"Erro ao extrair placar do lmt-container: {e}")

    # ESTRATÉGIA 4: Buscar padrões de placar em todo o HTML (mais genérico)
    # Procurar por qualquer padrão de placar no texto do HTML
    all_text = soup.get_text(" ", strip=True)
    # Procurar padrões como "2 - 1", "2:1", "2 x 1", "2x1", "(2-1)", etc.
    score_patterns = [
        r'(\d+)\s*[-:x×]\s*(\d+)',  # Padrão básico: "2 - 1", "2:1", "2 x 1"
        r'\((\d+)\s*[-:x]\s*(\d+)\)',  # Com parênteses: "(2-1)"
        r'\[(\d+)\s*[-:x]\s*(\d+)\]',  # Com colchetes: "[2-1]"
    ]
    
    for pattern in score_patterns:
        matches = re.finditer(pattern, all_text, re.IGNORECASE)
        for match in matches:
            try:
                home_goals_raw = match.group(1)
                away_goals_raw = match.group(2)
                
                # Validar placar antes de usar
                from utils.validators import validate_score
                validated_score = validate_score(home_goals_raw, away_goals_raw)
                if validated_score:
                    home_goals, away_goals = validated_score
                    from utils.logger import log_with_context
                    # Só considerar se o placar está em um contexto relevante (não muito aleatório)
                    # Verificar se está próximo de palavras relacionadas a futebol/jogo
                    match_start = match.start()
                    context_start = max(0, match_start - 50)
                    context_end = min(len(all_text), match_start + 50)
                    context = all_text[context_start:context_end].lower()
                    
                    # Procurar por palavras-chave que indicam contexto de placar
                    context_keywords = ['gol', 'score', 'placar', 'resultado', 'final', 'time', 'casa', 'fora', 'visitante']
                    if any(keyword in context for keyword in context_keywords) or match_start < 5000:  # Primeiros 5000 chars geralmente têm o placar
                        if home_goals > away_goals:
                            result = "home"
                            log_with_context(
                                "info",
                                f"Resultado encontrado via padrão genérico: {home_goals}-{away_goals} → home",
                                ext_id=ext_id,
                                stage="scrape_result",
                                status="success",
                                extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "padrao_generico"}
                            )
                            return result
                        elif away_goals > home_goals:
                            result = "away"
                            log_with_context(
                                "info",
                                f"Resultado encontrado via padrão genérico: {home_goals}-{away_goals} → away",
                                ext_id=ext_id,
                                stage="scrape_result",
                                status="success",
                                extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "padrao_generico"}
                            )
                            return result
                        else:
                            result = "draw"
                            log_with_context(
                                "info",
                                f"Resultado encontrado via padrão genérico: {home_goals}-{away_goals} → draw",
                                ext_id=ext_id,
                                stage="scrape_result",
                                status="success",
                                extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "padrao_generico"}
                            )
                            return result
            except (ValueError, AttributeError) as e:
                logger.debug(f"Erro ao processar padrão de placar: {e}")
                continue

    # ESTRATÉGIA 5: Buscar em elementos de resultado final (seletor específico)
    # Procurar por padrões de placar em vários elementos
    result_elements = soup.select(
        '.final-score, .match-result, [class*="result"], [class*="final"], '
        '.score, [class*="score"], .sr-lmt-1-sbr__score, [class*="lmt"], [class*="match"]'
    )
    for elem in result_elements:
        text = elem.get_text(strip=True)
        # Procurar padrão "2 - 1", "2:1", "2 x 1", "2x1"
        match = re.search(r'(\d+)\s*[-:x×]\s*(\d+)', text)
        if match:
            try:
                home_goals_raw = match.group(1)
                away_goals_raw = match.group(2)
                
                # Validar placar antes de usar
                from utils.validators import validate_score
                validated_score = validate_score(home_goals_raw, away_goals_raw)
                if validated_score:
                    home_goals, away_goals = validated_score
                    from utils.logger import log_with_context
                    if home_goals > away_goals:
                        result = "home"
                        log_with_context(
                            "debug",
                            f"Resultado encontrado em elemento de resultado: {home_goals}-{away_goals} → home",
                            ext_id=ext_id,
                            stage="scrape_result",
                            status="success",
                            extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "elementos_resultado"}
                        )
                        return result
                    elif away_goals > home_goals:
                        result = "away"
                        log_with_context(
                            "debug",
                            f"Resultado encontrado em elemento de resultado: {home_goals}-{away_goals} → away",
                            ext_id=ext_id,
                            stage="scrape_result",
                            status="success",
                            extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "elementos_resultado"}
                        )
                        return result
                    else:
                        result = "draw"
                        log_with_context(
                            "debug",
                            f"Resultado encontrado em elemento de resultado: {home_goals}-{away_goals} → draw",
                            ext_id=ext_id,
                            stage="scrape_result",
                            status="success",
                            extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "elementos_resultado"}
                        )
                        return result
            except (ValueError, AttributeError) as e:
                logger.debug(f"Erro ao validar placar do elemento: {e}")
                continue

    # ESTRATÉGIA 3: Procurar por um badge ou texto que diga "Vencedor" ou similar (fallback)
    winner_indicators = [
        soup.find(string=lambda text: text and "Vencedor" in text),
        soup.find(string=lambda text: text and "Winner" in text),
    ]

    for indicator in winner_indicators:
        if indicator:
            parent_text = indicator.parent.get_text(strip=True) if indicator.parent else ""
            from utils.logger import log_with_context
            if "Casa" in parent_text or "Home" in parent_text:
                log_with_context(
                    "debug",
                    "Resultado encontrado via texto 'Vencedor': home",
                    ext_id=ext_id,
                    stage="scrape_result",
                    status="success",
                    extra_fields={"result": "home", "strategy": "texto_vencedor"}
                )
                return "home"
            elif "Fora" in parent_text or "Away" in parent_text:
                log_with_context(
                    "debug",
                    "Resultado encontrado via texto 'Vencedor': away",
                    ext_id=ext_id,
                    stage="scrape_result",
                    status="success",
                    extra_fields={"result": "away", "strategy": "texto_vencedor"}
                )
                return "away"
            elif "Empate" in parent_text or "Draw" in parent_text:
                log_with_context(
                    "debug",
                    "Resultado encontrado via texto 'Vencedor': draw",
                    ext_id=ext_id,
                    stage="scrape_result",
                    status="success",
                    extra_fields={"result": "draw", "strategy": "texto_vencedor"}
                )
                return "draw"

    # ESTRATÉGIA 4: Procurar por classes CSS comuns em elementos de vencedor (fallback)
    winner_elements = soup.select('.winner, .vencedor, .champion, [class*="winner"], [class*="vencedor"]')
    for elem in winner_elements:
        elem_text = elem.get_text(strip=True).lower()
        from utils.logger import log_with_context
        if "casa" in elem_text or "home" in elem_text:
            log_with_context(
                "debug",
                "Resultado encontrado via classe CSS: home",
                ext_id=ext_id,
                stage="scrape_result",
                status="success",
                extra_fields={"result": "home", "strategy": "classes_css"}
            )
            return "home"
        elif "fora" in elem_text or "away" in elem_text:
            log_with_context(
                "debug",
                "Resultado encontrado via classe CSS: away",
                ext_id=ext_id,
                stage="scrape_result",
                status="success",
                extra_fields={"result": "away", "strategy": "classes_css"}
            )
            return "away"
        elif "empate" in elem_text or "draw" in elem_text:
            log_with_context(
                "debug",
                "Resultado encontrado via classe CSS: draw",
                ext_id=ext_id,
                stage="scrape_result",
                status="success",
                extra_fields={"result": "draw", "strategy": "classes_css"}
            )
            return "draw"

    # ESTRATÉGIA 6: Procurar por elementos com números grandes que podem ser placares
    # Procurar por divs/spans com classes que podem conter placares
    potential_score_elements = soup.select(
        '[class*="score"], [class*="goals"], [class*="result"], '
        '[class*="sbr"], [class*="scb"], [class*="match-score"], '
        'div[class*="number"], span[class*="number"], '
        '[class*="sr-lmt"], [class*="sr-"]'
    )
    
    score_numbers = []
    for elem in potential_score_elements:
        text = elem.get_text(strip=True)
        # Procurar por números isolados (0-9) que podem ser gols
        numbers = re.findall(r'\b([0-9])\b', text)
        if numbers and len(numbers) >= 2:
            # Tentar combinar números adjacentes como placar
            for i in range(len(numbers) - 1):
                try:
                    home_goals_raw = numbers[i]
                    away_goals_raw = numbers[i + 1]
                    from utils.validators import validate_score
                    validated_score = validate_score(home_goals_raw, away_goals_raw)
                    if validated_score:
                        score_numbers.append((validated_score[0], validated_score[1], elem))
                except:
                    continue
    
    # Se encontrou placares potenciais, usar o primeiro válido
    if score_numbers:
        home_goals, away_goals, elem = score_numbers[0]
        from utils.logger import log_with_context
        if home_goals > away_goals:
            result = "home"
            log_with_context(
                "info",
                f"Resultado encontrado via elementos numéricos: {home_goals}-{away_goals} → home",
                ext_id=ext_id,
                stage="scrape_result",
                status="success",
                extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "elementos_numericos"}
            )
            return result
        elif away_goals > home_goals:
            result = "away"
            log_with_context(
                "info",
                f"Resultado encontrado via elementos numéricos: {home_goals}-{away_goals} → away",
                ext_id=ext_id,
                stage="scrape_result",
                status="success",
                extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "elementos_numericos"}
            )
            return result
        else:
            result = "draw"
            log_with_context(
                "info",
                f"Resultado encontrado via elementos numéricos: {home_goals}-{away_goals} → draw",
                ext_id=ext_id,
                stage="scrape_result",
                status="success",
                extra_fields={"score": f"{home_goals}-{away_goals}", "result": result, "strategy": "elementos_numericos"}
            )
            return result

    # Se nenhuma estratégia funcionou, logar informações de debug
    from utils.logger import log_with_context
    
    # Extrair informações úteis para debug
    debug_info = {
        "strategies_tried": 6,
        "has_lmt_tracker": bool(soup.find("div", {"data-testid": "liveMatchTracker"})),
        "has_lmt_preview": bool(soup.find("div", id="lmt-match-preview")),
        "has_scoreboard": bool(soup.find("div", {"data-testid": "scoreboard"})),
        "html_length": len(html),
        "text_length": len(soup.get_text())
    }
    
    # Tentar encontrar qualquer padrão de placar no HTML para debug
    all_text_preview = soup.get_text(" ", strip=True)[:1000]  # Primeiros 1000 chars
    score_matches = re.findall(r'\d+\s*[-:x×]\s*\d+', all_text_preview)
    if score_matches:
        debug_info["found_score_patterns"] = score_matches[:5]  # Primeiros 5 padrões encontrados
    
    log_with_context(
        "warning",
        f"Não foi possível determinar o vencedor após tentar 6 estratégias. Debug: {debug_info}",
        ext_id=ext_id,
        stage="scrape_result",
        status="failed",
        extra_fields=debug_info
    )
    
    # Log adicional para ajudar no debug
    logger.debug(f"Jogo {ext_id}: HTML preview (primeiros 500 chars): {html[:500]}")
    logger.debug(f"Jogo {ext_id}: Text preview (primeiros 500 chars): {all_text_preview[:500]}")
    
    return None


def scrape_live_game_data(html: str, ext_id: str, source_url: str = None) -> Dict[str, Any]:
    """
    Extrai TUDO de uma página de jogo ao vivo: estatísticas e odds dos principais mercados.
    
    Usa APENAS HTML scraping (XHR desativado).
    
    Args:
        html: HTML da página
        ext_id: ID externo do evento
        source_url: URL de origem do evento (não usado, mantido para compatibilidade)
    """
    # Usar APENAS HTML scraping (XHR desativado)
    logger.debug(f"🌐 Usando HTML scraping para evento {ext_id} (XHR desativado)")
    soup = BeautifulSoup(html, "html.parser")
    data = {
        "stats": {},
        "markets": {}
    }

    # --- 1. Extrair Estatísticas (Placar, Tempo, etc) ---
    # Estratégia 1: Procurar scoreboard com data-testid="scoreboard"
    scoreboard = soup.find("div", {"data-testid": "scoreboard"})
    if scoreboard:
        try:
            # Extrair tabela dentro do scoreboard
            table = scoreboard.find("table")
            if table:
                rows = table.find_all("tr")
                
                # Primeira linha: cabeçalho com tempo e estatísticas
                if len(rows) > 0:
                    header_row = rows[0]
                    # Extrair tempo (primeira célula)
                    time_cell = header_row.find("td")
                    if time_cell:
                        time_text = time_cell.get_text(strip=True)
                        # Remover ícones e extrair apenas números
                        time_match = re.search(r'(\d+)', time_text)
                        if time_match:
                            data["stats"]["match_time"] = time_match.group(1)
                            data["stats"]["match_time_raw"] = time_text
                
                # Próximas linhas: times com estatísticas
                if len(rows) >= 3:
                    # Linha 1: Time da casa
                    home_row = rows[1]
                    home_cells = home_row.find_all("td")
                    if len(home_cells) >= 6:
                        home_team = home_cells[0].get_text(strip=True)
                        home_corners = home_cells[1].get_text(strip=True)
                        home_yellow = home_cells[2].get_text(strip=True)
                        home_red = home_cells[3].get_text(strip=True)
                        home_penalties = home_cells[4].get_text(strip=True)
                        home_goals = home_cells[5].get_text(strip=True)
                        
                        data["stats"]["home_team"] = home_team
                        data["stats"]["home_corners"] = int(home_corners) if home_corners.isdigit() else 0
                        data["stats"]["home_yellow_cards"] = int(home_yellow) if home_yellow.isdigit() else 0
                        data["stats"]["home_red_cards"] = int(home_red) if home_red.isdigit() else 0
                        data["stats"]["home_penalties"] = int(home_penalties) if home_penalties.isdigit() else 0
                        data["stats"]["home_goals"] = int(home_goals) if home_goals.isdigit() else 0
                    
                    # Linha 2: Time visitante
                    away_row = rows[2]
                    away_cells = away_row.find_all("td")
                    if len(away_cells) >= 6:
                        away_team = away_cells[0].get_text(strip=True)
                        away_corners = away_cells[1].get_text(strip=True)
                        away_yellow = away_cells[2].get_text(strip=True)
                        away_red = away_cells[3].get_text(strip=True)
                        away_penalties = away_cells[4].get_text(strip=True)
                        away_goals = away_cells[5].get_text(strip=True)
                        
                        data["stats"]["away_team"] = away_team
                        data["stats"]["away_corners"] = int(away_corners) if away_corners.isdigit() else 0
                        data["stats"]["away_yellow_cards"] = int(away_yellow) if away_yellow.isdigit() else 0
                        data["stats"]["away_red_cards"] = int(away_red) if away_red.isdigit() else 0
                        data["stats"]["away_penalties"] = int(away_penalties) if away_penalties.isdigit() else 0
                        data["stats"]["away_goals"] = int(away_goals) if away_goals.isdigit() else 0
                        
                        # Criar placar
                        if "home_goals" in data["stats"] and "away_goals" in data["stats"]:
                            data["stats"]["score"] = f"{data['stats']['home_goals']} - {data['stats']['away_goals']}"
                            
        except Exception as e:
            logger.debug(f"Erro ao extrair estatísticas do scoreboard para jogo {ext_id}: {e}")
    
    # Estratégia 2: Fallback para estrutura antiga (lmt-match-preview)
    if not data["stats"].get("score"):
        lmt_container = soup.find("div", id="lmt-match-preview")
        if lmt_container:
            try:
                # Placar
                score_elements = lmt_container.select(".sr-lmt-1-sbr__score")
                if len(score_elements) >= 2:
                    home_goals = int(score_elements[0].get_text(strip=True))
                    away_goals = int(score_elements[1].get_text(strip=True))
                    data["stats"]["score"] = f"{home_goals} - {away_goals}"
                    data["stats"]["home_goals"] = home_goals
                    data["stats"]["away_goals"] = away_goals

                # Tempo de Jogo
                if not data["stats"].get("match_time"):
                    time_element = lmt_container.select_one(".sr-lmt-clock-v2__time")
                    if time_element:
                        data["stats"]["match_time"] = time_element.get_text(strip=True)

                # Último Evento (Gol, Cartão, etc)
                last_event_element = lmt_container.select_one(".sr-lmt-1-evt__text-content")
                if last_event_element:
                    data["stats"]["last_event"] = last_event_element.get_text(" ", strip=True)
                
            except Exception as e:
                logger.debug(f"Erro ao extrair estatísticas do lmt-container para jogo {ext_id}: {e}")
    
    # Tenta extrair estatísticas adicionais usando função auxiliar
    try:
        from betting.live_validator import expand_live_game_stats
        expanded = expand_live_game_stats(str(soup))
        if expanded:
            # Merge sem sobrescrever dados já extraídos
            for key, value in expanded.items():
                if key not in data["stats"]:
                    data["stats"][key] = value
    except Exception:
        pass  # Não crítico se não conseguir extrair

    # --- 2. Extrair Mercados de Apostas ---
    market_name_map = {
        "Resultado Final": "match_result",
        "Ambos os Times Marcam": "btts",
        "Total": "total_goals",
        "Total de Gols": "total_goals",
        "Placar Exato": "correct_score",
        "Gols Exatos": "exact_goals",  # Total de gols exatos (1, 2, 3, 4, 5+)
        "Handicap Asiático": "asian_handicap",
        "Handicap": "asian_handicap",  # Forma abreviada
        "Marcar A Qualquer Momento (Tempo Regulamentar)": "anytime_scorer",
        "Escanteio - Resultado Final": "corners_result",
        "Cartão - Resultado Final": "cards_result",
        "Escanteio - Handicap Asiático": "corners_handicap",
        "Dupla Hipótese": "double_chance",
        "2º Gol": "next_goal",
        "Empate Anula Aposta": "draw_no_bet",
        "Ímpar/Par": "odd_even",
        "Atlético De Madrid - Total": "team_total_home",
        "Union Saint-Gilloise - Total": "team_total_away",
        "Atlético De Madrid - Gols Exatos": "team_exact_goals_home",
        "Union Saint-Gilloise - Gols Exatos": "team_exact_goals_away",
    }

    market_containers = soup.select('div[data-testid^="outcomes-by-market"]')
    for container in market_containers:
        market_name_elem = container.select_one('[data-testid="market-name"]')
        if not market_name_elem:
            continue

        market_display_name = market_name_elem.get_text(strip=True)
        market_key = market_name_map.get(market_display_name)
        
        # Se não encontrou no mapa, tenta padrões genéricos
        if not market_key:
            if "Placar" in market_display_name and "Exato" in market_display_name:
                market_key = "correct_score"
            elif "Gols" in market_display_name and "Exatos" in market_display_name:
                market_key = "exact_goals"
            elif "Handicap" in market_display_name:
                market_key = "asian_handicap"
            elif "Total" in market_display_name:
                market_key = "total_goals"
            else:
                continue  # Ignora mercados não mapeados

        # Extrai todas as opções e odds deste mercado
        options = {}
        option_elements = container.select('div[data-testid^="odd-"]')
        
        for opt_elem in option_elements:
            # Verificar se está suspenso (não disponível)
            if opt_elem.get('data-testid', '').startswith('suspended-outcome-'):
                continue
            
            # Buscar texto da opção (nome do resultado)
            option_text_elem = opt_elem.find('span', class_=lambda x: x and 'text-bold' in x)
            if not option_text_elem:
                # Tentar buscar qualquer span com texto
                option_text_elem = opt_elem.find('span', class_=lambda x: x and 'text-text-light-primary' in str(x))
            if not option_text_elem:
                # Última tentativa: buscar qualquer span dentro de div com flex items-center
                option_text_elem = opt_elem.select_one('span.text-text-light-primary, span.text-text-light-secondary')
            
            if not option_text_elem:
                continue

            option_text = option_text_elem.get_text(strip=True)
            
            # Buscar valor da odd
            # Padrão: span com classe _col-accentOdd2 ou similar
            odd_elem = opt_elem.select_one('span._col-accentOdd2, span[class*="accentOdd"]')
            if not odd_elem:
                # Tentar buscar dentro de span com transform
                odd_elem = opt_elem.select_one('span[class*="transform-translateY"]')
            if not odd_elem:
                # Última tentativa: buscar qualquer número no elemento
                text = opt_elem.get_text()
                numbers = re.findall(r'\d+\.?\d*', text)
                if numbers:
                    try:
                        odd_value = float(numbers[-1])  # Pega o último número (geralmente é a odd)
                        options[option_text] = odd_value
                    except ValueError:
                        continue
                continue

            try:
                odd_text = odd_elem.get_text(strip=True)
                odd_value = float(odd_text)
                options[option_text] = odd_value
            except (ValueError, AttributeError):
                continue

        if options:
            data["markets"][market_key] = {
                "display_name": market_display_name,
                "options": options
            }

    return data

