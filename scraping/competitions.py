"""
Extração de campeonatos/competições disponíveis na BetNacional.
"""
import json
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from utils.logger import logger


def extract_competitions_from_html(html: str) -> List[Dict[str, Any]]:
    """
    Extrai lista de campeonatos/ligações da página HTML de futebol.
    
    Retorna lista de dicionários com:
    - id: ID do campeonato/liga
    - name: Nome do campeonato
    - url: URL do campeonato
    - sport_id: ID do esporte (1 = futebol)
    - country: País (se disponível)
    """
    competitions = []
    seen_ids = set()  # Para evitar duplicatas
    soup = BeautifulSoup(html, "html.parser")
    
    # Estratégia 1: Tentar extrair do JSON __NEXT_DATA__
    try:
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if script_tag and script_tag.string:
            data = json.loads(script_tag.string)
            
            # Navegar pela estrutura do Next.js
            # A estrutura pode estar em props.pageProps ou initialState
            page_props = data.get("props", {}).get("pageProps", {})
            
            # Tentar encontrar campeonatos em diferentes locais
            if "initialState" in page_props:
                state = page_props["initialState"]
                
                # Tentar em events.queries
                if "events" in state:
                    events_data = state["events"].get("queries", {})
                    # Procurar por dados de ligas/campeonatos
                    for key, value in events_data.items():
                        if isinstance(value, dict) and "data" in value:
                            data_val = value["data"]
                            if isinstance(data_val, dict) and "leagues" in data_val:
                                for league in data_val["leagues"]:
                                    if isinstance(league, dict):
                                        comp = {
                                            "id": league.get("id"),
                                            "name": league.get("name"),
                                            "url": f"/sports/1/{league.get('id', '')}",
                                            "sport_id": 1
                                        }
                                        if comp["id"] and comp["name"]:
                                            competitions.append(comp)
                
                # Tentar em cache
                if "cache" in state:
                    cache = state["cache"]
                    if "events" in cache and "entities" in cache["events"]:
                        entities = cache["events"]["entities"]
                        # Procurar por ligas nos eventos
                        for event_id, event_data in entities.items():
                            if isinstance(event_data, dict) and "league" in event_data:
                                league = event_data["league"]
                                if isinstance(league, dict):
                                    comp = {
                                        "id": league.get("id"),
                                        "name": league.get("name"),
                                        "url": f"/sports/1/{league.get('id', '')}",
                                        "sport_id": 1
                                    }
                                    if comp["id"] and comp["name"]:
                                        # Evitar duplicatas
                                        if not any(c["id"] == comp["id"] for c in competitions):
                                            competitions.append(comp)
            
            # Tentar buscar diretamente em estrutura de dados
            # Se houver uma lista de ligas/campeonatos
            def find_competitions_in_dict(obj, path=""):
                """Busca recursiva por estruturas que parecem campeonatos."""
                if isinstance(obj, dict):
                    # Verificar se este dict parece um campeonato
                    if "id" in obj and "name" in obj:
                        if any(keyword in str(obj.get("name", "")).lower() for keyword in 
                               ["liga", "league", "campeonato", "championship", "copa", "cup"]):
                            comp = {
                                "id": obj.get("id"),
                                "name": obj.get("name"),
                                "url": f"/sports/1/{obj.get('id', '')}",
                                "sport_id": 1
                            }
                            if comp["id"] and comp["name"]:
                                if not any(c["id"] == comp["id"] for c in competitions):
                                    competitions.append(comp)
                    
                    # Continuar busca recursiva
                    for key, value in obj.items():
                        if key in ["leagues", "competitions", "championships", "tournaments"]:
                            if isinstance(value, list):
                                for item in value:
                                    find_competitions_in_dict(item, f"{path}.{key}")
                        else:
                            find_competitions_in_dict(value, f"{path}.{key}")
                            
                elif isinstance(obj, list):
                    for item in obj:
                        find_competitions_in_dict(item, path)
            
            find_competitions_in_dict(data)
            
    except Exception as e:
        logger.debug(f"Erro ao extrair campeonatos do JSON: {e}")
    
    # Estratégia 2: Tentar extrair do HTML renderizado
    # Procurar por links que apontam para campeonatos
    try:
        # Links que podem ser de campeonatos
        links = soup.select('a[href*="/events/"], a[href*="/sports/"]')
        for link in links:
            href = link.get("href", "")
            text = link.get_text(strip=True)
            
            # Verificar se é um link de campeonato
            if "/events/" in href or ("/sports/" in href and text):
                # Tentar extrair ID do campeonato da URL
                import re
                match = re.search(r'/events/(\d+)/(\d+)/(\d+)', href)
                if match:
                    sport_id, is_live, event_id = match.groups()
                    # Este é um evento, não um campeonato
                    continue
                
                match = re.search(r'/sports/(\d+)(?:/(\d+))?', href)
                if match:
                    sport_id = match.group(1)
                    comp_id = match.group(2) if match.group(2) else None
                    
                    if text and len(text) > 2:  # Nome válido
                        comp = {
                            "id": comp_id or text.lower().replace(" ", "-"),
                            "name": text,
                            "url": href,
                            "sport_id": int(sport_id)
                        }
                        if not any(c["name"] == comp["name"] for c in competitions):
                            competitions.append(comp)
    except Exception as e:
        logger.debug(f"Erro ao extrair campeonatos do HTML: {e}")
    
    # Estratégia 3: Procurar por elementos com classes específicas
    try:
        # Procurar por elementos que podem conter nomes de campeonatos
        competition_elements = soup.select('[class*="league"], [class*="competition"], [class*="championship"], [data-testid*="league"]')
        for elem in competition_elements:
            text = elem.get_text(strip=True)
            if text and len(text) > 2:
                # Verificar se parece um nome de campeonato
                if any(keyword in text.lower() for keyword in 
                       ["liga", "campeonato", "copa", "champions", "premier", "serie"]):
                    comp = {
                        "id": text.lower().replace(" ", "-"),
                        "name": text,
                        "url": "",
                        "sport_id": 1
                    }
                    if not any(c["name"] == comp["name"] for c in competitions):
                        competitions.append(comp)
    except Exception as e:
        logger.debug(f"Erro ao extrair campeonatos de elementos HTML: {e}")
    
    return competitions


