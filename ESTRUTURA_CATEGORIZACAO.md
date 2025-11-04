# 📊 Como a BetNacional Categoriza os Campeonatos

## 🏗️ Estrutura Hierárquica

A BetNacional organiza os campeonatos em uma hierarquia de 4 níveis:

```
1. Esporte (sport_id)
   ↓
2. Continente (continent_name) - opcional
   ↓
3. Categoria/País (category_id, category_name)
   ↓
4. Campeonato (tournament_id, tournament_name)
```

### Exemplo Prático:

```
sport_id: 1 (Futebol)
  └─ continent_name: "Europa"
      └─ category_id: 32, category_name: "Espanha"
          └─ tournament_id: 8, tournament_name: "LaLiga"
```

## 📋 Níveis de Categorização

### 1. Esporte (sport_id)

- **sport_id = 1**: Futebol (todos os campeonatos mapeados são de futebol)
- Outros esportes podem ter outros IDs (ex: 2 = Basquete, 5 = Tênis)

### 2. Continente (continent_name)

**Opcional** - Pode ser `null` para muitos campeonatos

Os continentes identificados nos dados:
- **"Europa"**: 13 campeonatos em 4 categorias
- **"Américas"**: 5 campeonatos em 2 categorias
- **null**: Maioria dos campeonatos não tem continente atribuído

### 3. Categoria/País (category_id, category_name)

**Este é o nível principal de organização**

- **category_id**: ID numérico único da categoria/país
- **category_name**: Nome do país ou categoria (ex: "Brasil", "Espanha", "Clubes Internacionais")

**Total de categorias/paises: 73**

#### Top Categorias com Mais Campeonatos:

1. **Itália** (ID: 31) - 9 campeonatos
2. **Alemanha** (ID: 30) - 9 campeonatos (incluindo variantes)
3. **Inglaterra Amadores** (ID: 252) - 7 campeonatos
4. **Escócia** (ID: 22) - 6 campeonatos
5. **Dinamarca** (ID: 8) - 5 campeonatos
6. **Internacional** (ID: 4) - 5 campeonatos
7. **República Checa** (ID: 18) - 4 campeonatos
8. **Rússia** (ID: 21) - 4 campeonatos
9. **Clubes Internacionais** (ID: 393) - 4 campeonatos
10. **Argentina** (ID: 48) - 4 campeonatos

#### Categorias Especiais:

- **category_id = 393**: "Clubes Internacionais"
  - Champions League
  - Europa League
  - Conference League
  - Libertadores
  - Copa Sul-Americana
  - AFC Champions League

- **category_id = 4**: "Internacional"
  - Copa do Mundo
  - Eliminatórias
  - Amistosos Internacionais
  - Copa das Nações Africanas

- **category_id = 252**: "Inglaterra Amadores"
  - Ligas não profissionais inglesas

- **category_id = 122**: "Alemanha Amadores"
  - Ligas femininas e amadoras

### 4. Campeonato (tournament_id, tournament_name)

- **tournament_id**: ID único do campeonato
- **tournament_name**: Nome completo do campeonato
- **is_important**: Flag booleana indicando se é destacado

## 🔗 Estrutura de URLs

A URL segue o padrão:

```
https://betnacional.bet.br/events/{sport_id}/{category_id}/{tournament_id}
```

### Exemplos:

- **Brasileirão Série A**:
  - URL: `https://betnacional.bet.br/events/1/13/325`
  - sport_id: 1, category_id: 13 (Brasil), tournament_id: 325

- **Champions League**:
  - URL: `https://betnacional.bet.br/events/1/393/7`
  - sport_id: 1, category_id: 393 (Clubes Internacionais), tournament_id: 7

- **Premier League**:
  - URL: `https://betnacional.bet.br/events/1/1/17`
  - sport_id: 1, category_id: 1 (Inglaterra), tournament_id: 17

## ⚠️ Casos Especiais

### 1. Campeonatos sem category_name

Alguns campeonatos importantes têm `category_name` vazio (string vazia):

- Alemanha - Bundesliga (ID: 35)
- Brasileirão Série A (ID: 325)
- Brasileirão Série B (ID: 390)
- Espanha - LaLiga (ID: 8)
- Inglaterra - Championship (ID: 18)
- Inglaterra - Premier League (ID: 17)
- UEFA Champions League (ID: 7)
- UEFA Conference League (ID: 34480)
- UEFA Europa League (ID: 679)

**Observação**: Esses campeonatos ainda têm `category_id`, mas o `category_name` está vazio. Provavelmente são destacados na interface principal.

### 2. Campeonatos Importantes (is_important = true)

8 campeonatos são marcados como importantes:
- Todos os campeonatos listados acima (sem category_name)
- São os principais campeonatos destacados na plataforma

### 3. category_id = 0

Na URL da API XHR, alguns campeonatos podem usar `category_id = 0` para indicar "todas as categorias":
- Exemplo: `https://betnacional.bet.br/events/1/0/7` (Champions League)

## 📊 Estatísticas

- **Total de campeonatos mapeados**: 163
- **Total de categorias/paises**: 73
- **Total de continentes identificados**: 2 (Europa, Américas)
- **Campeonatos importantes**: 8
- **Campeonatos sem category_name**: 9

## 🎯 Como Usar na Prática

### Buscar campeonatos por país:

```python
from scraping.tournaments import get_tournaments_by_category

# Buscar todos os campeonatos do Brasil (category_id = 13)
brasileiros = get_tournaments_by_category(13)
```

### Buscar campeonato específico:

```python
from scraping.tournaments import get_tournament_by_id

# Buscar Champions League (tournament_id = 7)
champions = get_tournament_by_id(7)
```

### Construir URL:

```python
def build_tournament_url(sport_id: int, category_id: int, tournament_id: int) -> str:
    return f"https://betnacional.bet.br/events/{sport_id}/{category_id}/{tournament_id}"

# Exemplo: Brasileirão
url = build_tournament_url(1, 13, 325)
# Resultado: https://betnacional.bet.br/events/1/13/325
```

## 📝 Observações Importantes

1. **category_id é obrigatório** na URL, mesmo que `category_name` esteja vazio
2. **continent_name é opcional** e pode ser `null`
3. **Campeonatos importantes** geralmente têm `category_name` vazio
4. **category_id = 393** é usado para competições internacionais de clubes
5. **category_id = 4** é usado para competições internacionais de seleções
6. A estrutura permite múltiplos campeonatos por país (ex: Série A, Série B, Copa)

## 🔍 Mapeamento de IDs Importantes

### Países Principais:

- **Brasil**: category_id = 13
- **Inglaterra**: category_id = 1
- **Espanha**: category_id = 32
- **Itália**: category_id = 31
- **Alemanha**: category_id = 30
- **França**: category_id = 7
- **Portugal**: category_id = 44
- **Argentina**: category_id = 48

### Categorias Especiais:

- **Clubes Internacionais**: category_id = 393
- **Internacional (Seleções)**: category_id = 4
- **Inglaterra Amadores**: category_id = 252
- **Alemanha Amadores**: category_id = 122

