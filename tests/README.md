# Testes Unitários

Este diretório contém os testes unitários do projeto BetAuto/GreenAi.

## Estrutura

```
tests/
├── __init__.py
├── conftest.py          # Configuração global do pytest
├── test_scraping_betnacional.py  # Testes de scraping
├── test_validators.py            # Testes de validação
├── test_cache.py                 # Testes de cache
├── test_rate_limiter.py          # Testes de rate limiting
└── test_decision.py              # Testes de lógica de decisão
```

## Executando os Testes

### Instalar dependências

```bash
pip install -r requirements.txt
```

### Executar todos os testes

```bash
pytest
```

### Executar testes específicos

```bash
# Testes de scraping
pytest tests/test_scraping_betnacional.py

# Testes de validação
pytest tests/test_validators.py

# Teste específico
pytest tests/test_validators.py::TestValidateOdds::test_valid_odds
```

### Executar com verbose

```bash
pytest -v
```

### Executar com coverage

```bash
pip install pytest-cov
pytest --cov=. --cov-report=html
```

## Adicionando Novos Testes

1. Crie um novo arquivo `test_*.py` no diretório `tests/`
2. Importe as funções que deseja testar
3. Crie classes `Test*` com métodos `test_*`
4. Use `assert` para verificar resultados

Exemplo:

```python
"""Testes para meu módulo."""
import pytest
from meu_modulo import minha_funcao


class TestMinhaFuncao:
    """Testes para minha_funcao."""
    
    def test_valid_input(self):
        """Testa entrada válida."""
        result = minha_funcao("input")
        assert result == "expected"
    
    def test_invalid_input(self):
        """Testa entrada inválida."""
        result = minha_funcao("invalid")
        assert result is None
```

## Testes Assíncronos

Para testar funções assíncronas, use `@pytest.mark.asyncio`:

```python
@pytest.mark.asyncio
async def test_async_function():
    result = await minha_funcao_async()
    assert result is not None
```

## Boas Práticas

1. **Um teste, uma verificação**: Cada teste deve verificar uma coisa
2. **Nomes descritivos**: Use nomes que expliquem o que está sendo testado
3. **Teste casos extremos**: Inclua testes para casos inválidos, limites, etc.
4. **Teste isolado**: Testes não devem depender uns dos outros
5. **Mocks quando necessário**: Use mocks para dependências externas (APIs, banco, etc.)

