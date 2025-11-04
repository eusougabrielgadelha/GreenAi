# 📋 Como Obter Dados XHR Completos para Mapeamento

## 🎯 Objetivo

Para mapear todos os campeonatos de futebol, precisamos do JSON completo da resposta XHR.

## ✅ Método Recomendado: Copiar JSON Completo

### Passo a Passo:

1. **Abra o DevTools** (F12)
2. **Vá para a aba Network** (Rede)
3. **Filtre por XHR** ou **Fetch/XHR**
4. **Acesse**: https://betnacional.bet.br/sports/1
5. **Encontre a requisição** que retorna dados de campeonatos
   - Procure por requisições para `bet6.com.br` ou similares
   - Ou procure por requisições que contenham "tournaments", "sports", etc.
6. **Clique na requisição**
7. **Vá para a aba Response**
8. **Clique com botão direito** no conteúdo JSON
9. **Selecione "Copy response"** ou "Copy response body"
10. **Cole em um arquivo** `data/xhr_tournaments_raw.json`
11. **Execute**:
    ```bash
    python scripts/map_tournaments.py data/xhr_tournaments_raw.json
    ```

## 🔍 Alternativa: Usar o Arquivo Fornecido

Se você já tem o arquivo `sports xhr.txt` no formato expandido do DevTools:

```bash
# Tentar processar (pode não pegar todos os campeonatos)
python scripts/parse_xhr_advanced.py "caminho/para/sports xhr.txt" data/xhr_tournaments.json

# Gerar mapeamento
python scripts/map_tournaments.py data/xhr_tournaments.json
```

**Nota**: O parser pode não extrair todos os campeonatos do formato expandido. 
Para resultado completo, use o método de copiar o JSON completo.

## 📝 Exemplo de JSON Esperado

O JSON deve ter esta estrutura:

```json
{
  "importants": [
    {
      "sport_id": 1,
      "category_id": 393,
      "tournament_id": 7,
      "tournament_name": "UEFA Champions League",
      "season_id": 131129
    },
    ...
  ],
  "tourneys": [
    {
      "sport_id": 1,
      "category_id": 13,
      "category_name": "Brasil",
      "tournament_id": 325,
      "tournament_name": "Brasileirão Série A",
      "season_id": 0
    },
    ...
  ]
}
```

## 🚀 Após Obter o JSON

Execute o script de mapeamento:

```bash
python scripts/map_tournaments.py data/xhr_tournaments_raw.json
```

Isso irá:
- ✅ Processar todos os campeonatos
- ✅ Gerar arquivos JSON, CSV e Python
- ✅ Exibir resumo formatado
- ✅ Criar mapeamento completo para uso no código

