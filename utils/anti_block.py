"""
Estratégias anti-bloqueio para evitar 403 Forbidden em requisições XHR.
"""
import random
import time
from typing import Dict, Optional
from requests import Session
from utils.logger import logger


class UserAgentRotator:
    """Rotaciona User-Agents para simular diferentes navegadores."""
    
    USER_AGENTS = [
        # Chrome no Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        
        # Chrome no Linux
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        
        # Firefox no Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
        
        # Edge no Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
        
        # Safari no macOS
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
    ]
    
    def __init__(self):
        self.current_index = 0
    
    def get_random(self) -> str:
        """Retorna um User-Agent aleatório."""
        return random.choice(self.USER_AGENTS)
    
    def get_next(self) -> str:
        """Retorna o próximo User-Agent em sequência."""
        ua = self.USER_AGENTS[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.USER_AGENTS)
        return ua


# Instância global do rotador
user_agent_rotator = UserAgentRotator()


def get_browser_headers(user_agent: Optional[str] = None, referer: str = "https://betnacional.bet.br/") -> Dict[str, str]:
    """
    Gera headers completos de navegador para evitar detecção.
    
    Args:
        user_agent: User-Agent customizado (se None, usa rotador)
        referer: URL de referência
    
    Returns:
        Dict com headers completos
    """
    if not user_agent:
        user_agent = user_agent_rotator.get_random()
    
    # Determinar versão do Chrome a partir do User-Agent
    chrome_version = "120"
    if "Chrome/" in user_agent:
        try:
            chrome_part = user_agent.split("Chrome/")[1].split(" ")[0]
            chrome_version = chrome_part.split(".")[0]
        except:
            pass
    
    headers = {
        'User-Agent': user_agent,
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': referer,
        'Origin': 'https://betnacional.bet.br',
        'sec-ch-ua': f'"Chromium";v="{chrome_version}", "Google Chrome";v="{chrome_version}", "Not_A Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'cross-site',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'DNT': '1',  # Do Not Track
    }
    
    return headers


def add_random_delay(min_seconds: float = 0.5, max_seconds: float = 2.0):
    """
    Adiciona um delay aleatório entre requisições para simular comportamento humano.
    
    Args:
        min_seconds: Delay mínimo em segundos
        max_seconds: Delay máximo em segundos
    """
    delay = random.uniform(min_seconds, max_seconds)
    time.sleep(delay)


def create_session(use_cookies: bool = True) -> Session:
    """
    Cria uma sessão HTTP persistente com configurações otimizadas.
    
    Args:
        use_cookies: Se True, usa gerenciador de cookies persistente
    
    Returns:
        Session configurada
    """
    if use_cookies:
        # Usar sessão com cookies persistentes
        from utils.cookie_manager import get_session_with_cookies
        session = get_session_with_cookies()
    else:
        session = Session()
    
    # Configurar timeout padrão
    session.timeout = 30
    
    # Configurar headers padrão
    session.headers.update(get_browser_headers())
    
    # Configurar adaptadores para melhor performance
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session


class RequestThrottle:
    """
    Throttle para adicionar delays inteligentes entre requisições.
    """
    
    def __init__(self, min_delay: float = 1.0, max_delay: float = 3.0, jitter: float = 0.5):
        """
        Inicializa o throttle.
        
        Args:
            min_delay: Delay mínimo em segundos
            max_delay: Delay máximo em segundos
            jitter: Variação aleatória adicional
        """
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.last_request_time = 0.0
    
    def wait_if_needed(self):
        """Aguarda se necessário para respeitar o throttle."""
        now = time.time()
        time_since_last = now - self.last_request_time
        
        # Calcular delay necessário
        base_delay = random.uniform(self.min_delay, self.max_delay)
        jitter_amount = random.uniform(-self.jitter, self.jitter)
        total_delay = max(0, base_delay + jitter_amount)
        
        if time_since_last < total_delay:
            sleep_time = total_delay - time_since_last
            logger.debug(f"Throttle: aguardando {sleep_time:.2f}s antes da próxima requisição")
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()


# Instâncias globais
api_throttle = RequestThrottle(min_delay=1.5, max_delay=3.0, jitter=0.5)
html_throttle = RequestThrottle(min_delay=2.0, max_delay=4.0, jitter=1.0)


def get_enhanced_headers_for_api(user_agent: Optional[str] = None) -> Dict[str, str]:
    """
    Gera headers otimizados especificamente para requisições da API XHR.
    
    Args:
        user_agent: User-Agent customizado
    
    Returns:
        Dict com headers completos
    """
    return get_browser_headers(user_agent, referer="https://betnacional.bet.br/")


def should_rotate_user_agent(failure_count: int = 0) -> bool:
    """
    Determina se deve rotacionar User-Agent baseado em falhas.
    
    Args:
        failure_count: Número de falhas consecutivas
    
    Returns:
        True se deve rotacionar
    """
    # Rotacionar após 3 falhas consecutivas
    return failure_count >= 3


def get_realistic_referer(url: str) -> str:
    """
    Gera um referer realista baseado na URL.
    
    Args:
        url: URL da requisição
    
    Returns:
        Referer apropriado
    """
    # Se for uma URL de evento, referer pode ser a página de eventos
    if "/event/" in url:
        return "https://betnacional.bet.br/events/1/0/7"  # Exemplo: Champions League
    elif "/events/" in url:
        return "https://betnacional.bet.br/sports/1"
    else:
        return "https://betnacional.bet.br/"

