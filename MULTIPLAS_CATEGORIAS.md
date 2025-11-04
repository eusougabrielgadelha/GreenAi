# 📊 Sistema de Múltiplas Categorias e Modo IMPORTANT_ONLY

## 🎯 Objetivo

Implementação de um sistema que permite:
1. **Múltiplas categorias por campeonato** - Um campeonato pode pertencer a várias categorias
2. **Categoria especial "Campeonatos Importantes"** - Categoria adicional para campeonatos destacados
3. **Modo IMPORTANT_ONLY** - Flag para fazer scraping apenas nos campeonatos importantes

## 🏗️ Estrutura de Dados

### Antes (Estrutura Simples)

```python
{
    "tournament_id": 7,
    "tournament_name": "UEFA Champions League",
    "category_id": 393,
    "category_name": "Clubes Internacionais",
    "is_important": True
}
```

### Depois (Estrutura com Múltiplas Categorias)

```python
{
    "tournament_id": 7,
    "tournament_name": "UEFA Champions League",
    "category_id": 393,  # Categoria primária (compatibilidade)
    "category_name": "Clubes Internacionais",  # Categoria primária (compatibilidade)
    "is_important": True,
    "categories": [  # Lista de TODAS as categorias
        {
            "category_id": 393,
            "category_name": "Clubes Internacionais",
            "is_primary": True
        },
        {
            "category_id": 9999,
            "category_name": "Campeonatos Importantes",
            "is_primary": False
        }
    ]
}
```

## 📋 Categoria "Campeonatos Importantes"

- **category_id**: `9999` (ID especial)
- **category_name**: `"Campeonatos Importantes"`
- **Aplicação**: Adicionada automaticamente a todos os campeonatos com `is_important = True`

### Campeonatos Importantes (8 total):

1. Brasileirão Série A (ID: 325)
2. Brasileirão Série B (ID: 390)
3. Inglaterra - Premier League (ID: 17)
4. Inglaterra - Championship (ID: 18)
5. Espanha - LaLiga (ID: 8)
6. UEFA Champions League (ID: 7)
7. UEFA Europa League (ID: 679)
8. UEFA Conference League (ID: 34480)

## ⚙️ Configuração: SCRAPE_IMPORTANT_ONLY

### Variável de Ambiente

Adicione no arquivo `.env`:

```bash
# Se True, faz scraping apenas em campeonatos importantes
# Se False, usa todos os campeonatos configurados em BETTING_LINKS
SCRAPE_IMPORTANT_ONLY=false
```

### Como Funciona

1. **SCRAPE_IMPORTANT_ONLY = false** (padrão):
   - Usa todos os links de `BETTING_LINKS` + `EXTRA_LINKS`
   - Comportamento normal

2. **SCRAPE_IMPORTANT_ONLY = true**:
   - Busca automaticamente todos os campeonatos importantes do mapeamento
   - Retorna apenas as URLs dos campeonatos importantes
   - Ignora `BETTING_LINKS` (exceto em caso de erro)

### Código

A função `get_all_betting_links()` em `config/settings.py` verifica a flag:

```python
def get_all_betting_links() -> list[str]:
    """
    Retorna todos os links de apostas, incluindo extras.
    
    Se SCRAPE_IMPORTANT_ONLY=True, retorna apenas links de campeonatos importantes.
    """
    from scraping.tournaments import get_important_tournaments, get_all_football_tournaments
    
    # Se configurado para apenas importantes, usar mapeamento
    if SCRAPE_IMPORTANT_ONLY:
        tournaments = get_all_football_tournaments()
        important = get_important_tournaments(tournaments)
        important_urls = [t.get('url') for t in important if t.get('url')]
        if important_urls:
            return important_urls
    
    # Modo normal: usar BETTING_LINKS
    base = [cfg["link"] for cfg in BETTING_LINKS.values() if "link" in cfg]
    base.extend(EXTRA_LINKS)
    # ... remover duplicatas ...
    return out
```

## 🔍 Funções Disponíveis

### 1. Buscar por Categoria (ID)

```python
from scraping.tournaments import get_tournaments_by_category

# Buscar campeonatos do Brasil
brasileiros = get_tournaments_by_category(13)

# Buscar campeonatos importantes
importantes = get_tournaments_by_category(9999)  # ID especial
```

### 2. Buscar por Categoria (Nome)

```python
from scraping.tournaments import get_tournaments_by_category_name

# Buscar campeonatos do Brasil
brasileiros = get_tournaments_by_category_name("Brasil")

# Buscar campeonatos importantes
importantes = get_tournaments_by_category_name("Campeonatos Importantes")
```

### 3. Buscar Apenas Importantes

