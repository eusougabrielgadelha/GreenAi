"""
Script para atualizar o mapeamento de campeonatos com múltiplas categorias.

Adiciona a categoria "Campeonatos Importantes" aos campeonatos que são importantes.
"""
import json
import sys
from pathlib import Path

# ID especial para categoria "Campeonatos Importantes"
IMPORTANT_CATEGORY_ID = 9999
IMPORTANT_CATEGORY_NAME = "Campeonatos Importantes"

# Mapeamento de category_id para category_name (quando category_name está vazio)
CATEGORY_ID_TO_NAME = {
    1: "Inglaterra",
    7: "Internacional",
    8: "Espanha",
    13: "Brasil",
    17: "Inglaterra",
    18: "Inglaterra",
    30: "Alemanha",
    31: "Itália",
    32: "Espanha",
    33: "Bélgica",
    34: "França",
    35: "Holanda",
    37: "Holanda",
    38: "Bélgica",
    39: "Dinamarca",
    40: "Suécia",
    44: "Alemanha",
    45: "Áustria",
    46: "Suécia",
    47: "Dinamarca",
    48: "Argentina",
    52: "Turquia",
    53: "Itália",
    54: "Espanha",
    65: "Dinamarca",
    66: "Israel",
    67: "Grécia",
    68: "Croácia",
    91: "Rússia",
    98: "Turquia",
    99: "China",
    102: "Chipre",
    131: "Holanda",
    136: "Austrália",
    155: "Argentina",
    169: "Bielorrússia",
    170: "Croácia",
    171: "Chipre",
    172: "República Checa",
    174: "Inglaterra Amadores",
    176: "Inglaterra Amadores",
    178: "Estónia",
    182: "França",
    183: "França",
    185: "Grécia",
    186: "Grécia",
    187: "Hungria",
    196: "Japão",
    197: "Letónia",
    198: "Lituânia",
    199: "Macedónia",
    200: "Irlanda do Norte",
    202: "Polónia",
    203: "Rússia",
    204: "Rússia",
    205: "República Checa",
    206: "Escócia",
    207: "Escócia",
    209: "Escócia",
    210: "Sérvia",
    211: "Eslováquia",
    212: "Eslovénia",
    214: "Suécia",
    215: "Suíça",
    216: "Suíça",
    217: "Alemanha",
    218: "Ucrânia",
    224: "Eslováquia",
    229: "Polónia",
    232: "Alemanha Amadores",
    238: "Portugal",
    239: "Portugal",
    240: "Equador",
    242: "Estados Unidos da América",
    247: "Bulgária",
    254: "País de Gales",
    266: "Israel",
    270: "Internacional",
    291: "Eslovénia",
    303: "Eslováquia",
    315: "Chipre",
    325: "Brasil",
    326: "Bélgica",
    328: "Itália",
    329: "Espanha",
    331: "Escócia",
    335: "França",
    341: "Itália",
    347: "Escócia",
    358: "África do Sul",
    365: "Bulgária",
    367: "País de Gales",
    373: "Brasil",
    375: "Grécia",
    384: "Clubes Internacionais",
    390: "Brasil",
    402: "Japão",
    410: "República da Coreia",
    445: "Áustria",
    463: "Clubes Internacionais",
    480: "Clubes Internacionais",
    491: "Alemanha",
    515: "Polónia",
    532: "Eslovénia",
    611: "Irlanda do Norte",
    626: "Vietname",
    634: "Singapura",
    649: "China",
    668: "Clubes Internacionais",
    679: "Clubes Internacionais",
    690: "Luxemburgo",
    703: "Argentina",
    704: "Georgia",
    724: "Croácia",
    727: "Israel",
    736: "Azerbaijão",
    742: "Andorra",
    777: "República da Coreia",
    808: "Egito",
    825: "Catar",
    851: "Internacional",
    937: "Marrocos",
    955: "Arábia Saudita",
    984: "Tunísia",
    1002: "Kuwait",
    1015: "Indonésia",
    1024: "Argentina",
    1032: "Tailândia",
    1044: "Inglaterra Amadores",
    1101: "Suíça",
    1111: "Inglaterra Amadores",
    1131: "Inglaterra Amadores",
    1339: "Hungria",
    1347: "Argentina",
    14193: "Dinamarca",
    14864: "Uganda",
    152: "Roménia",
    155: "Argentina",
    169: "Bielorrússia",
    170: "Croácia",
    172: "República Checa",
    185: "Grécia",
    186: "Grécia",
    187: "Hungria",
    196: "Japão",
    197: "Letónia",
    198: "Lituânia",
    199: "Macedónia",
    202: "Polónia",
    203: "Rússia",
    204: "Rússia",
    205: "República Checa",
    206: "Escócia",
    207: "Escócia",
    209: "Escócia",
    210: "Sérvia",
    211: "Eslováquia",
    212: "Eslovénia",
    215: "Suíça",
    216: "Suíça",
    217: "Alemanha",
    218: "Ucrânia",
    224: "Eslováquia",
    229: "Polónia",
    238: "Portugal",
    239: "Portugal",
    240: "Equador",
    242: "Estados Unidos da América",
    247: "Bulgária",
    254: "País de Gales",
    266: "Israel",
    291: "Eslovénia",
    303: "Eslováquia",
    315: "Chipre",
    326: "Bélgica",
    328: "Itália",
    329: "Espanha",
    331: "Escócia",
    335: "França",
    341: "Itália",
    347: "Escócia",
    358: "África do Sul",
    365: "Bulgária",
    367: "País de Gales",
    375: "Grécia",
    393: "Clubes Internacionais",
    402: "Japão",
    410: "República da Coreia",
    445: "Áustria",
    491: "Alemanha",
    515: "Polónia",
    532: "Eslovénia",
    626: "Vietname",
    634: "Singapura",
    649: "China",
    690: "Luxemburgo",
    704: "Georgia",
    724: "Croácia",
    727: "Israel",
    736: "Azerbaijão",
    742: "Andorra",
    777: "República da Coreia",
    937: "Marrocos",
    955: "Arábia Saudita",
    984: "Tunísia",
    1002: "Kuwait",
    1015: "Indonésia",
    1024: "Argentina",
    1032: "Tailândia",
    1101: "Suíça",
    1111: "Inglaterra Amadores",
    1131: "Inglaterra Amadores",
    1339: "Hungria",
    1347: "Argentina",
    14147: "República Checa",
    14193: "Dinamarca",
    14864: "Uganda",
    1906: "África do Sul",
    1908: "Uruguai",
    2094: "Japão",
    2436: "República da Coreia",
    26056: "Inglaterra Amadores",
    26058: "Inglaterra Amadores",
    26916: "Internacional",
    27072: "Colômbia",
    27100: "Paraguai",
    27382: "México",
    27464: "México",
    27665: "Chile",
    28163: "Estados Unidos da América",
    28432: "Canadá",
    33980: "Bolívia",
    34480: "Clubes Internacionais",
    34834: "Espanha",
    35811: "Uruguai",
    48235: "Roménia",
    40305: "Rússia",
    24864: "Espanha",
    39221: "Itália",
    20808: "Itália",
    26554: "Itália",
    26556: "Itália",
    26558: "Itália",
}


