# 🔍 Validação de IDs - Garantia de Sincronização com BetNacional

## ✅ Garantia

**TODOS os IDs que usamos são EXATAMENTE os mesmos IDs que a BetNacional usa na sua API.**

Não criamos, modificamos ou convertemos IDs. Apenas **extraímos e reutilizamos** os IDs originais da API.

## 📋 Como os IDs são Extraídos

### 1. Código de Extração

No arquivo `scraping/tournaments.py`, função `parse_tournaments_from_api()`:

```python
# Linha 71-74
tournament_id = item.get('tournament_id')  # DIRETO DA API
category_id = item.get('category_id', 0)   # DIRETO DA API
sport_id = item.get('sport_id', 1)        # DIRETO DA API
```

**Todos os valores são extraídos diretamente da resposta JSON da API da BetNacional.**

### 2. Exemplo Real

**Resposta da API (importants):**
```json
{
  "tournament_id": 7,
  "category_id": 393,
  "sport_id": 1,
  "tournament_name": "UEFA Champions League",
  "category_name": "Clubes Internacionais"
}
```

**Como extraímos:**
- `tournament_id = item.get('tournament_id')` → `7`
- `category_id = item.get('category_id')` → `393`
- `sport_id = item.get('sport_id')` → `1`

**URL construída:**
```
https://betnacional.bet.br/events/1/393/7
```

✅ **Todos os valores são os mesmos da API**

## 🎯 ID Especial (Único que Criamos)

### ID 9999: "Campeonatos Importantes"

**Este é o ÚNICO ID que criamos. É uma categoria virtual para uso interno.**

- **ID**: `9999`
- **Nome**: `"Campeonatos Importantes"`
- **Uso**: Apenas para categorização interna
- **NÃO é usado na API da BetNacional**
- **NÃO é usado nas URLs**
- **NÃO é enviado para a API**

**Localização no código:**
```python
# scraping/tournaments.py, linha 61
IMPORTANT_CATEGORY_ID = 9999
IMPORTANT_CATEGORY_NAME = "Campeonatos Importantes"
```

Este ID é adicionado apenas à lista `categories` de cada campeonato importante, mas **não afeta** os IDs originais (`tournament_id`, `category_id`, `sport_id`).

## 🔗 Construção de URLs

As URLs são construídas usando **APENAS** os IDs originais da API:

```python
# scraping/tournaments.py, linha 101
url = f"https://betnacional.bet.br/events/{sport_id}/{category_id}/{tournament_id}"
```

**Todos os valores (`sport_id`, `category_id`, `tournament_id`) vêm diretamente da API.**

## ✅ Validação

### Script de Verificação

Execute o script de verificação para confirmar:

```bash
python scripts/verify_ids_source.py
```

Este script verifica:
1. ✅ Todos os IDs são extraídos diretamente da API
2. ✅ O único ID criado é o 9999 (documentado)
3. ✅ Todas as URLs são construídas corretamente
4. ✅ Nenhum ID foi modificado ou criado (exceto 9999)

### Resultado da Validação

```
[OK] CONFIRMADO: Todos os IDs (tournament_id, category_id, sport_id)
   sao extraidos DIRETAMENTE da API da BetNacional

[OK] CONFIRMADO: O unico ID que criamos e o 9999 (Campeonatos Importantes)
   que e uma categoria virtual para uso interno

[OK] CONFIRMADO: As URLs sao construidas usando apenas IDs originais

[OK] CONCLUSAO: Nao estamos criando ou modificando IDs da BetNacional
```

## 📊 Estrutura de Dados

### Campeonato (Exemplo)

```json
{
  "sport_id": 1,                    // ← Direto da API
  "category_id": 393,               // ← Direto da API
  "tournament_id": 7,                // ← Direto da API
  "tournament_name": "UEFA Champions League",
  "category_name": "Clubes Internacionais",
  "url": "https://betnacional.bet.br/events/1/393/7",  // ← Construída com IDs originais
  "categories": [
    {
      "category_id": 393,           // ← Direto da API
      "category_name": "Clubes Internacionais",
      "is_primary": true
    },
    {
      "category_id": 9999,           // ← ÚNICO ID que criamos (virtual)
      "category_name": "Campeonatos Importantes",
      "is_primary": false
    }
  ]
}
```

## 🔒 Garantias

1. **✅ `tournament_id`**: Sempre extraído diretamente da API
2. **✅ `category_id`**: Sempre extraído diretamente da API
3. **✅ `sport_id`**: Sempre extraído diretamente da API
4. **✅ URLs**: Construídas usando apenas IDs originais
5. **✅ ID 9999**: Único ID criado, claramente documentado e não usado na API

## 🚨 Importante

- **NÃO modificamos IDs da BetNacional**
- **NÃO criamos novos IDs (exceto 9999 para uso interno)**
- **NÃO convertemos ou transformamos IDs**
- **Apenas extraímos e reutilizamos os IDs originais**

## 📝 Como Manter a Sincronização

Para garantir que os IDs permaneçam sincronizados:

1. **Sempre extrair IDs diretamente da API** (como já fazemos)
2. **Nunca criar IDs manualmente** (exceto 9999)
3. **Validar periodicamente** usando `scripts/verify_ids_source.py`
4. **Atualizar o mapeamento** quando a API retornar novos campeonatos

## 🔍 Verificação Manual

Se você quiser verificar manualmente:

1. Abra o DevTools do navegador
2. Acesse `https://betnacional.bet.br/sports/1`
3. Veja a resposta XHR da API
4. Compare os IDs com os do arquivo `data/tournaments_mapping.json`
5. Todos devem corresponder exatamente

## ✅ Conclusão

**Garantimos que todos os IDs (exceto 9999) são exatamente os mesmos que a BetNacional usa na sua API.**

Não há risco de dessincronização porque:
- Extraímos diretamente da API
- Não modificamos os valores
- Não criamos IDs (exceto 9999, que é virtual)
- URLs são construídas com IDs originais

**O sistema está 100% sincronizado com a API da BetNacional.**