```python
from scraping.tournaments import get_important_tournaments

# Buscar todos os campeonatos importantes
importantes = get_important_tournaments()
```

### 4. Verificar Categorias de um Campeonato

```python
from scraping.tournaments import get_tournament_by_id

champions = get_tournament_by_id(7)
if champions:
    print("Categorias:", [c['category_name'] for c in champions.get('categories', [])])
    # Output: ['Clubes Internacionais', 'Campeonatos Importantes']
```

## 📝 Exemplos de Uso

### Exemplo 1: Ativar Modo IMPORTANT_ONLY

**Arquivo `.env`:**
```bash
SCRAPE_IMPORTANT_ONLY=true
```

**Resultado:**
- Sistema usa apenas os 8 campeonatos importantes
- URLs são geradas automaticamente do mapeamento
- Não usa `BETTING_LINKS` (exceto em caso de erro)

### Exemplo 2: Listar Campeonatos por Categoria

```python
from scraping.tournaments import (
    get_all_football_tournaments,
    get_tournaments_by_category_name
)

# Buscar todos os campeonatos
all_tournaments = get_all_football_tournaments()

# Filtrar apenas importantes
importantes = get_tournaments_by_category_name("Campeonatos Importantes", all_tournaments)

print(f"Encontrados {len(importantes)} campeonatos importantes")
for t in importantes:
    print(f"  - {t['tournament_name']} ({t['url']})")
```

### Exemplo 3: Verificar Todas as Categorias de um Campeonato

```python
from scraping.tournaments import get_tournament_by_id

brasileirao = get_tournament_by_id(325)
if brasileirao:
    print(f"Campeonato: {brasileirao['tournament_name']}")
    print("Categorias:")
    for cat in brasileirao.get('categories', []):
        primary = " (primária)" if cat.get('is_primary') else ""
        print(f"  - {cat['category_name']}{primary}")
    
# Output:
# Campeonato: Brasileirão Série A
# Categorias:
#   - Brasil (primária)
#   - Campeonatos Importantes
```

## 🧪 Testando

Use o script de teste:

```bash
python scripts/test_important_only.py
```

Isso mostra:
- Estado atual da configuração
- Quantos links serão usados
- Quais campeonatos serão processados

## 🔄 Atualização de Dados

Se você já tem um arquivo `tournaments_mapping.json` antigo, atualize-o:

```bash
python scripts/update_tournaments_categories.py data/tournaments_mapping.json
```

Isso adiciona:
- Campo `categories` com lista de categorias
- Categoria "Campeonatos Importantes" para campeonatos importantes

## 📊 Compatibilidade

### Retrocompatibilidade

O sistema mantém compatibilidade com código antigo:

- `category_id` e `category_name` ainda funcionam (categoria primária)
- Código que não usa `categories` continua funcionando
- Novas funções usam `categories` para buscar múltiplas categorias

### Exemplo de Código Antigo (ainda funciona):

```python
# Código antigo continua funcionando
tournament = get_tournament_by_id(325)
category_id = tournament['category_id']  # 13 (Brasil)
category_name = tournament['category_name']  # "Brasil"
```

### Exemplo de Código Novo:

```python
# Código novo usa múltiplas categorias
tournament = get_tournament_by_id(325)
all_categories = tournament.get('categories', [])
# [{'category_id': 13, 'category_name': 'Brasil', 'is_primary': True},
#  {'category_id': 9999, 'category_name': 'Campeonatos Importantes', 'is_primary': False}]
```

## 🎯 Casos de Uso

### 1. Modo Rápido (Apenas Importantes)

Quando você quer fazer scraping rápido apenas nos principais campeonatos:

```bash
# .env
SCRAPE_IMPORTANT_ONLY=true
```

### 2. Modo Completo (Todos os Campeonatos)

Quando você quer fazer scraping em todos os campeonatos configurados:

```bash
# .env
SCRAPE_IMPORTANT_ONLY=false
```

### 3. Filtrar por Categoria Específica

```python
from scraping.tournaments import get_tournaments_by_category_name

# Buscar apenas campeonatos brasileiros
brasileiros = get_tournaments_by_category_name("Brasil")

# Buscar apenas campeonatos importantes
importantes = get_tournaments_by_category_name("Campeonatos Importantes")
```

## 📝 Notas Importantes

1. **category_id = 9999** é reservado para "Campeonatos Importantes"
2. **is_primary** indica a categoria principal (país de origem)
3. Campeonatos importantes têm **duas categorias**: país + "Campeonatos Importantes"
4. A função `get_all_betting_links()` verifica automaticamente `SCRAPE_IMPORTANT_ONLY`
5. Se houver erro ao buscar campeonatos importantes, o sistema faz fallback para `BETTING_LINKS`

