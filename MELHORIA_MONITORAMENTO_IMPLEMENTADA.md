# ✅ Melhoria #7 Implementada: Monitoramento e Alertas

## 📋 O Que Foi Implementado

Implementada a **Melhoria #7** do documento `MELHORIAS_PRIORITARIAS.md`: **Monitoramento e Alertas**.

## 🔧 Mudanças Realizadas

### 1. **Criado Sistema de Health Checks**

**Arquivo:** `utils/health_check.py` (NOVO)

**Classe:** `SystemHealth`

**Funcionalidades:**

#### A. `check_api_health()`
Verifica se a API do Betnacional está respondendo.

**Verificações:**
- ✅ Testa chamada à API com campeonato conhecido (UEFA Champions League)
- ✅ Verifica se API retorna dados válidos
- ✅ Verifica tempo de resposta (alerta se > 10s)

**Retorna:**
- `(True, None)` se saudável
- `(False, error_message)` se houver problema

#### B. `check_db_health()`
Verifica se o banco de dados está acessível e funcionando.

**Verificações:**
- ✅ Testa query simples (`SELECT COUNT(*)`)
- ✅ Testa query com filtro usando índice (`WHERE status = 'live'`)
- ✅ Verifica tempo de resposta (alerta se > 2s)

**Retorna:**
- `(True, None)` se saudável
- `(False, error_message)` se houver problema

#### C. `check_telegram_health()`
Verifica se o Telegram está funcionando.

**Verificações:**
- ✅ Verifica se TOKEN e CHAT_ID estão configurados
- ✅ Testa conexão com API do Telegram (`getMe`)
- ✅ Não envia mensagem de teste (apenas verifica conectividade)

**Retorna:**
- `(True, None)` se saudável
- `(False, error_message)` se houver problema

#### D. `check_all()`
Executa todos os health checks e retorna resultado consolidado.

**Retorna:**
```python
{
    "timestamp": datetime,
    "api": {"healthy": bool, "error": str|None},
    "database": {"healthy": bool, "error": str|None},
    "telegram": {"healthy": bool, "error": str|None},
    "overall": bool  # True se todos estão saudáveis
}
```

### 2. **Sistema de Alertas com Cooldown**

**Funcionalidades:**

#### A. Cooldown de Alertas
- ✅ Previne spam de alertas (30 minutos entre alertas do mesmo tipo)
- ✅ Evita notificações excessivas durante problemas persistentes

#### B. Tipos de Alerta
- **Critical** (🔴): Para API e Banco de Dados
- **Warning** (⚠️): Para Telegram

#### C. Notificação de Recuperação
- ✅ Envia mensagem quando sistema se recupera
- ✅ Informa que todos os componentes estão funcionando novamente

**Exemplo de Alerta:**
```
🔴 ALERTA DE SAÚDE DO SISTEMA

Componente: API do Betnacional
Severidade: CRÍTICO
Erro: API retornou None

Verifique o sistema imediatamente.
```

**Exemplo de Recuperação:**
```
✅ SISTEMA RECUPERADO

Todos os componentes estão funcionando normalmente novamente.
```

### 3. **Integração com Scheduler**

**Arquivo:** `scheduler/jobs.py`

**Função:** `health_check_job()`

**Agendamento:**
- ✅ Executa a cada 30 minutos
- ✅ Automaticamente envia alertas se necessário
- ✅ Loga status detalhado em modo debug

**Configuração:**
```python
scheduler.add_job(
    health_check_job,
    trigger=IntervalTrigger(minutes=30),
    id="health_check",
    replace_existing=True,
    coalesce=True,
    max_instances=1,
    misfire_grace_time=300,
)
```

## 📊 Benefícios

### 1. **Observabilidade Melhorada**
- ✅ Sistema monitora sua própria saúde automaticamente
- ✅ Identifica problemas antes que afetem usuários
- ✅ Logs detalhados para troubleshooting

### 2. **Alertas Proativos**
- ✅ Notificações imediatas quando problemas críticos ocorrem
- ✅ Cooldown previne spam de alertas
- ✅ Notificação de recuperação quando sistema volta ao normal

### 3. **Detecção Rápida de Problemas**
- ✅ Problemas detectados em até 30 minutos
- ✅ Alertas críticos para componentes essenciais
- ✅ Alertas de warning para componentes não críticos

### 4. **Manutenibilidade**
- ✅ Código centralizado para health checks
- ✅ Fácil adicionar novos checks
- ✅ Configurável (cooldown, intervalos, etc)

## 🧪 Como Funciona

### Fluxo de Health Check

