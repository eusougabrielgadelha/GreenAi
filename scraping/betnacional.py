"""Parsing específico da BetNacional."""
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from types import SimpleNamespace as NS
import pytz

from config.settings import ZONE
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
        except Exception:
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

    logger.info(f"🧮 → eventos extraídos via HTML: {len(evs)} | URL: {url}")
    
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
    """
    soup = BeautifulSoup(html, "html.parser")

    # Estratégia 1: Procurar por um badge ou texto que diga "Vencedor" ou similar.
    winner_indicators = [
        soup.find(string=lambda text: text and "Vencedor" in text),
        soup.find(string=lambda text: text and "Winner" in text),
    ]

    for indicator in winner_indicators:
        if indicator:
            parent_text = indicator.parent.get_text(strip=True) if indicator.parent else ""
            if "Casa" in parent_text or "Home" in parent_text:
                return "home"
            elif "Fora" in parent_text or "Away" in parent_text:
                return "away"
            elif "Empate" in parent_text or "Draw" in parent_text:
                return "draw"

    # Estratégia 2: Procurar por classes CSS comuns em elementos de vencedor.
    winner_elements = soup.select('.winner, .vencedor, .champion, [class*="winner"], [class*="vencedor"]')
    for elem in winner_elements:
        elem_text = elem.get_text(strip=True).lower()
        if "casa" in elem_text or "home" in elem_text:
            return "home"
        elif "fora" in elem_text or "away" in elem_text:
            return "away"
        elif "empate" in elem_text or "draw" in elem_text:
            return "draw"

    # Estratégia 3: Se nada for encontrado, retorna None.
    logger.warning(f"Não foi possível determinar o vencedor para o jogo com ext_id: {ext_id}")
    return None


def scrape_live_game_data(html: str, ext_id: str) -> Dict[str, Any]:
    """
    Extrai TUDO de uma página de jogo ao vivo: estatísticas e odds dos principais mercados.
    """
    soup = BeautifulSoup(html, "html.parser")
    data = {
        "stats": {},
        "markets": {}
    }

    # --- 1. Extrair Estatísticas (Placar, Tempo, etc) ---
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
            time_element = lmt_container.select_one(".sr-lmt-clock-v2__time")
            if time_element:
                data["stats"]["match_time"] = time_element.get_text(strip=True)

            # Último Evento (Gol, Cartão, etc)
            last_event_element = lmt_container.select_one(".sr-lmt-1-evt__text-content")
            if last_event_element:
                data["stats"]["last_event"] = last_event_element.get_text(" ", strip=True)

        except Exception as e:
            logger.error(f"Erro ao extrair estatísticas do jogo ao vivo {ext_id}: {e}")

    # --- 2. Extrair Mercados de Apostas ---
    market_name_map = {
        "Resultado Final": "match_result",
        "Ambos os Times Marcam": "btts",
        "Total de Gols": "total_goals",
        "Placar Exato": "correct_score",
        "Marcar A Qualquer Momento (Tempo Regulamentar)": "anytime_scorer",
        "Escanteio - Resultado Final": "corners_result",
        "Cartão - Resultado Final": "cards_result",
    }

    market_containers = soup.select('div[data-testid^="outcomes-by-market"]')
    for container in market_containers:
        market_name_elem = container.select_one('[data-testid="market-name"]')
        if not market_name_elem:
            continue

        market_display_name = market_name_elem.get_text(strip=True)
        market_key = market_name_map.get(market_display_name)
        if not market_key:
            continue

        # Extrai todas as opções e odds deste mercado
        options = {}
        option_elements = container.select('div[data-testid^="odd-"]')
        for opt_elem in option_elements:
            option_text_elem = opt_elem.select_one('span:not([class*="font-bold"])')
            if not option_text_elem:
                continue

            option_text = option_text_elem.get_text(strip=True)

            odd_elem = opt_elem.select_one('span._col-accentOdd2')
            if not odd_elem:
                continue

            try:
                odd_value = float(odd_elem.get_text(strip=True))
                options[option_text] = odd_value
            except ValueError:
                continue

        if options:
            data["markets"][market_key] = {
                "display_name": market_display_name,
                "options": options
            }

    return data

