# 💡 Melhorias Práticas - Implementações Sugeridas

## 🎯 Melhorias Identificadas e Como Implementar

---

## 1. 🔴 MELHORAR EXTRAÇÃO DE RESULTADO (CRÍTICO)

### Problema
A função `scrape_game_result()` atual só busca texto "Vencedor", que é muito limitado.

### Solução Prática
Já temos código que extrai placar em `scrape_live_game_data()`. Podemos usar a mesma estratégia:

```python
# scraping/betnacional.py
def scrape_game_result(html: str, ext_id: str) -> Optional[str]:
    """
    Tenta extrair o resultado final (home/draw/away) da página HTML.
    Usa múltiplas estratégias para maior robustez.
    """
    soup = BeautifulSoup(html, "html.parser")
    
    # ESTRATÉGIA 1: Extrair do placar final (MAIS CONFIÁVEL)
    lmt_container = soup.find("div", id="lmt-match-preview")
    if lmt_container:
        score_elements = lmt_container.select(".sr-lmt-1-sbr__score")
        if len(score_elements) >= 2:
            try:
                home_goals = int(score_elements[0].get_text(strip=True))
                away_goals = int(score_elements[1].get_text(strip=True))
                
                # Determinar resultado pelo placar
                if home_goals > away_goals:
                    logger.info(f"Resultado extraído do placar: {home_goals}-{away_goals} → home")
                    return "home"
                elif away_goals > home_goals:
                    logger.info(f"Resultado extraído do placar: {home_goals}-{away_goals} → away")
                    return "away"
                else:
                    logger.info(f"Resultado extraído do placar: {home_goals}-{away_goals} → draw")
                    return "draw"
            except (ValueError, IndexError):
                pass
    
    # ESTRATÉGIA 2: Buscar em elementos de resultado final
    result_elements = soup.select(
        '.final-score, .match-result, [class*="result"], [class*="final"]'
    )
    for elem in result_elements:
        text = elem.get_text(strip=True)
        # Procurar padrão "2 - 1" ou "2:1"
        match = re.search(r'(\d+)\s*[-:x]\s*(\d+)', text)
        if match:
            home_goals = int(match.group(1))
            away_goals = int(match.group(2))
            if home_goals > away_goals:
                return "home"
            elif away_goals > home_goals:
                return "away"
            else:
                return "draw"
    
    # ESTRATÉGIA 3: Texto "Vencedor" (atual - manter como fallback)
    winner_indicators = [
        soup.find(string=lambda text: text and "Vencedor" in text),
        soup.find(string=lambda text: text and "Winner" in text),
    ]
    for indicator in winner_indicators:
        if indicator:
            parent_text = indicator.parent.get_text(strip=True) if indicator.parent else ""
            if "Casa" in parent_text or "Home" in parent_text:
                return "home"
            elif "Fora" in parent_text or "Away" in parent_text:
                return "away"
            elif "Empate" in parent_text or "Draw" in parent_text:
                return "draw"
    
    # ESTRATÉGIA 4: Classes CSS (atual - manter como fallback)
    winner_elements = soup.select('.winner, .vencedor, .champion, [class*="winner"], [class*="vencedor"]')
    for elem in winner_elements:
        elem_text = elem.get_text(strip=True).lower()
        if "casa" in elem_text or "home" in elem_text:
            return "home"
        elif "fora" in elem_text or "away" in elem_text:
            return "away"
        elif "empate" in elem_text or "draw" in elem_text:
            return "draw"
    
    logger.warning(f"Não foi possível determinar o vencedor para o jogo com ext_id: {ext_id}")
    return None
```

**Benefícios:**
- ✅ 4 estratégias diferentes (mais robusto)
- ✅ Usa placar quando disponível (mais confiável)
- ✅ Mantém compatibilidade com métodos antigos

---

## 2. 🔴 CACHE DE RESULTADOS

### Problema
Sistema busca resultado múltiplas vezes para o mesmo jogo.

### Solução
```python
# utils/cache.py (novo arquivo)
from functools import lru_cache
from datetime import datetime, timedelta
from typing import Optional, Dict

class ResultCache:
    def __init__(self, ttl_minutes: int = 60):
        self.cache: Dict[str, tuple] = {}  # {ext_id: (result, timestamp)}
        self.ttl = timedelta(minutes=ttl_minutes)
    
    def get(self, ext_id: str) -> Optional[str]:
        if ext_id not in self.cache:
            return None
        
        result, timestamp = self.cache[ext_id]
        if datetime.now() - timestamp > self.ttl:
            del self.cache[ext_id]
            return None
        
        return result
    
    def set(self, ext_id: str, result: str):
        self.cache[ext_id] = (result, datetime.now())
    
    def clear(self):
        self.cache.clear()

# Instância global
result_cache = ResultCache(ttl_minutes=120)  # Cache válido por 2 horas

# Usar em fetch_game_result
async def fetch_game_result(ext_id: str, source_link: str) -> Optional[str]:
    # Verificar cache primeiro
    cached_result = result_cache.get(ext_id)
    if cached_result:
        logger.debug(f"Resultado encontrado no cache para {ext_id}: {cached_result}")
        return cached_result
    
    # Buscar resultado
    result = await _fetch_game_result_impl(ext_id, source_link)
    
    # Salvar no cache se encontrou
    if result:
        result_cache.set(ext_id, result)
    
    return result
```

