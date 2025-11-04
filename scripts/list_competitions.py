"""
Script para listar todos os campeonatos de futebol disponíveis na BetNacional.
"""
import asyncio
import sys
import os

# Adiciona o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraping.fetchers import _fetch_requests_async, _fetch_with_playwright
from scraping.competitions import extract_competitions_from_html
from utils.logger import logger


async def list_all_competitions():
    """
    Lista todos os campeonatos de futebol disponíveis na BetNacional.
    
    Tenta múltiplas estratégias:
    1. Extrair da página /sports/1 (lista de campeonatos)
    2. Extrair dos campeonatos configurados em config/settings.py
    3. Buscar em páginas de eventos para encontrar campeonatos adicionais
    """
    competitions = []
    
    # Estratégia 1: Buscar da página de campeonatos
    url = "https://betnacional.bet.br/sports/1"
    logger.info(f"📋 Buscando campeonatos de futebol em: {url}")
    
    try:
        # Usa Playwright para aguardar carregamento completo
        logger.info("⏳ Aguardando carregamento completo da página...")
        html = await _fetch_with_playwright(url, wait_time=8000)  # Aguarda 8 segundos para JS carregar
        
        if not html:
            logger.error("Nao foi possivel obter o HTML com Playwright")
            return []
        
        logger.info(f"✅ HTML obtido ({len(html)} caracteres)")
        
        # Extrai campeonatos do HTML
        competitions = extract_competitions_from_html(html)
        logger.info(f"📊 Encontrados {len(competitions)} campeonato(s) no HTML")
        
    except Exception as e:
        logger.warning(f"⚠️ Erro ao buscar página de campeonatos: {e}")
    
    # Estratégia 2: Adicionar campeonatos conhecidos do config
    logger.info("📚 Adicionando campeonatos configurados em config/settings.py...")
    try:
        from config.settings import BETTING_LINKS
        import re
        
        for comp_name, comp_info in BETTING_LINKS.items():
            if isinstance(comp_info, dict) and "link" in comp_info:
                # Extrair ID do campeonato da URL
                match = re.search(r'/events/(\d+)/(\d+)/(\d+)', comp_info["link"])
                if match:
                    sport_id, is_live, event_id = match.groups()
                    comp = {
                        "id": event_id,
                        "name": comp_info.get("campeonato", comp_name),
                        "url": comp_info["link"],
                        "sport_id": int(sport_id),
                        "country": comp_info.get("pais", "")
                    }
                    # Evitar duplicatas
                    if not any(c.get("id") == comp["id"] for c in competitions):
                        competitions.append(comp)
                    else:
                        # Atualizar se já existe
                        for c in competitions:
                            if c.get("id") == comp["id"]:
                                c.update(comp)
                                break
    except Exception as e:
        logger.warning(f"⚠️ Erro ao adicionar campeonatos do config: {e}")
        
    # Ordenar por nome
    competitions.sort(key=lambda x: x.get("name", "").lower())
    
    # Remover duplicatas por ID
    unique_competitions = []
    seen_ids = set()
    for comp in competitions:
        comp_id = comp.get("id")
        if comp_id and comp_id not in seen_ids:
            seen_ids.add(comp_id)
            unique_competitions.append(comp)
        elif not comp_id:
            # Se não tem ID, verificar por nome
            name = comp.get("name", "")
            if name and name not in [c.get("name", "") for c in unique_competitions]:
                unique_competitions.append(comp)
    
    competitions = unique_competitions
    
    # Exibir resultados
    if competitions:
        logger.info(f"\n{'='*60}")
        logger.info(f"📋 TOTAL: {len(competitions)} campeonato(s) encontrado(s)")
        logger.info(f"{'='*60}\n")
        
        for i, comp in enumerate(competitions, 1):
            country = comp.get("country", "")
            country_str = f" ({country})" if country else ""
            print(f"{i:3d}. {comp['name']}{country_str}")
            print(f"      ID: {comp.get('id', 'N/A')}")
            if comp.get('url'):
                print(f"      URL: {comp['url']}")
            print(f"      Esporte ID: {comp.get('sport_id', 'N/A')}")
            print()
    else:
        logger.warning("⚠️ Nenhum campeonato encontrado.")
        logger.info("\n💡 Dica: O site pode ter mudado a estrutura. Verifique manualmente.")
    
    return competitions


if __name__ == "__main__":
    print("🔍 Iniciando busca de campeonatos na BetNacional...\n")
    competitions = asyncio.run(list_all_competitions())
    
    if competitions:
        print(f"\n{'='*60}")
        print(f"✅ Processo concluído: {len(competitions)} campeonato(s) encontrado(s)")
        print(f"{'='*60}")
    else:
        print("\n⚠️ Nenhum campeonato encontrado. Verifique os logs para mais detalhes.")

