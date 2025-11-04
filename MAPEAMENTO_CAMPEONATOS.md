# 📋 Mapeamento de Campeonatos de Futebol - BetNacional

Este documento explica como mapear e usar todos os campeonatos de futebol disponíveis na BetNacional.

## 🎯 Objetivo

Criar um mapeamento completo de todos os campeonatos de futebol com:
- **IDs únicos** (tournament_id, category_id, sport_id)
- **Nomes** dos campeonatos
- **URLs** para scraping de jogos
- **Categorias/Países** de origem

## 🚀 Como Usar

### Opção 1: Usar dados XHR salvos manualmente

Se você salvou os dados XHR do DevTools (como no arquivo `sports xhr.txt`):

```bash
# 1. Converter o arquivo de texto para JSON
python scripts/convert_xhr_to_json.py "caminho/para/sports xhr.txt" data/xhr_tournaments.json

# 2. Gerar mapeamento completo
python scripts/map_tournaments.py data/xhr_tournaments.json
```

### Opção 2: Buscar automaticamente via HTML

```bash
# Busca automaticamente da página /sports/1
python scripts/map_tournaments.py
```

## 📊 Estrutura dos Dados

Cada campeonato contém:

```python
{
    'sport_id': 1,                    # ID do esporte (1 = futebol)
    'category_id': 13,               # ID da categoria/país
    'tournament_id': 325,            # ID único do campeonato
    'tournament_name': 'Brasileirão Série A',  # Nome do campeonato
    'category_name': 'Brasil',       # Nome da categoria/país
    'url': 'https://betnacional.bet.br/events/1/0/325',  # URL completa
    'is_important': True,            # Se é campeonato destacado
    'season_id': 128461              # ID da temporada
}
```

## 📁 Arquivos Gerados

O script `map_tournaments.py` gera vários arquivos na pasta `data/`:

1. **`tournaments_mapping.json`** - JSON completo com todos os dados
2. **`tournaments_simplified.json`** - JSON simplificado (apenas IDs e nomes)
3. **`tournaments_mapping.csv`** - CSV para visualização em planilhas
4. **`tournaments_dict.py`** - Dicionário Python para uso no código

## 🔍 Exemplo de Uso no Código

```python
from scraping.tournaments import (
    get_all_football_tournaments,
    get_tournament_by_id,
    get_tournaments_by_category
)

# Buscar todos os campeonatos
tournaments = get_all_football_tournaments()

# Buscar campeonato específico
champions_league = get_tournament_by_id(7, tournaments)
# Retorna: {'tournament_id': 7, 'tournament_name': 'UEFA Champions League', ...}

# Buscar campeonatos de um país
brasileiros = get_tournaments_by_category(13, tournaments)  # category_id=13 é Brasil
```

## 📝 Campeonatos Importantes

Os campeonatos marcados como `is_important: True` são os principais destacados:

- UEFA Champions League (tournament_id: 7)
- Inglaterra - Premier League (tournament_id: 17)
- Espanha - LaLiga (tournament_id: 8)
- Alemanha - Bundesliga (tournament_id: 35)
- Brasileirão Série A (tournament_id: 325)
- E outros...

## 🔗 URLs de Scraping

Cada campeonato tem uma URL no formato:
```
https://betnacional.bet.br/events/{sport_id}/{category_id}/{tournament_id}
```

Exemplos:
- Champions League: `https://betnacional.bet.br/events/1/0/7`
- Brasileirão Série A: `https://betnacional.bet.br/events/1/13/325`
- Premier League: `https://betnacional.bet.br/events/1/1/17`

## 🛠️ Integração com Sistema de Scraping

O mapeamento pode ser usado para:

1. **Listar campeonatos disponíveis** para o usuário escolher
2. **Validar URLs** antes de fazer scraping
3. **Organizar jogos por campeonato** automaticamente
4. **Criar watchlists** por categoria/país

### Exemplo: Buscar jogos de um campeonato

```python
from scraping.tournaments import get_tournament_by_id
from scraping.fetchers import fetch_events_from_link

# Buscar campeonato
tournament = get_tournament_by_id(7)  # Champions League

if tournament:
    url = tournament['url']
    events = await fetch_events_from_link(url, backend='requests')
    # events agora contém todos os jogos da Champions League
```

## 📊 Estatísticas

Após executar o mapeamento, você verá:

- Total de campeonatos encontrados
- Campeonatos por categoria/país
- Lista de campeonatos importantes
- URLs para cada campeonato

## 🐛 Troubleshooting

### Nenhum campeonato encontrado

**Causa:** O site pode ter mudado a estrutura ou a API retornou erro 403.

**Solução:**
1. Salve os dados XHR manualmente do DevTools
2. Use `convert_xhr_to_json.py` para converter
3. Execute `map_tournaments.py` com o arquivo JSON

### Erro 403 ao buscar via API

**Causa:** A API está bloqueando requisições não autenticadas.

**Solução:**
- Use dados XHR salvos manualmente
- Ou use o fallback HTML scraping (mais lento mas funciona)

## 📚 Arquivos Relacionados

- `scraping/tournaments.py` - Funções de busca e parseamento
- `scripts/map_tournaments.py` - Script principal de mapeamento
- `scripts/convert_xhr_to_json.py` - Conversor de dados XHR
- `API_XHR_INTEGRATION.md` - Documentação da API XHR

## 🔄 Atualização do Mapeamento

Recomenda-se atualizar o mapeamento periodicamente:

1. Novos campeonatos podem ser adicionados
2. IDs podem mudar
3. Categorias podem ser reorganizadas

Execute `map_tournaments.py` sempre que:
- Houver mudanças no site
- Novos campeonatos aparecerem
- Antes de fazer scraping em massa

