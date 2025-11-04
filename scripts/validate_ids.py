"""
Script para validar se os IDs de campeonatos e categorias correspondem
aos IDs reais da API da BetNacional.
"""
import json
import sys
import os
import requests
from typing import Dict, List, Any, Optional

# Adicionar diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import logger
from scraping.betnacional import fetch_events_from_api


def load_local_tournaments() -> List[Dict[str, Any]]:
    """Carrega campeonatos do arquivo JSON local."""
    json_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tournaments_mapping.json")
    
    if not os.path.exists(json_file):
        logger.error(f"Arquivo não encontrado: {json_file}")
        return []
    
    with open(json_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def fetch_tournaments_from_api_real() -> Optional[Dict[str, Any]]:
    """
    Busca campeonatos diretamente da API da BetNacional.
    Tenta buscar via HTML scraping da página /sports/1.
    """
    try:
        from scraping.tournaments import fetch_tournaments_from_api
        return fetch_tournaments_from_api(sport_id=1)
    except Exception as e:
        logger.error(f"Erro ao buscar da API: {e}")
        return None


def validate_tournament_ids(local_tournaments: List[Dict[str, Any]], 
                           api_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Valida se os IDs dos campeonatos locais correspondem aos da API.
    
    Returns:
        Dict com resultados da validação
    """
    results = {
        'total_local': len(local_tournaments),
        'validated': 0,
        'errors': [],
        'warnings': [],
        'missing_in_api': []
    }
    
    if not api_data:
        results['errors'].append("Não foi possível buscar dados da API")
        return results
    
    # Extrair IDs da API
    api_tournaments = {}
    
    # Processar campeonatos importantes
    for item in api_data.get('importants', []):
        tournament_id = item.get('tournament_id')
        if tournament_id:
            api_tournaments[tournament_id] = {
                'category_id': item.get('category_id', 0),
                'tournament_name': item.get('tournament_name', ''),
                'category_name': item.get('category_name', ''),
                'source': 'importants'
            }
    
    # Processar todos os campeonatos
    for item in api_data.get('tourneys', []):
        tournament_id = item.get('tournament_id')
        if tournament_id:
            if tournament_id not in api_tournaments:
                api_tournaments[tournament_id] = {
                    'category_id': item.get('category_id', 0),
                    'tournament_name': item.get('tournament_name', ''),
                    'category_name': item.get('category_name', ''),
                    'source': 'tourneys'
                }
    
    logger.info(f"Encontrados {len(api_tournaments)} campeonatos únicos na API")
    
    # Validar cada campeonato local
    for local_t in local_tournaments:
        tournament_id = local_t.get('tournament_id')
        local_category_id = local_t.get('category_id')
        local_name = local_t.get('tournament_name')
        
        if not tournament_id:
            results['errors'].append(f"Campeonato sem tournament_id: {local_name}")
            continue
        
        if tournament_id in api_tournaments:
            api_t = api_tournaments[tournament_id]
            api_category_id = api_t.get('category_id', 0)
            
            # Validar category_id
            if local_category_id != api_category_id:
                results['warnings'].append(
                    f"tournament_id={tournament_id} ({local_name}): "
                    f"category_id local={local_category_id} != API={api_category_id}"
                )
            
            # Validar nome (pode ter pequenas diferenças)
            api_name = api_t.get('tournament_name', '')
            if local_name.lower() != api_name.lower():
                results['warnings'].append(
                    f"tournament_id={tournament_id}: "
                    f"Nome diferente - Local='{local_name}' vs API='{api_name}'"
                )
            
            results['validated'] += 1
        else:
            # Verificar se é a categoria especial "Campeonatos Importantes"
            if tournament_id == 9999:
                # ID especial criado por nós, não precisa validar
                continue
            
            results['missing_in_api'].append({
                'tournament_id': tournament_id,
                'tournament_name': local_name,
                'category_id': local_category_id
            })
    
    return results


def validate_urls(local_tournaments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Valida se as URLs dos campeonatos locais estão corretas.
    """
    results = {
        'total': 0,
        'valid': 0,
        'invalid': []
    }
    
    for tournament in local_tournaments:
        results['total'] += 1
        
        url = tournament.get('url', '')
        tournament_id = tournament.get('tournament_id')
        category_id = tournament.get('category_id', 0)
        sport_id = tournament.get('sport_id', 1)
        
        # Construir URL esperada
        expected_url = f"https://betnacional.bet.br/events/{sport_id}/{category_id}/{tournament_id}"
        
        if url != expected_url:
            results['invalid'].append({
                'tournament_id': tournament_id,
                'tournament_name': tournament.get('tournament_name', ''),
                'expected': expected_url,
                'actual': url
            })
        else:
            results['valid'] += 1
    
    return results


def print_validation_report(id_results: Dict[str, Any], url_results: Dict[str, Any]):
    """Imprime relatório de validação."""
    print("\n" + "=" * 80)
    print("RELATORIO DE VALIDACAO DE IDs")
    print("=" * 80)
    
    print(f"\nESTATISTICAS:")
    print(f"  - Total de campeonatos locais: {id_results['total_local']}")
    print(f"  - Validados com sucesso: {id_results['validated']}")
    print(f"  - Avisos: {len(id_results['warnings'])}")
    print(f"  - Erros: {len(id_results['errors'])}")
    print(f"  - Nao encontrados na API: {len(id_results['missing_in_api'])}")
    
    print(f"\nVALIDACAO DE URLs:")
    print(f"  - Total de URLs: {url_results['total']}")
    print(f"  - URLs validas: {url_results['valid']}")
    print(f"  - URLs invalidas: {len(url_results['invalid'])}")
    
    if id_results['warnings']:
        print(f"\nAVISOS ({len(id_results['warnings'])}):")
        for warning in id_results['warnings'][:10]:  # Mostrar apenas os 10 primeiros
            print(f"  - {warning}")
        if len(id_results['warnings']) > 10:
            print(f"  ... e mais {len(id_results['warnings']) - 10} aviso(s)")
    
    if id_results['errors']:
        print(f"\nERROS ({len(id_results['errors'])}):")
        for error in id_results['errors']:
            print(f"  - {error}")
    
    if id_results['missing_in_api']:
        print(f"\nCAMPEONATOS NAO ENCONTRADOS NA API ({len(id_results['missing_in_api'])}):")
        for missing in id_results['missing_in_api'][:10]:
            print(f"  - tournament_id={missing['tournament_id']}: {missing['tournament_name']} (category_id={missing['category_id']})")
        if len(id_results['missing_in_api']) > 10:
            print(f"  ... e mais {len(id_results['missing_in_api']) - 10} campeonato(s)")
    
    if url_results['invalid']:
        print(f"\nURLs INVALIDAS ({len(url_results['invalid'])}):")
        for invalid in url_results['invalid'][:5]:
            print(f"  - {invalid['tournament_name']} (ID: {invalid['tournament_id']})")
            print(f"    Esperado: {invalid['expected']}")
            print(f"    Atual:    {invalid['actual']}")
    
    print("\n" + "=" * 80)
    
    # Resumo final
    all_ok = (
        len(id_results['errors']) == 0 and
        len(url_results['invalid']) == 0 and
        len(id_results['missing_in_api']) == 0
    )
    
    if all_ok:
        print("VALIDACAO CONCLUIDA: Todos os IDs estao corretos!")
    else:
        print("VALIDACAO CONCLUIDA: Alguns problemas foram encontrados (ver acima)")


def main():
    """Função principal."""
    logger.info("Iniciando validação de IDs...")
    
    # Carregar campeonatos locais
    local_tournaments = load_local_tournaments()
    if not local_tournaments:
        logger.error("Não foi possível carregar campeonatos locais")
        return
    
    logger.info(f"Carregados {len(local_tournaments)} campeonatos locais")
    
    # Buscar dados da API
    logger.info("Buscando dados da API da BetNacional...")
    api_data = fetch_tournaments_from_api_real()
    
    # Validar IDs
    logger.info("Validando IDs...")
    id_results = validate_tournament_ids(local_tournaments, api_data)
    
    # Validar URLs
    logger.info("Validando URLs...")
    url_results = validate_urls(local_tournaments)
    
    # Imprimir relatório
    print_validation_report(id_results, url_results)


if __name__ == "__main__":
    main()

