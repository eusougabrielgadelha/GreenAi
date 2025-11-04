# 🔧 Solução para Erro 403 na API XHR

## Problema

O erro `403 Forbidden` ocorre quando a API bloqueia a requisição porque:
1. **Falta de cookies/sessão**: A API pode exigir cookies de autenticação
2. **Headers incompletos**: Alguns headers podem estar faltando
3. **Rate limiting**: Muitas requisições do mesmo IP
4. **Validação de origem**: A API pode estar validando a origem da requisição

## ✅ Soluções Implementadas

### 1. Headers Melhorados

Atualizei os headers para incluir:
- ✅ `Accept-Encoding`: gzip, deflate, br
- ✅ `Origin`: https://betnacional.bet.br
- ✅ `sec-fetch-*`: Headers de segurança do navegador
- ✅ `Connection`: keep-alive
- ✅ `Cache-Control`: no-cache

### 2. Fallback Automático

O sistema já tem fallback automático para HTML scraping se a API retornar erro 403.

## 🔄 Comportamento Atual

Quando ocorre 403:
1. ❌ Tenta API XHR → Recebe 403
2. ✅ Faz fallback automático para HTML scraping
3. ✅ Continua funcionando normalmente

## 💡 Soluções Adicionais (Opcionais)

### Opção 1: Usar Playwright (Recomendado para contornar 403)

Se você tiver Playwright instalado, pode fazer uma requisição prévia para obter cookies:

```python
# Exemplo de como obter cookies com Playwright
from playwright.async_api import async_playwright

async def get_cookies_from_browser():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://betnacional.bet.br/events/1/0/7")
        cookies = await context.cookies()
        await browser.close()
        return cookies
```

### Opção 2: Fazer Requisição Prévia

Fazer uma requisição GET na página principal antes de chamar a API:

```python
# Primeiro acessar a página principal para obter cookies
session = requests.Session()
session.get("https://betnacional.bet.br/events/1/0/7", headers=headers)
# Depois usar a session para chamar a API
response = session.get(api_url, params=params, headers=headers)
```

### Opção 3: Aceitar o Fallback (Atual)

O sistema já funciona com fallback HTML. Se a API não funcionar, o HTML scraping continua funcionando normalmente.

## 📊 Status Atual

✅ **Sistema Funcional**: O fallback HTML garante que o sistema continue funcionando mesmo com 403 na API

⚠️ **API XHR**: Pode retornar 403, mas o sistema faz fallback automaticamente

## 🔍 Como Verificar

### Ver logs para confirmar fallback

```bash
pm2 logs betauto | grep -E "(API|fallback|HTML)"
```

Você deve ver:
```
📡 Tentando buscar via API XHR...
⚠️  Erro ao buscar via API XHR: 403...
🌐 Fallback para HTML scraping — backend=requests
🧮 → eventos extraídos via HTML: X
```

### Testar manualmente

```python
# Testar se a API funciona
import requests

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://betnacional.bet.br/',
    'Origin': 'https://betnacional.bet.br',
}

response = requests.get(
    'https://prod-global-bff-events.bet6.com.br/api/odds/1/events-by-seasons',
    params={'sport_id': '1', 'category_id': '0', 'tournament_id': '7', 'markets': '1'},
    headers=headers
)
print(response.status_code)  # Se 403, API bloqueou
```

## 🎯 Recomendação

**Por enquanto, deixe o sistema usar o fallback HTML**. O scraping HTML funciona normalmente e:

- ✅ Já está implementado e testado
- ✅ Funciona mesmo com 403 na API
- ✅ Não requer configuração adicional
- ✅ É mais confiável a longo prazo

Se a API começar a funcionar (talvez por mudanças no servidor), o sistema automaticamente usará a API primeiro.

---

**O sistema está funcionando corretamente com fallback HTML!**