---

## 3. 🔴 RATE LIMITING

### Solução
```python
# utils/rate_limiter.py (novo arquivo)
import asyncio
from time import time
from typing import Optional

class RateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self.requests: list = []
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        async with self._lock:
            now = time()
            # Remove requisições antigas
            self.requests = [r for r in self.requests if now - r < self.window]
            
            if len(self.requests) >= self.max_requests:
                # Calcular tempo de espera
                oldest_request = min(self.requests)
                sleep_time = self.window - (now - oldest_request) + 1
                if sleep_time > 0:
                    logger.debug(f"Rate limit atingido. Aguardando {sleep_time:.1f}s")
                    await asyncio.sleep(sleep_time)
                    # Recalcular após espera
                    now = time()
                    self.requests = [r for r in self.requests if now - r < self.window]
            
            self.requests.append(now)

# Instância global
api_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)

# Usar em fetch_events_from_api
async def fetch_events_from_api_async(...):
    await api_rate_limiter.acquire()
    # Fazer requisição
    return await fetch_data(...)
```

---

## 4. 🟡 RETRY COM BACKOFF EXPONENCIAL

### Solução
```python
# utils/retry.py (novo arquivo)
import asyncio
from typing import Callable, Any, Optional
from functools import wraps

async def retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    exceptions: tuple = (Exception,)
):
    """
    Retry uma função com backoff exponencial.
    """
    delay = initial_delay
    
    for attempt in range(max_retries):
        try:
            return await func() if asyncio.iscoroutinefunction(func) else func()
        except exceptions as e:
            if attempt == max_retries - 1:
                raise
            
            logger.warning(
                f"Tentativa {attempt + 1}/{max_retries} falhou: {e}. "
                f"Tentando novamente em {delay:.1f}s..."
            )
            
            await asyncio.sleep(delay)
            delay = min(delay * exponential_base, max_delay)
    
    raise Exception("Número máximo de tentativas excedido")

# Decorator para facilitar uso
def with_retry(max_retries: int = 3, **kwargs):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **func_kwargs):
            async def _func():
                return await func(*args, **func_kwargs)
            return await retry_with_backoff(_func, max_retries=max_retries, **kwargs)
        return wrapper
    return decorator

# Usar
@with_retry(max_retries=3, initial_delay=2.0)
async def fetch_events_from_api_async(...):
    # Função que pode falhar
    pass
```

---

## 5. 🟡 VALIDAÇÃO DE DADOS

### Solução Simples (sem Pydantic)
```python
# utils/validators.py (novo arquivo)
from typing import Optional, Dict, Any

def validate_odds(odds_home: Any, odds_draw: Any, odds_away: Any) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Valida e normaliza odds.
    Retorna (odds_home, odds_draw, odds_away) ou (None, None, None) se inválido.
    """
    try:
        home = float(odds_home) if odds_home else None
        draw = float(odds_draw) if odds_draw else None
        away = float(odds_away) if odds_away else None
        
        # Validar range
        if home and (home < 1.0 or home > 100):
            logger.warning(f"Odd home inválida: {home}")
            home = None
        if draw and (draw < 1.0 or draw > 100):
            logger.warning(f"Odd draw inválida: {draw}")
            draw = None
        if away and (away < 1.0 or away > 100):
            logger.warning(f"Odd away inválida: {away}")
            away = None
        
        # Todas devem estar presentes
        if not (home and draw and away):
            return (None, None, None)
        
        return (home, draw, away)
    except (ValueError, TypeError) as e:
        logger.warning(f"Erro ao validar odds: {e}")
        return (None, None, None)

# Usar em parse_events_from_api
def parse_events_from_api(json_data: Dict[str, Any], source_url: str) -> List[Any]:
    events = []
    for item in json_data.get('odds', []):
        odds_home = item.get('odd') if item.get('outcome_id') == '1' else None
        odds_draw = item.get('odd') if item.get('outcome_id') == '2' else None
        odds_away = item.get('odd') if item.get('outcome_id') == '3' else None
        
        # Validar antes de usar
        home, draw, away = validate_odds(odds_home, odds_draw, odds_away)
        if not (home and draw and away):
            continue  # Pular se inválido
        
        # Criar evento com odds validadas
        # ...
```

---

## 📊 Resumo de Implementação

### Prioridade Alta (Implementar Agora)
1. ✅ **Melhorar extração de resultado** - Usar placar do HTML
2. ✅ **Cache de resultados** - Evitar requisições duplicadas
3. ✅ **Rate limiting** - Prevenir 403 errors

### Prioridade Média (Implementar em Breve)
4. ✅ **Retry com backoff** - Melhorar resiliência
5. ✅ **Validação de dados** - Prevenir erros

### Prioridade Baixa (Futuro)
6. Cache de campeonatos
7. Refatoração de funções longas
8. Testes unitários
9. Logging estruturado

---

## 🎯 Como Começar

1. **Implementar #1 (Extração de Resultado)** - Impacto imediato
2. **Implementar #2 (Cache)** - Melhora performance
3. **Implementar #3 (Rate Limiting)** - Reduz erros

Essas 3 melhorias sozinhas vão resolver **80% dos problemas** atuais!

