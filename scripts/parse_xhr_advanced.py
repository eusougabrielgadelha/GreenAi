"""
Parser avançado para arquivo XHR do DevTools.

Este parser processa o formato expandido do DevTools de forma mais robusta,
reconstruindo os objetos JSON a partir do formato expandido.
"""
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Any


def parse_devtools_expanded(filepath: str) -> Dict[str, Any]:
    """
    Parseia arquivo no formato expandido do DevTools.
    
    O formato DevTools expandido tem estrutura:
    - chave
    - :
    - valor
    - Objetos começam com { e terminam com }
    - Arrays começam com [ e terminam com ]
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    result = {
        'importants': [],
        'tourneys': []
    }
    
    # Estratégia: Buscar por padrões de objetos conhecidos
    # Procurar por objetos que têm sport_id, tournament_id, tournament_name
    
    # Pattern para encontrar objetos de campeonato
    # Procurar por blocos que começam com número: { e têm as propriedades esperadas
    pattern = r'(\d+)\s*:\s*\{([^}]+)\}'
    
    # Processar importants
    importants_section = re.search(r'importants\s*:\s*\[(.*?)\]', content, re.DOTALL)
    if importants_section:
        importants_content = importants_section.group(1)
        # Buscar objetos individuais
        obj_matches = re.finditer(r'\{[^}]*sport_id[^}]*tournament_id[^}]*tournament_name[^}]*\}', importants_content, re.DOTALL)
        for match in obj_matches:
            obj_str = match.group(0)
            # Tentar parsear objeto
            obj = parse_object_from_string(obj_str)
            if obj and 'tournament_id' in obj:
                result['importants'].append(obj)
    
    # Processar tourneys (similar)
    tourneys_section = re.search(r'tourneys\s*:\s*\[(.*)\]', content, re.DOTALL)
    if tourneys_section:
        tourneys_content = tourneys_section.group(1)
        # Buscar objetos individuais
        obj_matches = re.finditer(r'\{[^}]*sport_id[^}]*tournament_id[^}]*tournament_name[^}]*\}', tourneys_content, re.DOTALL)
        for match in obj_matches:
            obj_str = match.group(0)
            obj = parse_object_from_string(obj_str)
            if obj and 'tournament_id' in obj:
                result['tourneys'].append(obj)
    
    # Se não encontrou com regex, tentar parse manual linha por linha
    if not result['importants'] and not result['tourneys']:
        result = parse_manual_line_by_line(content)
    
    return result


def parse_object_from_string(obj_str: str) -> Dict[str, Any]:
    """Parseia string de objeto para dict."""
    obj = {}
    
    # Remover chaves externas
    obj_str = obj_str.strip().strip('{}')
    
    # Buscar pares chave:valor
    # Pattern: chave : valor
    pattern = r'(\w+)\s*:\s*([^,}]+)'
    matches = re.findall(pattern, obj_str)
    
    for key, value in matches:
        value = value.strip().strip('"\'')
        
        # Converter tipos
        if value == 'null':
            obj[key] = None
        elif value.isdigit():
            obj[key] = int(value)
        elif value.replace('.', '', 1).isdigit():
            obj[key] = float(value)
        else:
            obj[key] = value
    
    return obj


def parse_manual_line_by_line(content: str) -> Dict[str, Any]:
    """
    Parse manual linha por linha do formato DevTools expandido.
    """
    lines = content.split('\n')
    result = {
        'importants': [],
        'tourneys': []
    }
    
    current_section = None
    current_obj = None
    current_key = None
    expecting_value = False
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        next_line = lines[i+1].strip() if i+1 < len(lines) else ''
        
        # Detectar seção
        if line == 'importants' and next_line == ':':
            current_section = 'importants'
            i += 2
            continue
        elif line == 'tourneys' and next_line == ':':
            current_section = 'tourneys'
            i += 2
            continue
        
        if current_section:
            # Detectar início de objeto (número seguido de :)
            if line.isdigit() and next_line == ':':
                if current_obj:
                    result[current_section].append(current_obj)
                current_obj = {}
                i += 2
                # Próxima linha deve ser {
                if i < len(lines) and '{' in lines[i]:
                    i += 1
                continue
            
            # Dentro de objeto: chave : valor
            if current_obj is not None:
                # Se linha tem só chave e próxima é :
                if ':' not in line and next_line == ':':
                    current_key = line
                    expecting_value = True
                    i += 2
                    # Próxima linha é valor
                    if i < len(lines):
                        value_line = lines[i].strip()
                        value = parse_value(value_line)
                        if current_key:
                            current_obj[current_key] = value
                            current_key = None
                            expecting_value = False
                        i += 1
                        continue
                
                # Fim de objeto
                if '}' in line:
                    if current_obj:
                        result[current_section].append(current_obj)
                    current_obj = None
                    i += 1
                    continue
        
        i += 1
    
    # Adicionar último objeto se houver
    if current_obj and current_section:
        result[current_section].append(current_obj)
    
    return result


def parse_value(value_str: str) -> Any:
    """Parseia valor string para tipo apropriado."""
    value_str = value_str.strip().rstrip(',')
    
    if value_str == 'null':
        return None
    elif value_str.startswith('"') and value_str.endswith('"'):
        return value_str[1:-1]
    elif value_str.isdigit():
        return int(value_str)
    elif value_str.replace('.', '', 1).replace('-', '', 1).isdigit():
        try:
            return float(value_str)
        except:
            return value_str
    else:
        return value_str


def main():
    """Função principal."""
    if len(sys.argv) < 2:
        print("Uso: python scripts/parse_xhr_advanced.py <arquivo_entrada> [arquivo_saida]")
        print("\nPara obter o JSON completo:")
        print("1. Abra DevTools > Network")
        print("2. Encontre a requisição XHR")
        print("3. Clique com botão direito > Copy > Copy response")
        print("4. Cole em um arquivo .json")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "data/xhr_tournaments.json"
    
    print(f"Processando arquivo: {input_file}")
    
    try:
        data = parse_devtools_expanded(input_file)
        
        # Salvar JSON
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        importants_count = len(data.get('importants', []))
        tourneys_count = len(data.get('tourneys', []))
        
        print(f"Conversao concluida!")
        print(f"   - Campeonatos importantes: {importants_count}")
        print(f"   - Total de campeonatos: {tourneys_count}")
        print(f"   - Arquivo salvo em: {output_path}")
        
        if importants_count > 0 or tourneys_count > 0:
            print(f"\nAgora voce pode usar:")
            print(f"   python scripts/map_tournaments.py {output_path}")
        else:
            print("\nAviso: Nenhum campeonato encontrado.")
            print("\nRECOMENDACAO: Para melhor resultado, copie o JSON completo da resposta XHR:")
            print("1. DevTools > Network > XHR")
            print("2. Clique na requisicao")
            print("3. Aba Response")
            print("4. Botao direito > Copy response")
            print("5. Cole em um arquivo .json")
        
    except Exception as e:
        print(f"Erro ao processar: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

