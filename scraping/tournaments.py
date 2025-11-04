"""Mapeamento e busca de campeonatos/torneios da BetNacional via API XHR."""
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import requests

from config.settings import USER_AGENT
from utils.logger import logger

# Cache de campeonatos com TTL de 24 horas
_tournaments_cache: Optional[Tuple[List[Dict[str, Any]], datetime]] = None
_cache_ttl_hours = 24


def fetch_tournaments_from_api(sport_id: int = 1) -> Optional[Dict[str, Any]]:
    """
    Busca lista de todos os campeonatos/torneios de um esporte via HTML scraping.
    
    A API XHR não expõe diretamente o endpoint de campeonatos, então buscamos
    da página /sports/{sport_id} e extraímos do JSON embutido no HTML.
    
    Args:
        sport_id: ID do esporte (1 = futebol)
    
    Returns:
        Dict com a resposta JSON (estrutura com 'importants' e 'tourneys') ou None
    """
    try:
        from scraping.fetchers import _fetch_requests_async
        import asyncio
        
        url = f"https://betnacional.bet.br/sports/{sport_id}"
        html = asyncio.run(_fetch_requests_async(url))
        
        if html:
            json_data = extract_tournaments_from_html(html)
            return json_data
    except Exception as e:
        logger.warning(f"Erro ao buscar campeonatos via HTML: {e}")
    
    return None


