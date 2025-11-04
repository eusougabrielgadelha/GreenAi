"""
Script auxiliar para converter dados XHR salvos como texto para JSON.

Este script processa o arquivo "sports xhr.txt" que contém dados XHR
salvos do DevTools e converte para um formato JSON válido.
"""
import json
import re
import sys
from pathlib import Path


def parse_xhr_text_file(filepath: str) -> dict:
    """
    Parseia arquivo de texto com dados XHR do DevTools.
    
    O arquivo contém uma estrutura JSON parcialmente formatada do formato DevTools.
    Precisamos converter para JSON válido.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Estratégia 1: Tentar encontrar JSON válido completo
    # Procurar por objeto que começa com { e tem importants/tourneys
    pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    matches = re.findall(pattern, content, re.DOTALL)
    
    for match in matches:
        try:
            data = json.loads(match)
            if 'importants' in data or 'tourneys' in data:
                return data
        except:
            continue
    
    # Estratégia 2: Parse manual do formato DevTools
    # O formato DevTools tem chaves em linhas separadas, preciso reconstruir
    result = {}
    
    # Encontrar início do objeto principal
    lines = content.split('\n')
    
    # Procurar por "importants" e "tourneys"
    in_importants = False
    in_tourneys = False
    current_obj = None
    objects_list = []
    brace_count = 0
    
    for i, line in enumerate(lines):
        line = line.strip()
        
        # Detectar início de importants
        if 'importants' in line.lower() and ':' in line:
            in_importants = True
            in_tourneys = False
            objects_list = []
            continue
        
        # Detectar início de tourneys
        if 'tourneys' in line.lower() and ':' in line:
            in_tourneys = True
            in_importants = False
            objects_list = []
            continue
        
        # Se estamos dentro de um array, processar objetos
        if in_importants or in_tourneys:
            # Detectar início de objeto
            if '{' in line:
                if current_obj is None:
                    current_obj = {}
                brace_count += line.count('{')
            
            # Processar propriedades do objeto
            if ':' in line and current_obj is not None:
                parts = line.split(':', 1)
                if len(parts) == 2:
                    key = parts[0].strip().strip('"\'')
                    value = parts[1].strip().rstrip(',')
                    
                    # Limpar aspas e converter tipos
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value == 'null':
                        value = None
                    elif value.isdigit():
                        value = int(value)
                    elif value.replace('.', '', 1).isdigit():
                        value = float(value)
                    
                    current_obj[key] = value
            
            # Detectar fim de objeto
            if '}' in line:
                brace_count -= line.count('}')
                if brace_count <= 0 and current_obj:
                    objects_list.append(current_obj)
                    current_obj = None
                    brace_count = 0
    
    # Se encontrou objetos, adicionar ao resultado
    if in_importants and objects_list:
        result['importants'] = objects_list
    
    # Tentar parsear tourneys também (pode estar em outro formato)
    if 'tourneys' in content.lower():
        # Tentar extrair usando regex mais amplo
        tourneys_match = re.search(r'tourneys\s*:\s*\[(.*)\]', content, re.DOTALL)
        if tourneys_match:
            # Tentar parsear manualmente os objetos do tourneys
            tourneys_content = tourneys_match.group(1)
            # Por enquanto, vamos tentar uma abordagem diferente
            pass
    
    # Estratégia 3: Se não conseguiu parsear, tentar usar o conteúdo original
    # e fazer substituições para tornar JSON válido
    if not result:
        # Tentar substituir formato DevTools por JSON válido
        json_str = content
        
        # Substituir chaves sem aspas
        json_str = re.sub(r'(\w+)\s*:', r'"\1":', json_str)
        
        # Substituir null sem aspas
        json_str = re.sub(r':\s*null', r': null', json_str)
        
        # Tentar encontrar e parsear
        try:
            # Encontrar objeto principal
            start = json_str.find('{')
            end = json_str.rfind('}')
            if start >= 0 and end > start:
                json_str = json_str[start:end+1]
                data = json.loads(json_str)
                if 'importants' in data or 'tourneys' in data:
                    return data
        except:
            pass
    
    if result:
        return result
    
    raise ValueError("Nao foi possivel parsear o arquivo como JSON. Tente copiar o JSON completo do DevTools.")


def main():
    """Função principal."""
    if len(sys.argv) < 2:
        print("Uso: python scripts/convert_xhr_to_json.py <arquivo_entrada> [arquivo_saida]")
        print("\nExemplo:")
        print("  python scripts/convert_xhr_to_json.py 'c:\\Users\\gabri\\Downloads\\sports xhr.txt' data/xhr_tournaments.json")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "data/xhr_tournaments.json"
    
    print(f"Processando arquivo: {input_file}")
    
    try:
        # Parsear arquivo
        data = parse_xhr_text_file(input_file)
        
        # Salvar JSON
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Contar campeonatos
        importants_count = len(data.get('importants', []))
        tourneys_count = len(data.get('tourneys', []))
        
        print(f"Conversao concluida!")
        print(f"   - Campeonatos importantes: {importants_count}")
        print(f"   - Total de campeonatos: {tourneys_count}")
        print(f"   - Arquivo salvo em: {output_path}")
        print(f"\nAgora voce pode usar:")
        print(f"   python scripts/map_tournaments.py {output_path}")
        
    except Exception as e:
        print(f"Erro ao processar arquivo: {e}")
        print("\nDica: O arquivo pode estar em um formato diferente.")
        print("   Tente abrir o arquivo no DevTools e copiar o JSON completo.")
        sys.exit(1)


if __name__ == "__main__":
    main()

