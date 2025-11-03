# 📋 Análise de Arquivos Não Utilizados

Relatório de arquivos que não estão sendo usados no projeto atual.

## ❌ Arquivos Não Utilizados (Podem ser Removidos)

### 1. **`main_old.py`** (114.515 bytes)
- **Status**: ❌ **NÃO UTILIZADO**
- **Descrição**: Backup do código original antes da modularização
- **Data**: 20/09/2025
- **Motivo**: Código monolítico antigo, substituído pela versão modular
- **Ação recomendada**: ⚠️ **Pode ser deletado** (faça backup primeiro se quiser manter histórico)

### 2. **`main_new.py`** (15.069 bytes)
- **Status**: ❌ **NÃO UTILIZADO**
- **Descrição**: Versão intermediária de refatoração
- **Data**: 03/11/2025 19:03:52
- **Motivo**: Versão anterior do `main.py` atual. O `main.py` atual (18.709 bytes) é mais completo e tem melhor tratamento de erros
- **Diferenças**: O `main.py` atual tem:
  - Tratamento de erros melhorado na função `main()`
  - Shutdown gracioso do scheduler
  - Melhor logging e tratamento de exceções
  - Exit codes corretos para systemd
- **Ação recomendada**: ⚠️ **Pode ser deletado** (já foi substituído por `main.py`)

### 3. **`tomorrow.py`** (113.008 bytes)
- **Status**: ⚠️ **PENDENTE DE MODULARIZAÇÃO**
- **Descrição**: Arquivo monolítico separado que ainda não foi integrado ao sistema modular
- **Data**: 20/09/2025 18:46:01
- **Motivo**: Foi mencionado que deveria ser modularizado, mas ainda não foi feito
- **Ação recomendada**: 
  - 📝 **Manter por enquanto** até ser modularizado
  - 🔄 Ou modularizar e depois remover

## ✅ Arquivos em Uso (NÃO REMOVER)

### Arquivos Principais
- ✅ `main.py` - Ponto de entrada principal (ATIVO)
- ✅ `requirements.txt` - Dependências do projeto
- ✅ `README.md` - Documentação principal
- ✅ `DEPLOY.md` - Guia de deploy
- ✅ `betauto.service` - Configuração systemd
- ✅ `setup.sh` - Script de instalação

### Módulos Ativos
- ✅ `config/` - Configurações
- ✅ `models/` - Modelos de banco de dados
- ✅ `scraping/` - Lógica de scraping
- ✅ `betting/` - Lógica de apostas
- ✅ `scheduler/` - Jobs agendados
- ✅ `notifications/` - Notificações Telegram
- ✅ `utils/` - Utilitários
- ✅ `watchlist/` - Gerenciamento de watchlist
- ✅ `live/` - Monitoramento de jogos ao vivo

## 📊 Resumo

| Arquivo | Tamanho | Status | Ação Recomendada |
|---------|---------|--------|------------------|
| `main_old.py` | 114 KB | ❌ Não usado | ⚠️ Pode deletar |
| `main_new.py` | 15 KB | ❌ Não usado | ⚠️ Pode deletar |
| `tomorrow.py` | 113 KB | ⚠️ Pendente | 📝 Manter até modularizar |

**Total de espaço potencialmente liberado**: ~242 KB (se remover `main_old.py` e `main_new.py`)

## 🔧 Comandos para Limpeza

### Remover arquivos não utilizados (CUIDADO!)

```bash
# Fazer backup primeiro
mkdir -p backup
cp main_old.py backup/
cp main_new.py backup/

# Remover arquivos não utilizados
rm main_old.py
rm main_new.py
```

### Ou mover para uma pasta de backup

```bash
mkdir -p arquivos_antigos
mv main_old.py arquivos_antigos/
mv main_new.py arquivos_antigos/
```

## ⚠️ Avisos Importantes

1. **Faça backup antes de deletar** - Mesmo que não estejam sendo usados, podem conter código útil para referência
2. **`tomorrow.py`** - Não deletar ainda, pois ainda precisa ser modularizado
3. **Verifique dependências** - Antes de deletar, certifique-se de que nenhum script ou documentação referencia esses arquivos



