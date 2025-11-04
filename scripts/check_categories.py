"""Script para verificar categorias dos campeonatos."""
import json

data = json.load(open('data/tournaments_mapping.json', encoding='utf-8'))
important = [t for t in data if t.get('is_important')]

print(f'Total importantes: {len(important)}\n')
print('Verificando categorias:\n')

for t in important[:5]:
    categories = [c['category_name'] for c in t.get('categories', [])]
    print(f"{t['tournament_name']}: {categories}")