def parse_tournaments_from_api(json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parseia a resposta JSON da API e extrai todos os campeonatos.
    
    A API retorna um JSON com estrutura:
    {
        "importants": [...],  # Campeonatos importantes
        "tourneys": [...]     # Todos os campeonatos
    }
    
    Args:
        json_data: Resposta JSON da API
    
    Returns:
        Lista de dicionários com informações dos campeonatos
        Cada campeonato pode ter múltiplas categorias (lista em 'categories')
    """
    tournaments = []
    seen_ids = set()
    
    # ID especial para categoria "Campeonatos Importantes"
    IMPORTANT_CATEGORY_ID = 9999
    IMPORTANT_CATEGORY_NAME = "Campeonatos Importantes"
    
    try:
        # Processar campeonatos importantes
        importants = json_data.get('importants', [])
        for item in importants:
            if not isinstance(item, dict):
                continue
                
            tournament_id = item.get('tournament_id')
            if tournament_id and tournament_id not in seen_ids:
                category_id = item.get('category_id', 0)
                category_name = item.get('category_name', '')
                
                # Criar lista de categorias (país + importante)
                categories = []
                if category_name:
                    categories.append({
                        'category_id': category_id,
                        'category_name': category_name,
                        'is_primary': True
                    })
                # Sempre adicionar categoria "Campeonatos Importantes"
                categories.append({
                    'category_id': IMPORTANT_CATEGORY_ID,
                    'category_name': IMPORTANT_CATEGORY_NAME,
                    'is_primary': False
                })
                
                tournament = {
                    'sport_id': item.get('sport_id', 1),
                    'category_id': category_id,  # Categoria primária (país)
                    'tournament_id': tournament_id,
                    'tournament_name': item.get('tournament_name', ''),
                    'category_name': category_name,  # Categoria primária (para compatibilidade)
                    'categories': categories,  # Lista de todas as categorias
                    'image_name': item.get('image_name'),
                    'season_id': item.get('season_id', 0),
                    'is_important': True,
                    'url': f"https://betnacional.bet.br/events/{item.get('sport_id', 1)}/{category_id}/{tournament_id}"
                }
                tournaments.append(tournament)
                seen_ids.add(tournament_id)
        
        # Processar todos os campeonatos (tourneys)
        tourneys = json_data.get('tourneys', [])
        for item in tourneys:
            if not isinstance(item, dict):
                continue
                
            tournament_id = item.get('tournament_id')
            if tournament_id and tournament_id not in seen_ids:
                category_id = item.get('category_id', 0)
                category_name = item.get('category_name', '')
                
                # Criar lista de categorias (apenas país)
                categories = []
                if category_name:
                    categories.append({
                        'category_id': category_id,
                        'category_name': category_name,
                        'is_primary': True
                    })
                
                tournament = {
                    'sport_id': item.get('sport_id', 1),
                    'category_id': category_id,
                    'tournament_id': tournament_id,
                    'tournament_name': item.get('tournament_name', ''),
                    'category_name': category_name,
                    'categories': categories,  # Lista de todas as categorias
                    'category_image_name': item.get('category_image_name'),
                    'continent_name': item.get('continent_name'),
                    'season_id': item.get('season_id', 0),
                    'is_important': False,
                    'url': f"https://betnacional.bet.br/events/{item.get('sport_id', 1)}/{category_id}/{tournament_id}"
                }
                tournaments.append(tournament)
                seen_ids.add(tournament_id)
            elif tournament_id in seen_ids:
                # Se já existe (está em importants), adicionar categoria "Campeonatos Importantes" se ainda não tiver
                for tournament in tournaments:
                    if tournament.get('tournament_id') == tournament_id:
                        # Verificar se já tem a categoria importante
                        has_important = any(
                            cat.get('category_id') == IMPORTANT_CATEGORY_ID 
                            for cat in tournament.get('categories', [])
                        )
                        if not has_important:
                            tournament['categories'].append({
                                'category_id': IMPORTANT_CATEGORY_ID,
                                'category_name': IMPORTANT_CATEGORY_NAME,
                                'is_primary': False
                            })
                            tournament['is_important'] = True
        
        # Ordenar por nome do campeonato
        tournaments.sort(key=lambda x: x.get('tournament_name', '').lower())
        
    except Exception as e:
        logger.warning(f"Erro ao parsear campeonatos da API: {e}")
    
    return tournaments


def extract_tournaments_from_html(html: str) -> Optional[Dict[str, Any]]:
    """
    Extrai dados de campeonatos do HTML da página /sports/1.
    
    Busca pelo script __NEXT_DATA__ que contém os dados JSON.
    Os dados podem estar em uma chamada XHR que retorna JSON com estrutura:
    {
        "importants": [...],  # Campeonatos importantes
        "tourneys": [...]      # Todos os campeonatos
    }
    
    Args:
        html: HTML da página
    
    Returns:
        Dict com os dados JSON (estrutura com 'importants' e 'tourneys') ou None
    """
    try:
        # Estratégia 1: Buscar pelo script __NEXT_DATA__
        pattern = r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>'
        match = re.search(pattern, html, re.DOTALL)
        
        if match:
            json_str = match.group(1)
            data = json.loads(json_str)
            
            # Tentar encontrar os dados de campeonatos
            # Os dados podem estar em diferentes locais
            if 'props' in data and 'pageProps' in data['props']:
                page_props = data['props']['pageProps']
                
                # Buscar recursivamente por estruturas que parecem campeonatos
                def find_tournaments(obj, path=""):
                    """Busca recursiva por dados de campeonatos."""
                    if isinstance(obj, dict):
                        # Verificar se tem a estrutura esperada (importants + tourneys)
                        if 'importants' in obj and 'tourneys' in obj:
                            return obj
                        
                        # Verificar se tem apenas uma das chaves (pode estar em objeto maior)
                        if 'importants' in obj or 'tourneys' in obj:
                            # Construir objeto com ambas as chaves se possível
                            result = {}
                            if 'importants' in obj:
                                result['importants'] = obj['importants']
                            if 'tourneys' in obj:
                                result['tourneys'] = obj['tourneys']
                            if result:
                                return result
                        
                        # Buscar em sub-objetos
                        for key, value in obj.items():
                            if key in ['importants', 'tourneys', 'tournaments', 'leagues', 'data']:
                                result = find_tournaments(value, f"{path}.{key}")
                                if result:
                                    return result
                            else:
                                result = find_tournaments(value, f"{path}.{key}")
                                if result:
                                    return result
                    elif isinstance(obj, list):
                        for item in obj:
                            result = find_tournaments(item, path)
                            if result:
                                return result
                    return None
                
                result = find_tournaments(page_props)
                if result:
                    return result
        
        # Estratégia 2: Buscar por variáveis JavaScript globais
        patterns = [
            r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
            r'window\.__TOURNAMENTS__\s*=\s*({.*?});',
            r'var\s+tournaments\s*=\s*({.*?});',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    json_str = match.group(1)
                    data = json.loads(json_str)
                    if 'importants' in data or 'tourneys' in data:
                        return data
                except:
                    continue
        
        # Estratégia 3: Buscar por JSON inline no HTML
        # Às vezes os dados estão em um script tag com JSON
        pattern = r'<script[^>]*>.*?({[\s\S]*?"importants"[\s\S]*?"tourneys"[\s\S]*?})'
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                json_str = match.group(1)
                data = json.loads(json_str)
                if 'importants' in data or 'tourneys' in data:
                    return data
            except:
                pass
            
    except Exception as e:
        logger.debug(f"Erro ao extrair dados de campeonatos do HTML: {e}")
    
    return None


def load_tournaments_from_json_file(filepath: str) -> Optional[Dict[str, Any]]:
    """
    Carrega dados de campeonatos de um arquivo JSON.
    
    Útil para processar dados XHR salvos manualmente.
    
    Args:
        filepath: Caminho do arquivo JSON
    
    Returns:
        Dict com os dados JSON ou None
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Verificar se tem estrutura esperada
            if isinstance(data, dict) and ('importants' in data or 'tourneys' in data):
                return data
            # Se não tem, pode estar em um objeto maior
            if isinstance(data, dict):
                # Buscar recursivamente
                def find_tournaments(obj):
                    if isinstance(obj, dict):
                        if 'importants' in obj and 'tourneys' in obj:
                            return obj
                        for value in obj.values():
                            result = find_tournaments(value)
                            if result:
                                return result
                    elif isinstance(obj, list):
                        for item in obj:
                            result = find_tournaments(item)
                            if result:
                                return result
                    return None
                
                result = find_tournaments(data)
                if result:
                    return result
                return data
    except Exception as e:
        logger.warning(f"Erro ao carregar arquivo JSON: {e}")
    
    return None


def get_all_football_tournaments(json_file: Optional[str] = None, use_cache: bool = True) -> List[Dict[str, Any]]:
    """
    Busca todos os campeonatos de futebol disponíveis.
    
    Tenta primeiro via arquivo JSON (se fornecido ou padrão), depois via HTML scraping.
    Usa cache com TTL de 24 horas para evitar requisições desnecessárias.
    
    Args:
        json_file: (opcional) Caminho para arquivo JSON com dados XHR
        use_cache: Se True, usa cache se disponível e válido (padrão: True)
    
    Returns:
        Lista de dicionários com informações dos campeonatos
    """
    global _tournaments_cache
    
    # Verifica cache se habilitado
    if use_cache and _tournaments_cache is not None:
        cached_tournaments, cache_time = _tournaments_cache
        cache_age = datetime.now() - cache_time
        
        if cache_age < timedelta(hours=_cache_ttl_hours):
            logger.debug(f"Usando cache de campeonatos (idade: {cache_age.total_seconds()/3600:.1f}h)")
            return cached_tournaments
        else:
            logger.debug(f"Cache expirado, buscando campeonatos novamente")
            _tournaments_cache = None
    
    tournaments = []
    
    # Tentar carregar de arquivo JSON primeiro
    # Se não fornecido, tentar arquivo padrão
    if json_file is None:
        import os
        default_json = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tournaments_mapping.json")
        if os.path.exists(default_json):
            json_file = default_json
    
    if json_file:
        logger.info(f"📁 Carregando campeonatos de arquivo: {json_file}")
        try:
            import json
            with open(json_file, 'r', encoding='utf-8') as f:
                tournaments = json.load(f)
            if tournaments:
                logger.info(f"✅ Encontrados {len(tournaments)} campeonato(s) do arquivo")
                # Salva no cache
                if use_cache:
                    _tournaments_cache = (tournaments, datetime.now())
                    logger.debug(f"Cache de campeonatos atualizado: {len(tournaments)} campeonatos")
                return tournaments
        except Exception as e:
            logger.warning(f"⚠️ Erro ao carregar arquivo JSON: {e}. Tentando parsear como formato XHR...")
            # Tentar como formato XHR antigo
            json_data = load_tournaments_from_json_file(json_file)
            if json_data:
                tournaments = parse_tournaments_from_api(json_data)
                logger.info(f"✅ Encontrados {len(tournaments)} campeonato(s) do arquivo (formato XHR)")
                # Salva no cache
                if use_cache:
                    _tournaments_cache = (tournaments, datetime.now())
                    logger.debug(f"Cache de campeonatos atualizado: {len(tournaments)} campeonatos")
                return tournaments
    
    # Tentar via HTML scraping
    logger.info("🌐 Buscando campeonatos via HTML scraping...")
    json_data = fetch_tournaments_from_api(sport_id=1)
    
    if json_data:
        tournaments = parse_tournaments_from_api(json_data)
        logger.info(f"✅ Encontrados {len(tournaments)} campeonato(s) via HTML")
    
    if not tournaments:
        logger.warning("⚠️ Nenhum campeonato encontrado")
        return []
    
    # Salva no cache
    if use_cache:
        _tournaments_cache = (tournaments, datetime.now())
        logger.debug(f"Cache de campeonatos atualizado: {len(tournaments)} campeonatos")
    
    return tournaments


def clear_tournaments_cache():
    """
    Limpa o cache de campeonatos.
    Útil quando se sabe que os dados mudaram e precisam ser recarregados.
    """
    global _tournaments_cache
    _tournaments_cache = None
    logger.debug("Cache de campeonatos limpo")


def get_tournament_by_id(tournament_id: int, tournaments: List[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Busca um campeonato pelo ID.
    
    Args:
        tournament_id: ID do campeonato
        tournaments: Lista de campeonatos (se None, busca todos)
    
    Returns:
        Dict com informações do campeonato ou None
    """
    if tournaments is None:
        tournaments = get_all_football_tournaments()
    
    for tournament in tournaments:
        if tournament.get('tournament_id') == tournament_id:
            return tournament
    
    return None


def get_tournaments_by_category(category_id: int, tournaments: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Busca todos os campeonatos de uma categoria.
    
    Agora suporta múltiplas categorias por campeonato.
    Busca na lista 'categories' de cada campeonato.
    
    Args:
        category_id: ID da categoria (ex: 13 = Brasil, 9999 = Campeonatos Importantes)
        tournaments: Lista de campeonatos (se None, busca todos)
    
    Returns:
        Lista de campeonatos da categoria
    """
    if tournaments is None:
        tournaments = get_all_football_tournaments()
    
    result = []
    for t in tournaments:
        # Verificar categoria primária (compatibilidade)
        if t.get('category_id') == category_id:
            result.append(t)
        else:
            # Verificar na lista de categorias
            categories = t.get('categories', [])
            if any(cat.get('category_id') == category_id for cat in categories):
                result.append(t)
    
    return result


def get_tournaments_by_category_name(category_name: str, tournaments: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Busca todos os campeonatos de uma categoria por nome.
    
    Args:
        category_name: Nome da categoria (ex: "Brasil", "Campeonatos Importantes")
        tournaments: Lista de campeonatos (se None, busca todos)
    
    Returns:
        Lista de campeonatos da categoria
    """
    if tournaments is None:
        tournaments = get_all_football_tournaments()
    
    result = []
    for t in tournaments:
        # Verificar categoria primária (compatibilidade)
        if t.get('category_name') == category_name:
            result.append(t)
        else:
            # Verificar na lista de categorias
            categories = t.get('categories', [])
            if any(cat.get('category_name') == category_name for cat in categories):
                result.append(t)
    
    return result


def get_important_tournaments(tournaments: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Busca apenas campeonatos importantes.
    
    Args:
        tournaments: Lista de campeonatos (se None, busca todos)
    
    Returns:
        Lista de campeonatos importantes
    """
    if tournaments is None:
        tournaments = get_all_football_tournaments()
    
    return [t for t in tournaments if t.get('is_important', False)]


def export_tournaments_to_json(tournaments: List[Dict[str, Any]], filepath: str = "tournaments_mapping.json"):
    """
    Exporta lista de campeonatos para arquivo JSON.
    
    Args:
        tournaments: Lista de campeonatos
        filepath: Caminho do arquivo JSON
    """
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(tournaments, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Campeonatos exportados para {filepath}")
    except Exception as e:
        logger.error(f"Erro ao exportar campeonatos: {e}")

