#!/usr/bin/env python3
"""
Script para analisar resposta da API copiada do DevTools.
Converte formato expandido do DevTools para JSON válido e analisa estrutura.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Any

def parse_devtools_format(content: str) -> Dict[str, Any]:
    """
    Converte formato expandido do DevTools para JSON válido.
    
    Formato DevTools:
    field_name
    :
    value
    
    Cada campo ocupa 3 linhas: nome, :, valor
    """
    items = []
    current_item = None
    current_key = None
    expecting_value = False
    
    lines = content.split('\n')
    i = 0
    
    # Procurar início do array odds
    while i < len(lines):
        line = lines[i].strip()
        
        # Procurar por padrão que indica início de item do array
        # Formato: número\n: \n{...}
        if line.isdigit() and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if next_line == ':' and i + 2 < len(lines):
                next_next = lines[i + 2].strip()
                if next_next.startswith('{'):
                    # Novo item do array
                    if current_item:
                        items.append(current_item)
                    current_item = {}
                    i += 3  # Pular número, :, {
                    continue
        
        # Se estamos em um item
        if current_item is not None:
            # Formato: key\n:\nvalue
            if not line or line in ['{', '}', '[', ']', ',', '…']:
                i += 1
                continue
            
            # Se a linha anterior era apenas ':', então esta é o valor
            if expecting_value:
                value = line
                
                # Converter valor
                if value == 'null':
                    current_item[current_key] = None
                elif value.startswith('"') and value.endswith('"'):
                    current_item[current_key] = value[1:-1]
                elif value.isdigit() or (value.startswith('-') and value[1:].isdigit()):
                    current_item[current_key] = int(value)
                elif re.match(r'^-?\d+\.\d+$', value):
                    current_item[current_key] = float(value)
                elif value == 'true':
                    current_item[current_key] = True
                elif value == 'false':
                    current_item[current_key] = False
                else:
                    current_item[current_key] = value
                
                current_key = None
                expecting_value = False
            
            # Se a próxima linha é ':', então esta é a chave
            elif i + 1 < len(lines) and lines[i + 1].strip() == ':':
                current_key = line.strip().strip('"')
                expecting_value = True
                i += 2  # Pular esta linha e a linha ':'
                continue
        
        i += 1
    
    # Adicionar último item
    if current_item:
        items.append(current_item)
    
    return {'odds': items}


def analyze_odds_structure(odds_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analisa a estrutura dos odds para identificar padrões e campos únicos.
    """
    analysis = {
        'total_items': len(odds_list),
        'unique_event_ids': set(),
        'unique_market_ids': set(),
        'unique_outcome_ids': set(),
        'unique_category_ids': set(),
        'unique_tournament_ids': set(),
        'fields': set(),
        'is_live_count': 0,
        'special_market_count': 0,
        'market_status_ids': set(),
        'event_status_ids': set(),
    }
    
    for item in odds_list:
        # Coletar IDs únicos
        if 'event_id' in item:
            analysis['unique_event_ids'].add(item['event_id'])
        if 'market_id' in item:
            analysis['unique_market_ids'].add(item['market_id'])
        if 'outcome_id' in item:
            analysis['unique_outcome_ids'].add(item['outcome_id'])
        if 'category_id' in item:
            analysis['unique_category_ids'].add(item['category_id'])
        if 'tournament_id' in item:
            analysis['unique_tournament_ids'].add(item['tournament_id'])
        
        # Coletar campos
        analysis['fields'].update(item.keys())
        
        # Contar flags
        if item.get('is_live') == 1:
            analysis['is_live_count'] += 1
        if item.get('special_market') == 1:
            analysis['special_market_count'] += 1
        
        # Coletar status IDs
        if 'market_status_id' in item:
            analysis['market_status_ids'].add(item['market_status_id'])
        if 'event_status_id' in item:
            analysis['event_status_ids'].add(item['event_status_id'])
    
    # Converter sets para lists para JSON
    analysis['unique_event_ids'] = sorted(list(analysis['unique_event_ids']))
    analysis['unique_market_ids'] = sorted(list(analysis['unique_market_ids']))
    analysis['unique_outcome_ids'] = sorted(list(analysis['unique_outcome_ids']))
    analysis['unique_category_ids'] = sorted(list(analysis['unique_category_ids']))
    analysis['unique_tournament_ids'] = sorted(list(analysis['unique_tournament_ids']))
    analysis['fields'] = sorted(list(analysis['fields']))
    analysis['market_status_ids'] = sorted(list(analysis['market_status_ids']))
    analysis['event_status_ids'] = sorted(list(analysis['event_status_ids']))
    
    return analysis


