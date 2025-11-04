"""
Script para processar manualmente o arquivo XHR do DevTools.

Como o arquivo está no formato expandido do DevTools, este script
tenta extrair os dados e reconstruir o JSON.
"""
import json
import re
import sys
from pathlib import Path


def process_devtools_format(filepath: str) -> dict:
    """
    Processa arquivo no formato expandido do DevTools.
    
    O formato DevTools mostra objetos expandidos com propriedades em linhas separadas.
    Padrão observado:
    - linha com número sozinho = índice do array
    - linha com { = início de objeto
    - linhas com chave, depois :, depois valor = propriedades
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
    in_object = False
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        
        # Detectar seção importants
        if line == 'importants' and i + 1 < len(lines) and lines[i+1].strip() == ':':
            current_section = 'importants'
            i += 2  # Pular 'importants' e ':'
            continue
        
        # Detectar seção tourneys
        if line == 'tourneys' and i + 1 < len(lines) and lines[i+1].strip() == ':':
            current_section = 'tourneys'
            i += 2  # Pular 'tourneys' e ':'
            continue
        
        # Se estamos em uma seção
        if current_section:
            # Detectar início de objeto (linha com número seguida de :)
            if line.isdigit() and i + 1 < len(lines) and lines[i+1].strip() == ':':
                # Próximo deve ser início de objeto
                i += 2
                if i < len(lines) and '{' in lines[i]:
                    current_obj = {}
                    in_object = True
                    i += 1
                    continue
            
            # Se estamos dentro de um objeto
            if in_object and current_obj is not None:
                # Linha com chave (sem :)
                if ':' not in line and line and not line.startswith('{') and not line.startswith('}'):
                    # Próxima linha deve ser ':'
                    if i + 1 < len(lines) and lines[i+1].strip() == ':':
                        current_key = line
                        i += 2  # Pular chave e ':'
                        # Próxima linha é o valor
                        if i < len(lines):
                            value_line = lines[i].strip()
                            value = None
                            
                            # Converter valor
                            if value_line == 'null':
                                value = None
                            elif value_line.startswith('"') and value_line.endswith('"'):
                                value = value_line[1:-1]
                            elif value_line.isdigit():
                                value = int(value_line)
                            elif value_line.replace('.', '', 1).replace('-', '', 1).isdigit():
                                try:
                                    value = float(value_line)
                                except:
                                    value = value_line
                            else:
                                value = value_line
                            
                            if current_key:
                                current_obj[current_key] = value
                                current_key = None
                            i += 1
                            continue
                
                # Detectar fim de objeto
                if '}' in line:
                    if current_obj:
                        result[current_section].append(current_obj)
                    current_obj = None
                    in_object = False
        
        i += 1
    
    return result


def main():
    """Função principal."""
    if len(sys.argv) < 2:
        print("Uso: python scripts/process_xhr_manual.py <arquivo_entrada> [arquivo_saida]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "data/xhr_tournaments.json"
    
    print(f"Processando arquivo: {input_file}")
    
    try:
        data = process_devtools_format(input_file)
        
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
            print("\nAviso: Nenhum campeonato encontrado. Verifique o formato do arquivo.")
        
    except Exception as e:
        print(f"Erro ao processar: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

