"""
Script para analisar os mercados disponíveis em uma página de jogo ao vivo.
"""
import json
import re
from bs4 import BeautifulSoup
from pathlib import Path

def analyze_html_markets(html_file: str):
    """Analisa o HTML e identifica todos os mercados disponíveis."""
    
    with open(html_file, 'r', encoding='utf-8') as f:
        html = f.read()
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # 1. Tentar extrair do JSON __NEXT_DATA__
    print("=" * 80)
    print("ANÁLISE DO JSON __NEXT_DATA__")
    print("=" * 80)
    
    script_tag = soup.find("script", id="__NEXT_DATA__")
    if script_tag and script_tag.string:
        try:
            next_data = json.loads(script_tag.string)
            
            # Procurar por dados de mercado no JSON
            def find_markets(obj, path=""):
                """Busca recursiva por estruturas que possam conter dados de mercado."""
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        current_path = f"{path}.{key}" if path else key
                        if any(term in key.lower() for term in ['market', 'odd', 'outcome', 'bet', 'aposta']):
                            print(f"\n[ENCONTRADO] {current_path}")
                            if isinstance(value, (dict, list)):
                                print(f"   Tipo: {type(value).__name__}")
                                if isinstance(value, dict) and len(value) < 10:
                                    print(f"   Conteúdo: {json.dumps(value, indent=2, ensure_ascii=False)}")
                                elif isinstance(value, list) and len(value) < 5:
                                    print(f"   Conteúdo: {json.dumps(value, indent=2, ensure_ascii=False)}")
                        find_markets(value, current_path)
                elif isinstance(obj, list):
                    for i, item in enumerate(obj):
                        find_markets(item, f"{path}[{i}]")
            
            find_markets(next_data)
            
        except json.JSONDecodeError as e:
            print(f"Erro ao decodificar JSON: {e}")
    
    # 2. Analisar estrutura HTML para mercados
    print("\n" + "=" * 80)
    print("ANÁLISE DA ESTRUTURA HTML")
    print("=" * 80)
    
    # Procurar por elementos com data-testid relacionados a mercados
    market_elements = soup.select('[data-testid*="market"], [data-testid*="outcome"], [data-testid*="odd"]')
    print(f"\nElementos com data-testid relacionados a mercados: {len(market_elements)}")
    
    # Agrupar por mercado
    markets_found = {}
    for elem in market_elements[:50]:  # Limitar para não exibir muito
        testid = elem.get('data-testid', '')
        text = elem.get_text(strip=True)
        
        # Tentar identificar o tipo de mercado
        if 'market' in testid.lower():
            market_name = text[:100] if text else testid
            if market_name not in markets_found:
                markets_found[market_name] = []
            markets_found[market_name].append({
                'testid': testid,
                'text': text[:50]
            })
    
    print(f"\nMercados encontrados no HTML:")
    for market_name, items in markets_found.items():
        print(f"\n  • {market_name}")
        for item in items[:3]:  # Mostrar apenas os 3 primeiros
            print(f"    - {item['testid']}: {item['text']}")
    
    # 3. Procurar por texto específico de mercados
    print("\n" + "=" * 80)
    print("BUSCA POR TERMOS ESPECÍFICOS")
    print("=" * 80)
    
    search_terms = {
        'Placar': ['placar', 'score', 'resultado'],
        'Gols Exatos': ['gols exatos', 'correct score', 'placar exato'],
        'Handicap Asiático': ['handicap asiático', 'asian handicap', 'handicap'],
        'Total de Gols': ['total de gols', 'over', 'under', 'total goals'],
        'Ambos Marcam': ['ambos marcam', 'btts', 'both teams']
    }
    
    for term_name, terms in search_terms.items():
        found = False
        for term in terms:
            # Buscar no texto
            if term.lower() in html.lower():
                print(f"\n[OK] '{term_name}' encontrado (termo: '{term}')")
                found = True
                
                # Tentar encontrar contexto
                pattern = re.compile(rf'.{{0,100}}{re.escape(term)}.{{0,100}}', re.IGNORECASE)
                matches = pattern.findall(html)
                if matches:
                    print(f"   Contexto encontrado: {matches[0][:150]}...")
                break
        
        if not found:
            print(f"\n[NAO ENCONTRADO] '{term_name}' NÃO encontrado")
    
    # 4. Extrair estrutura de dados-testid
    print("\n" + "=" * 80)
    print("ESTRUTURA DE DATA-TESTID")
    print("=" * 80)
    
    all_testids = set()
    for elem in soup.select('[data-testid]'):
        testid = elem.get('data-testid', '')
        if testid:
            all_testids.add(testid)
    
    market_testids = [tid for tid in all_testids if any(term in tid.lower() for term in ['market', 'outcome', 'odd', 'bet'])]
    
    print(f"\nTestIDs relacionados a mercados ({len(market_testids)}):")
    for tid in sorted(market_testids)[:20]:
        print(f"  • {tid}")

if __name__ == "__main__":
    html_file = r"c:\Users\gabri\Downloads\64743690"
    
    if not Path(html_file).exists():
        print(f"[ERRO] Arquivo não encontrado: {html_file}")
    else:
        analyze_html_markets(html_file)