def main():
    file_path = Path(r'c:\Users\gabri\Downloads\campeonato.txt')
    
    if not file_path.exists():
        print(f"Arquivo não encontrado: {file_path}")
        return
    
    print(f"Lendo arquivo: {file_path}")
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print(f"Tamanho do arquivo: {len(content)} caracteres")
    
    # Tentar parsear como JSON primeiro (caso já esteja em formato válido)
    try:
        data = json.loads(content)
        print("OK: Arquivo ja esta em formato JSON valido")
    except json.JSONDecodeError:
        print("AVISO: Arquivo nao e JSON valido, tentando converter formato DevTools...")
        data = parse_devtools_format(content)
    
    if not data or 'odds' not in data:
        print("ERRO: Nao foi possivel extrair dados 'odds' do arquivo")
        return
    
    odds_list = data['odds']
    print(f"\nOK: Encontrados {len(odds_list)} itens de odds")
    
    # Analisar estrutura
    analysis = analyze_odds_structure(odds_list)
    
    print("\n" + "="*60)
    print("ANÁLISE DA ESTRUTURA")
    print("="*60)
    print(f"Total de itens: {analysis['total_items']}")
    print(f"Eventos únicos: {len(analysis['unique_event_ids'])}")
    print(f"Market IDs únicos: {analysis['unique_market_ids']}")
    print(f"Outcome IDs únicos: {analysis['unique_outcome_ids']}")
    print(f"Categorias únicas: {analysis['unique_category_ids']}")
    print(f"Torneios únicos: {analysis['unique_tournament_ids']}")
    print(f"\nJogos ao vivo: {analysis['is_live_count']}")
    print(f"Mercados especiais: {analysis['special_market_count']}")
    print(f"\nMarket Status IDs: {analysis['market_status_ids']}")
    print(f"Event Status IDs: {analysis['event_status_ids']}")
    
    print(f"\nCampos encontrados ({len(analysis['fields'])}):")
    for field in analysis['fields']:
        print(f"  - {field}")
    
    # Mostrar exemplo de item
    if odds_list:
        print("\n" + "="*60)
        print("EXEMPLO DE ITEM (primeiro)")
        print("="*60)
        example = odds_list[0]
        print(json.dumps(example, indent=2, ensure_ascii=False))
    
    # Agrupar por event_id para ver estrutura completa de um evento
    events_dict = {}
    for item in odds_list:
        event_id = item.get('event_id')
        if not event_id:
            continue
        
        if event_id not in events_dict:
            events_dict[event_id] = {
                'event_info': {
                    'event_id': event_id,
                    'home': item.get('home'),
                    'away': item.get('away'),
                    'date_start': item.get('date_start'),
                    'is_live': item.get('is_live'),
                    'tournament_name': item.get('tournament_name'),
                    'category_name': item.get('category_name'),
                },
                'odds_by_market': {}
            }
        
        market_id = item.get('market_id')
        outcome_id = item.get('outcome_id')
        odd_value = item.get('odd')
        
        if market_id not in events_dict[event_id]['odds_by_market']:
            events_dict[event_id]['odds_by_market'][market_id] = {}
        
        if outcome_id and odd_value:
            events_dict[event_id]['odds_by_market'][market_id][outcome_id] = odd_value
    
    if events_dict:
        print("\n" + "="*60)
        print(f"ESTRUTURA DE EVENTOS ({len(events_dict)} eventos)")
        print("="*60)
        for event_id, event_data in list(events_dict.items())[:3]:  # Mostrar primeiros 3
            print(f"\nEvento {event_id}:")
            print(f"  {event_data['event_info']['home']} vs {event_data['event_info']['away']}")
            print(f"  Torneio: {event_data['event_info']['tournament_name']}")
            print(f"  Ao vivo: {event_data['event_info']['is_live']}")
            print(f"  Mercados: {list(event_data['odds_by_market'].keys())}")
            for market_id, odds in event_data['odds_by_market'].items():
                print(f"    Market {market_id}: {odds}")


if __name__ == '__main__':
    main()

