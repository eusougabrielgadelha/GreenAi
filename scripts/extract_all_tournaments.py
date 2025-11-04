"""
Script para extrair TODOS os campeonatos do arquivo XHR do DevTools.

Este script processa o formato expandido do DevTools linha por linha,
reconstruindo os objetos JSON corretamente.
"""
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional


def parse_devtools_expanded_robust(filepath: str) -> Dict[str, Any]:
    """
    Parse robusto do formato expandido do DevTools.
    
    Processa linha por linha, reconstruindo objetos JSON.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    result = {
        'importants': [],
        'tourneys': []
    }
    
    current_section = None
    current_obj = None
    current_key = None
    brace_stack = []
    in_array = False
    array_index = None
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        next_line = lines[i+1].strip() if i+1 < len(lines) else ''
        
        # Detectar início de seção
        if line == 'importants' and next_line == ':':
            current_section = 'importants'
            in_array = True
            i += 2
            # Próxima linha deve ser [
            if i < len(lines) and '[' in lines[i]:
                i += 1
            continue
        
        if line == 'tourneys' and next_line == ':':
            current_section = 'tourneys'
            in_array = True
            i += 2
            # Próxima linha deve ser [
            if i < len(lines) and '[' in lines[i]:
                i += 1
            continue
        
        # Se estamos em uma seção
        if current_section and in_array:
            # Detectar início de objeto (número seguido de :)
            if line.isdigit() and next_line == ':':
                # Salvar objeto anterior se existir
                if current_obj and current_obj.get('tournament_id'):
                    result[current_section].append(current_obj)
                
                array_index = int(line)
                current_obj = {}
                brace_stack = []
                i += 2
                # Próxima linha deve ser {
                if i < len(lines) and '{' in lines[i]:
                    brace_stack.append('{')
                    i += 1
                continue
            
            # Processar dentro de objeto
            if current_obj is not None and brace_stack:
                # Linha com chave (sem :)
                if ':' not in line and line and not line.startswith('{') and not line.startswith('}'):
                    # Verificar se próxima linha é ':'
                    if next_line == ':':
                        current_key = line
                        i += 2
                        # Próxima linha é o valor
                        if i < len(lines):
                            value_line = lines[i].strip().rstrip(',')
                            value = parse_value(value_line)
                            if current_key:
                                current_obj[current_key] = value
                                current_key = None
                            i += 1
                            continue
                
                # Detectar chaves com valores inline (ex: "key: value")
                if ':' in line and not line.startswith('{') and not line.startswith('}'):
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        value_str = parts[1].strip().rstrip(',')
                        value = parse_value(value_str)
                        current_obj[key] = value
                
                # Detectar chaves de objeto aninhado
                if '{' in line:
                    brace_stack.append('{')
                
                # Detectar fim de objeto
                if '}' in line:
                    brace_stack.pop()
                    if not brace_stack:  # Fim do objeto principal
                        if current_obj and current_obj.get('tournament_id'):
                            result[current_section].append(current_obj)
                        current_obj = None
        
        i += 1
    
    # Adicionar último objeto se houver
    if current_obj and current_obj.get('tournament_id') and current_section:
        if current_obj not in result[current_section]:
            result[current_section].append(current_obj)
    
    return result


def parse_value(value_str: str) -> Any:
    """Parseia valor string para tipo apropriado."""
    value_str = value_str.strip().rstrip(',')
    
    if value_str == 'null':
        return None
    elif value_str.startswith('"') and value_str.endswith('"'):
        return value_str[1:-1]
    elif value_str.startswith("'") and value_str.endswith("'"):
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


def extract_from_html_file(html_file: str) -> Optional[Dict[str, Any]]:
    """
    Tenta extrair dados do HTML também.
    """
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            html = f.read()
        
        # Buscar __NEXT_DATA__
        pattern = r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>'
        match = re.search(pattern, html, re.DOTALL)
        
        if match:
            json_str = match.group(1)
            data = json.loads(json_str)
            
            # Buscar recursivamente por importants/tourneys
            def find_tournaments(obj):
                if isinstance(obj, dict):
                    if 'importants' in obj and 'tourneys' in obj:
                        return obj
                    for value in obj.values():
                        result = find_tournaments(value)
                        if result:
                            return result
                elif isinstance(obj, list):
                    for item in obj:
                        result = find_tournaments(item)
                        if result:
                            return result
                return None
            
            result = find_tournaments(data)
            if result:
                return result
    except Exception as e:
        print(f"Erro ao processar HTML: {e}")
    
    return None


def main():
    """Função principal."""
    if len(sys.argv) < 2:
        print("Uso: python scripts/extract_all_tournaments.py <arquivo_xhr> [arquivo_html]")
        sys.exit(1)
    
    xhr_file = sys.argv[1]
    html_file = sys.argv[2] if len(sys.argv) > 2 else None
    output_file = "data/xhr_tournaments_complete.json"
    
    print(f"Processando arquivo XHR: {xhr_file}")
    
    # Processar XHR
    data = parse_devtools_expanded_robust(xhr_file)
    
    # Tentar complementar com HTML se fornecido
    if html_file:
        print(f"Tentando complementar com HTML: {html_file}")
        html_data = extract_from_html_file(html_file)
        if html_data:
            # Mesclar dados
            if 'importants' in html_data and html_data['importants']:
                # Adicionar apenas novos
                existing_ids = {t.get('tournament_id') for t in data['importants']}
                for t in html_data['importants']:
                    if t.get('tournament_id') not in existing_ids:
                        data['importants'].append(t)
            
            if 'tourneys' in html_data and html_data['tourneys']:
                existing_ids = {t.get('tournament_id') for t in data['tourneys']}
                for t in html_data['tourneys']:
                    if t.get('tournament_id') not in existing_ids:
                        data['tourneys'].append(t)
    
    # Salvar JSON
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    importants_count = len(data.get('importants', []))
    tourneys_count = len(data.get('tourneys', []))
    total = importants_count + tourneys_count
    
    print(f"\nResultado:")
    print(f"   - Campeonatos importantes: {importants_count}")
    print(f"   - Total de campeonatos: {tourneys_count}")
    print(f"   - TOTAL GERAL: {total}")
    print(f"   - Arquivo salvo em: {output_path}")
    
    if total > 0:
        print(f"\nGerando mapeamento completo...")
        print(f"   python scripts/map_tournaments.py {output_path}")
    else:
        print("\nAviso: Nenhum campeonato extraido.")
        print("O arquivo pode estar em formato diferente.")
        print("\nPara melhor resultado:")
        print("1. DevTools > Network > XHR")
        print("2. Clique na requisicao")
        print("3. Aba Response")
        print("4. Botao direito > Copy response")
        print("5. Cole em um arquivo .json")


if __name__ == "__main__":
    main()

