# 📋 Listagem de Campeonatos da BetNacional

Este documento explica como usar o sistema de listagem de campeonatos de futebol disponíveis na BetNacional.

## 🎯 Objetivo

O script `scripts/list_competitions.py` lista **todos os campeonatos de futebol** disponíveis na BetNacional, combinando:

1. **Campeonatos extraídos do site** (página `/sports/1`)
2. **Campeonatos configurados** em `config/settings.py`

## 🚀 Como Usar

### Executar o Script

```bash
python scripts/list_competitions.py
```

### Saída Esperada

O script irá:
1. Buscar a página de campeonatos usando Playwright
2. Extrair campeonatos do HTML renderizado
3. Adicionar campeonatos conhecidos do `config/settings.py`
4. Remover duplicatas e ordenar por nome
5. Exibir lista completa formatada

**Exemplo de saída:**
```
🔍 Iniciando busca de campeonatos na BetNacional...

📋 Buscando campeonatos de futebol em: https://betnacional.bet.br/sports/1
⏳ Aguardando carregamento completo da página...
✅ HTML obtido (123456 caracteres)
📊 Encontrados 15 campeonato(s) no HTML
📚 Adicionando campeonatos configurados em config/settings.py...

============================================================
📋 TOTAL: 25 campeonato(s) encontrado(s)
============================================================

  1. Argentina - Série A (Argentina)
      ID: 30106
      URL: https://betnacional.bet.br/events/1/0/30106
      Esporte ID: 1

  2. Argentina - Série B (Argentina)
      ID: 703
      URL: https://betnacional.bet.br/events/1/0/703
      Esporte ID: 1

  ...
```

## 📁 Estrutura dos Arquivos

### `scripts/list_competitions.py`
Script principal que:
- Busca campeonatos da página web
- Combina com campeonatos configurados
- Remove duplicatas
- Exibe resultados formatados

### `scraping/competitions.py`
Módulo com funções de extração:
- `extract_competitions_from_html()`: Extrai campeonatos do HTML
- `extract_competition_from_event_html()`: Extrai campeonato de uma página de evento

## 🔍 Estratégias de Extração

O sistema usa múltiplas estratégias para encontrar campeonatos:

### 1. Extração do JSON `__NEXT_DATA__`
- Busca em `props.pageProps.initialState`
- Procura em `events.queries` e `cache.events.entities`
- Busca recursiva por estruturas que parecem campeonatos

### 2. Extração do HTML Renderizado
- Procura por links que apontam para campeonatos (`/sports/`, `/events/`)
- Extrai nomes e IDs das URLs

### 3. Elementos HTML Específicos
- Procura por classes CSS relacionadas a campeonatos
- Seletores: `[class*="league"]`, `[class*="competition"]`, etc.

### 4. Campeonatos Configurados
- Adiciona todos os campeonatos de `config/settings.py`
- Garante que campeonatos conhecidos sempre apareçam na lista

## 📊 Estrutura de Dados

Cada campeonato é representado como um dicionário:

```python
{
    "id": "325",                    # ID do campeonato/liga
    "name": "Brasileirão Série A",  # Nome do campeonato
    "url": "https://betnacional.bet.br/events/1/0/325",  # URL completa
    "sport_id": 1,                   # ID do esporte (1 = futebol)
    "country": "Brasil"              # País (se disponível)
}
```

## ⚙️ Configuração

### Campeonatos em `config/settings.py`

Os campeonatos configurados estão em `BETTING_LINKS`:

```python
BETTING_LINKS = {
    "UEFA Champions League": {
        "pais": "Europa",
        "campeonato": "UEFA Champions League",
        "link": "https://betnacional.bet.br/events/1/0/7"
    },
    # ...
}
```

### Adicionar Novos Campeonatos

1. Adicione à `BETTING_LINKS` em `config/settings.py`
2. Execute `scripts/list_competitions.py` para verificar
3. O campeonato será incluído automaticamente na lista

## 🐛 Troubleshooting

### Nenhum Campeonato Encontrado

**Causa:** O site pode ter mudado a estrutura HTML ou o JavaScript não carregou completamente.

**Solução:**
1. Verifique se o Playwright está instalado: `pip install playwright`
2. Aumente o `wait_time` em `scripts/list_competitions.py` (linha 34)
3. Verifique os logs para mais detalhes

### Campeonatos Duplicados

**Causa:** O mesmo campeonato foi encontrado em múltiplas fontes.

**Solução:** O script já remove duplicatas automaticamente por ID. Se ainda houver duplicatas, verifique se os IDs estão corretos.

### Erro de Importação

**Causa:** O Python não encontra os módulos do projeto.

**Solução:** Execute o script a partir do diretório raiz do projeto:
```bash
cd /caminho/para/GreenAi
python scripts/list_competitions.py
```

## 📝 Notas

- O script usa **Playwright** para renderizar JavaScript, então é necessário ter o Playwright instalado
- A busca pode levar alguns segundos devido ao carregamento da página
- Campeonatos são ordenados alfabeticamente por nome
- O script sempre mostra pelo menos os campeonatos configurados, mesmo se a extração do site falhar

## 🔗 Links Relacionados

- Documentação do projeto: `README.md`
- Configurações: `config/settings.py`
- Scraping: `scraping/betnacional.py`

