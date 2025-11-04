"""
Script para analisar como a BetNacional categoriza os campeonatos.
"""
import json
from collections import defaultdict
from pathlib import Path

def analyze_categorization():
    """Analisa a estrutura de categorização dos campeonatos."""
    
    # Carregar dados
    data_file = Path("data/tournaments_mapping.json")
    with open(data_file, 'r', encoding='utf-8') as f:
        tournaments = json.load(f)
    
    print("=" * 80)
    print("ANALISE DE CATEGORIZACAO - BETNACIONAL")
    print("=" * 80)
    
    # 1. Estrutura hierárquica
    print("\n1. ESTRUTURA HIERARQUICA")
    print("-" * 80)
    print("Esporte (sport_id) -> Continente (continent_name) -> Categoria/País (category_id, category_name) -> Campeonato (tournament_id)")
    print("\nExemplo:")
    print("  sport_id: 1 (Futebol)")
    print("    continent_name: 'Europa'")
    print("      category_id: 32, category_name: 'Espanha'")
    print("        tournament_id: 8, tournament_name: 'LaLiga'")
    
    # 2. Análise por categoria/país
    print("\n\n2. CATEGORIAS/PAISES")
    print("-" * 80)
    categories = defaultdict(lambda: {'id': None, 'count': 0, 'continent': None, 'tournaments': []})
    
    for t in tournaments:
        cat_name = t.get('category_name', 'Sem categoria')
        cat_id = t.get('category_id')
        continent = t.get('continent_name')
        tournament_name = t.get('tournament_name')
        
        if categories[cat_name]['id'] is None:
            categories[cat_name]['id'] = cat_id
            categories[cat_name]['continent'] = continent
        categories[cat_name]['count'] += 1
        categories[cat_name]['tournaments'].append(tournament_name)
    
    print(f"\nTotal de categorias/paises: {len(categories)}\n")
    
    # Ordenar por quantidade de campeonatos
    sorted_categories = sorted(categories.items(), key=lambda x: x[1]['count'], reverse=True)
    
    print("Top 20 categorias com mais campeonatos:")
    for i, (cat_name, info) in enumerate(sorted_categories[:20], 1):
        continent_str = info['continent'] if info['continent'] else 'N/A'
        print(f"  {i:2d}. {cat_name:30s} (ID: {info['id']:4d}) - {info['count']:2d} campeonato(s) - Continente: {continent_str}")
    
    # 3. Análise por continente
    print("\n\n3. CONTINENTES")
    print("-" * 80)
    continents = defaultdict(lambda: {'count': 0, 'categories': set()})
    
    for t in tournaments:
        continent = t.get('continent_name')
        if continent:
            continents[continent]['count'] += 1
            continents[continent]['categories'].add(t.get('category_name'))
    
    print(f"\nTotal de continentes: {len(continents)}\n")
    
    for continent, info in sorted(continents.items(), key=lambda x: x[1]['count'], reverse=True):
        print(f"  {continent:30s}: {info['count']:3d} campeonatos em {len(info['categories'])} categoria(s)")
    
    # 4. Campeonatos sem categoria
    print("\n\n4. CAMPEONATOS SEM CATEGORIA (category_name vazio)")
    print("-" * 80)
    no_category = [t for t in tournaments if not t.get('category_name')]
    print(f"Total: {len(no_category)} campeonatos\n")
    
    for t in no_category[:10]:
        print(f"  - {t.get('tournament_name')} (ID: {t.get('tournament_id')}, category_id: {t.get('category_id')})")
    
    # 5. Campeonatos importantes
    print("\n\n5. CAMPEONATOS IMPORTANTES")
    print("-" * 80)
    important = [t for t in tournaments if t.get('is_important')]
    print(f"Total: {len(important)} campeonatos importantes\n")
    
    for t in important:
        cat = t.get('category_name', 'Sem categoria')
        print(f"  - {t.get('tournament_name')} (ID: {t.get('tournament_id')}) - Categoria: {cat}")
    
    # 6. Estrutura de URLs
    print("\n\n6. ESTRUTURA DE URLs")
    print("-" * 80)
    print("Padrao de URL:")
    print("  https://betnacional.bet.br/events/{sport_id}/{category_id}/{tournament_id}")
    print("\nExemplos:")
    for t in tournaments[:5]:
        print(f"  {t.get('tournament_name')}")
        print(f"    URL: {t.get('url')}")
        print(f"    sport_id: {t.get('sport_id')}, category_id: {t.get('category_id')}, tournament_id: {t.get('tournament_id')}")
    
    # 7. Observações
    print("\n\n7. OBSERVACOES")
    print("-" * 80)
    print("""
    - sport_id: 1 = Futebol (todos os campeonatos mapeados sao de futebol)
    - category_id: Identifica o pais/categoria (ex: 13 = Brasil, 32 = Espanha)
    - category_name: Nome do pais/categoria (ex: "Brasil", "Espanha", "Clubes Internacionais")
    - continent_name: Nome do continente (ex: "Europa", "Americas") - pode ser null
    - tournament_id: ID unico do campeonato
    - is_important: Indica se e um campeonato destacado
    
    Estrutura hierarquica:
    1. Esporte (sport_id)
       2. Continente (continent_name) - opcional
          3. Categoria/País (category_id, category_name)
             4. Campeonato (tournament_id, tournament_name)
    
    Casos especiais:
    - category_id = 393: "Clubes Internacionais" (Champions League, Libertadores, etc.)
    - category_id = 0: Alguns campeonatos importantes podem ter category_id = 0
    - category_name vazio: Campeonatos importantes que nao sao atribuidos a um pais especifico
    """)

if __name__ == "__main__":
    analyze_categorization()

