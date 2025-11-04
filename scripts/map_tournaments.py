"""
Script para mapear todos os campeonatos de futebol da BetNacional.

Este script:
1. Busca todos os campeonatos via API XHR ou HTML
2. Organiza os dados por categoria/país
3. Exporta para JSON e exibe resumo formatado
"""
import sys
import os
import json
from pathlib import Path

# Adiciona o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraping.tournaments import (
    get_all_football_tournaments,
    export_tournaments_to_json,
    get_tournaments_by_category
)
from utils.logger import logger


def format_tournament_summary(tournaments: list) -> str:
    """Formata resumo dos campeonatos para exibição."""
    output = []
    output.append("\n" + "=" * 80)
    output.append(f"MAPEAMENTO DE CAMPEONATOS - FUTEBOL")
    output.append("=" * 80)
    output.append(f"\nTotal de campeonatos encontrados: {len(tournaments)}\n")
    
    # Agrupar por categoria
    by_category = {}
    for t in tournaments:
        cat_name = t.get('category_name', 'Sem categoria')
        if cat_name not in by_category:
            by_category[cat_name] = []
        by_category[cat_name].append(t)
    
    # Ordenar categorias
    sorted_categories = sorted(by_category.keys(), key=lambda x: x.lower())
    
    output.append("Campeonatos por Categoria/Pais:\n")
    
    for i, category in enumerate(sorted_categories, 1):
        tournaments_in_cat = by_category[category]
        output.append(f"\n{i}. {category} ({len(tournaments_in_cat)} campeonato(s))")
        output.append("-" * 80)
        
        for j, tournament in enumerate(tournaments_in_cat, 1):
            tournament_id = tournament.get('tournament_id')
            tournament_name = tournament.get('tournament_name', 'N/A')
            url = tournament.get('url', '')
            is_important = tournament.get('is_important', False)
            star = "*" if is_important else " "
            
            output.append(f"   {star} {j}. {tournament_name}")
            output.append(f"      ID: {tournament_id} | URL: {url}")
    
    # Listar campeonatos importantes separadamente
    important_tournaments = [t for t in tournaments if t.get('is_important', False)]
    if important_tournaments:
        output.append("\n" + "=" * 80)
        output.append("* CAMPEONATOS IMPORTANTES")
        output.append("=" * 80)
        
        for i, tournament in enumerate(important_tournaments, 1):
            tournament_id = tournament.get('tournament_id')
            tournament_name = tournament.get('tournament_name', 'N/A')
            url = tournament.get('url', '')
            category = tournament.get('category_name', 'N/A')
            
            output.append(f"\n{i}. {tournament_name}")
            output.append(f"   Categoria: {category}")
            output.append(f"   ID: {tournament_id}")
            output.append(f"   URL: {url}")
    
    output.append("\n" + "=" * 80)
    output.append("Estrutura de Dados")
    output.append("=" * 80)
    output.append("""
Cada campeonato contém:
- sport_id: ID do esporte (1 = futebol)
- category_id: ID da categoria/país
- tournament_id: ID único do campeonato
- tournament_name: Nome do campeonato
- category_name: Nome da categoria/país
- url: URL completa para eventos do campeonato
- is_important: Se é um campeonato destacado
- season_id: ID da temporada (pode ser 0)
""")
    
    return "\n".join(output)


def save_tournaments_mapping(tournaments: list, output_dir: str = "data"):
    """Salva mapeamento em múltiplos formatos."""
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # JSON completo
    json_file = output_path / "tournaments_mapping.json"
    export_tournaments_to_json(tournaments, str(json_file))
    
    # JSON simplificado (apenas IDs e nomes)
    simplified = []
    for t in tournaments:
        simplified.append({
            'tournament_id': t.get('tournament_id'),
            'tournament_name': t.get('tournament_name'),
            'category_name': t.get('category_name'),
            'url': t.get('url'),
            'is_important': t.get('is_important', False)
        })
    
    simplified_file = output_path / "tournaments_simplified.json"
    with open(simplified_file, 'w', encoding='utf-8') as f:
        json.dump(simplified, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ Mapeamento simplificado salvo em {simplified_file}")
    
    # CSV simples (para fácil visualização)
    csv_file = output_path / "tournaments_mapping.csv"
    with open(csv_file, 'w', encoding='utf-8') as f:
        f.write("tournament_id,tournament_name,category_name,url,is_important\n")
        for t in tournaments:
            tid = t.get('tournament_id', '')
            tname = t.get('tournament_name', '').replace(',', ';')
            cname = t.get('category_name', '').replace(',', ';')
            url = t.get('url', '')
            important = 'Sim' if t.get('is_important', False) else 'Não'
            f.write(f"{tid},{tname},{cname},{url},{important}\n")
    logger.info(f"✅ Mapeamento CSV salvo em {csv_file}")
    
    # Arquivo Python com dicionário (para uso no código)
    py_file = output_path / "tournaments_dict.py"
    with open(py_file, 'w', encoding='utf-8') as f:
        f.write("# -*- coding: utf-8 -*-\n")
        f.write('"""Mapeamento de campeonatos de futebol da BetNacional."""\n\n')
        f.write("TOURNAMENTS_MAP = {\n")
        for t in tournaments:
            tid = t.get('tournament_id')
            tname = t.get('tournament_name', '').replace("'", "\\'")
            cname = t.get('category_name', '').replace("'", "\\'")
            url = t.get('url', '')
            important = t.get('is_important', False)
            
            f.write(f"    {tid}: {{\n")
            f.write(f"        'name': '{tname}',\n")
            f.write(f"        'category': '{cname}',\n")
            f.write(f"        'url': '{url}',\n")
            f.write(f"        'is_important': {important},\n")
            f.write(f"    }},\n")
        f.write("}\n")
    logger.info(f"✅ Mapeamento Python salvo em {py_file}")


def main():
    """Função principal."""
    import sys
    
    logger.info("Iniciando mapeamento de campeonatos...")
    
    # Verificar se foi fornecido arquivo JSON como argumento
    json_file = None
    if len(sys.argv) > 1:
        json_file = sys.argv[1]
        logger.info(f"Usando arquivo JSON fornecido: {json_file}")
    
    # Buscar todos os campeonatos
    tournaments = get_all_football_tournaments(json_file=json_file)
    
    if not tournaments:
        logger.error("Nenhum campeonato encontrado!")
        logger.info("\nDica: Voce pode fornecer um arquivo JSON com dados XHR:")
        logger.info("   python scripts/map_tournaments.py caminho/para/dados_xhr.json")
        return
    
    # Exibir resumo
    summary = format_tournament_summary(tournaments)
    print(summary)
    
    # Salvar mapeamentos
    logger.info("\nSalvando mapeamentos em arquivos...")
    save_tournaments_mapping(tournaments)
    
    logger.info("\nMapeamento concluido com sucesso!")


if __name__ == "__main__":
    main()