def extract_competition_from_event_html(html: str, url: str = "") -> Optional[str]:
    """
    Extrai o nome do campeonato de uma página de evento/jogo.
    
    Tenta encontrar o campeonato no HTML do jogo.
    """
    soup = BeautifulSoup(html, "html.parser")
    
    # Estratégia 1: Procurar no JSON __NEXT_DATA__
    try:
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if script_tag and script_tag.string:
            data = json.loads(script_tag.string)
            
            # Procurar por league/competition name
            page_props = data.get("props", {}).get("pageProps", {})
            
            def find_competition_name(obj):
                """Busca recursiva pelo nome do campeonato."""
                if isinstance(obj, dict):
                    # Verificar se tem campos de liga
                    for key in ["league", "competition", "championship", "tournament"]:
                        if key in obj:
                            league_obj = obj[key]
                            if isinstance(league_obj, dict) and "name" in league_obj:
                                return league_obj["name"]
                            elif isinstance(league_obj, str):
                                return league_obj
                    
                    # Continuar busca
                    for value in obj.values():
                        result = find_competition_name(value)
                        if result:
                            return result
                elif isinstance(obj, list):
                    for item in obj:
                        result = find_competition_name(item)
                        if result:
                            return result
                return None
            
            competition_name = find_competition_name(page_props)
            if competition_name:
                return competition_name
    except Exception as e:
        logger.debug(f"Erro ao extrair campeonato do JSON: {e}")
    
    # Estratégia 2: Procurar no HTML renderizado
    try:
        # Procurar por elementos que podem conter o nome do campeonato
        competition_selectors = [
            '[class*="league"]',
            '[class*="competition"]',
            '[class*="championship"]',
            '[data-testid*="league"]',
        ]
        
        for selector in competition_selectors:
            elements = soup.select(selector)
            for elem in elements:
                text = elem.get_text(strip=True)
                if text and len(text) > 2 and len(text) < 100:
                    # Verificar se parece um nome de campeonato (não é muito longo)
                    if any(keyword in text.lower() for keyword in 
                           ["liga", "campeonato", "copa", "champions", "premier", "serie"]):
                        return text
    except Exception as e:
        logger.debug(f"Erro ao extrair campeonato do HTML: {e}")
    
    return None