def update_tournaments_with_categories(input_file: str, output_file: str = None):
    """
    Atualiza o mapeamento de campeonatos adicionando múltiplas categorias.
    
    Args:
        input_file: Arquivo JSON com campeonatos
        output_file: Arquivo de saída (se None, sobrescreve o input)
    """
    if output_file is None:
        output_file = input_file
    
    input_path = Path(input_file)
    output_path = Path(output_file)
    
    # Carregar dados
    with open(input_path, 'r', encoding='utf-8') as f:
        tournaments = json.load(f)
    
    updated_count = 0
    
    for tournament in tournaments:
        # Verificar se já tem a estrutura de categorias
        if 'categories' not in tournament:
            tournament['categories'] = []
        
        # Adicionar categoria primária se não existir
        category_id = tournament.get('category_id', 0)
        category_name = tournament.get('category_name', '')
        
        # Se category_name está vazio mas temos category_id, buscar no mapeamento
        if not category_name and category_id and category_id in CATEGORY_ID_TO_NAME:
            category_name = CATEGORY_ID_TO_NAME[category_id]
        
        # Verificar se categoria primária já está na lista
        has_primary = any(
            cat.get('category_id') == category_id and cat.get('is_primary', False)
            for cat in tournament.get('categories', [])
        )
        
        if not has_primary and category_name and category_id:
            tournament['categories'].append({
                'category_id': category_id,
                'category_name': category_name,
                'is_primary': True
            })
        
        # Adicionar categoria "Campeonatos Importantes" se for importante
        is_important = tournament.get('is_important', False)
        if is_important:
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
                updated_count += 1
    
    # Salvar arquivo atualizado
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(tournaments, f, ensure_ascii=False, indent=2)
    
    print(f"Atualizacao concluida!")
    print(f"  - Total de campeonatos: {len(tournaments)}")
    print(f"  - Campeonatos importantes atualizados: {updated_count}")
    print(f"  - Arquivo salvo em: {output_path}")


def main():
    """Função principal."""
    if len(sys.argv) < 2:
        print("Uso: python scripts/update_tournaments_categories.py <arquivo_json> [arquivo_saida]")
        print("\nExemplo:")
        print("  python scripts/update_tournaments_categories.py data/tournaments_mapping.json")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    update_tournaments_with_categories(input_file, output_file)


if __name__ == "__main__":
    main()