```
1. Job agendado executa a cada 30 minutos
   ↓
2. Executa todos os health checks
   - API
   - Banco de Dados
   - Telegram
   ↓
3. Verifica resultados
   ├─ Se saudável → Log apenas
   └─ Se problema → Verifica cooldown
       ↓
4. Se cooldown expirado → Envia alerta
   ↓
5. Se sistema recuperou → Envia notificação de recuperação
```

### Exemplo de Uso Manual

```python
from utils.health_check import system_health

# Executa todos os checks
results = system_health.check_all()

# Verifica status específico
api_ok, api_error = system_health.check_api_health()

# Obtém resumo textual
summary = system_health.get_status_summary()
# "✅ API | ✅ DATABASE | ✅ TELEGRAM"
```

### Cooldown de Alertas

**Problema:** Sistema com API instável envia alerta a cada 30 minutos
**Solução:** Cooldown de 30 minutos previne alertas repetidos

```python
# Primeira falha
system_health.send_alert("api", "API não responde")
# ✅ Alerta enviado

# Falha 10 minutos depois
system_health.send_alert("api", "API não responde")
# ❌ Alerta ignorado (cooldown)

# Falha 35 minutos depois (cooldown expirado)
system_health.send_alert("api", "API não responde")
# ✅ Alerta enviado novamente
```

## 📈 Impacto Esperado

### Antes (Sem Monitoramento)
```
❌ Problema na API → Detectado apenas quando usuário reporta
❌ Banco lento → Detectado apenas quando queries falham
❌ Telegram offline → Detectado apenas quando mensagem falha
❌ Sem alertas automáticos
```

### Depois (Com Monitoramento)
```
✅ Problema na API → Detectado em até 30 minutos → Alerta imediato
✅ Banco lento → Detectado em até 30 minutos → Alerta imediato
✅ Telegram offline → Detectado em até 30 minutos → Alerta de warning
✅ Alertas automáticos via Telegram
✅ Notificação de recuperação quando sistema volta ao normal
```

**Benefícios:**
- ✅ **Detecção proativa** de problemas
- ✅ **Redução de ~80%** no tempo de resposta a problemas (estimado)
- ✅ **Melhor experiência** do usuário

## ⚙️ Configuração

### Ajustar Intervalo de Health Checks

**Padrão:** 30 minutos

Para alterar:
```python
# scheduler/jobs.py
scheduler.add_job(
    health_check_job,
    trigger=IntervalTrigger(minutes=15),  # A cada 15 minutos
    ...
)
```

### Ajustar Cooldown de Alertas

**Padrão:** 30 minutos

Para alterar:
```python
# utils/health_check.py
system_health.cooldown_minutes = 60  # 1 hora
```

### Adicionar Novos Health Checks

```python
# utils/health_check.py
class SystemHealth:
    def check_new_component(self) -> Tuple[bool, Optional[str]]:
        try:
            # Verificação do novo componente
            return (True, None)
        except Exception as e:
            return (False, str(e))
    
    def check_all(self):
        # Adicionar novo check
        new_healthy, new_error = self.check_new_component()
        results["new_component"] = {
            "healthy": new_healthy,
            "error": new_error
        }
```

## 📊 Estrutura de Health Checks

### Componentes Monitorados

| Componente | Tipo | Criticidade | Verificação |
|-----------|------|-------------|--------------|
| API Betnacional | External | Crítico | Chamada de teste + tempo |
| Banco de Dados | Internal | Crítico | Query simples + query com índice |
| Telegram | External | Warning | getMe + configuração |

### Métricas Coletadas

- ✅ Tempo de resposta (API, DB)
- ✅ Status de conectividade
- ✅ Erros e exceções
- ✅ Timestamp do último check

## 🔄 Funcionamento

### Health Check Job

```python
async def health_check_job():
    # Executa todos os checks
    results = system_health.check_and_alert()
    
    # Log resumo
    if results["overall"]:
        logger.debug("✅ Sistema saudável")
    else:
        logger.warning("⚠️ Sistema com problemas")
```

### Sistema de Alertas

```python
def check_and_alert():
    # Executa checks
    results = self.check_all()
    
    # Verifica cada componente
    if not results["api"]["healthy"]:
        self.send_alert("api", error, "critical")
    
    # Se recuperou, notifica
    if results["overall"] and had_issues_before:
        send_recovery_notification()
```

## ✅ Status

**IMPLEMENTADO E PRONTO PARA USO**

O sistema agora:
- ✅ Monitora saúde dos componentes automaticamente
- ✅ Envia alertas quando problemas críticos ocorrem
- ✅ Notifica quando sistema se recupera
- ✅ Previne spam de alertas com cooldown
- ✅ Executa health checks a cada 30 minutos

---

**Implementação concluída em:** 2025-11-04

**Arquivos criados/modificados:**
- `utils/health_check.py` (NOVO) - Sistema de health checks
- `scheduler/jobs.py` - Integração com scheduler

