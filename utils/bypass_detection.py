"""
Sistema avançado de bypass de detecção para raspagem de dados.
Implementa múltiplas estratégias para contornar bloqueios e detecção.
"""
import random
import time
import json
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from requests import Session, Response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib3.util.ssl_ import create_urllib3_context
import ssl

from utils.logger import logger
from utils.cookie_manager import get_cookie_manager, update_cookies_from_response


class BypassDetector:
    """
    Sistema completo de bypass de detecção com múltiplas estratégias.
    """
    
    def __init__(self):
        self.rotation_index = 0
        self.failure_count = 0
        self.last_rotation_time = datetime.now()
        self.detected_patterns = []
    
    def get_rotated_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        """
        Gera headers rotacionados com variações realistas.
        
        Args:
            referer: URL de referência (se None, gera automaticamente)
        
        Returns:
            Dict com headers completos
        """
        from utils.anti_block import user_agent_rotator, get_browser_headers
        
        # Rotacionar User-Agent
        user_agent = user_agent_rotator.get_random()
        
        # Gerar headers base
        headers = get_browser_headers(user_agent=user_agent, referer=referer)
        
        # Adicionar variações aleatórias para evitar fingerprinting
        variations = self._get_header_variations()
        headers.update(variations)
        
        return headers
    
    def _get_header_variations(self) -> Dict[str, str]:
        """
        Gera variações aleatórias de headers para evitar detecção.
        
        Returns:
            Dict com variações adicionais
        """
        variations = {}
        
        # Variações de Accept-Language
        languages = [
            'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
            'pt-BR,pt;q=0.9',
            'pt-BR,pt;q=0.9,en;q=0.8',
        ]
        variations['Accept-Language'] = random.choice(languages)
        
        # Variações de Accept-Encoding
        encodings = [
            'gzip, deflate, br',
            'gzip, deflate',
            'gzip, br',
        ]
        variations['Accept-Encoding'] = random.choice(encodings)
        
        # Variações de DNT
        if random.random() < 0.7:  # 70% das vezes
            variations['DNT'] = '1'
        
        # Variações de Upgrade-Insecure-Requests
        if random.random() < 0.5:  # 50% das vezes
            variations['Upgrade-Insecure-Requests'] = '1'
        
        return variations
    
    def create_stealth_session(self, use_cookies: bool = True) -> Session:
        """
        Cria uma sessão HTTP com configurações de stealth.
        
        Args:
            use_cookies: Se True, usa cookies persistentes
        
        Returns:
            Session configurada para stealth
        """
        if use_cookies:
            from utils.cookie_manager import get_session_with_cookies
            session = get_session_with_cookies()
        else:
            session = Session()
        
        # Configurar timeout
        session.timeout = 30
        
        # Configurar headers
        session.headers.update(self.get_rotated_headers())
        
        # Configurar SSL/TLS para evitar detecção
        try:
            # Criar contexto SSL customizado
            ctx = create_urllib3_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            # Adicionar cipher suites modernas
            ctx.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS')
        except Exception as e:
            logger.debug(f"Erro ao configurar SSL: {e}")
        
        # Configurar retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            respect_retry_after_header=True
        )
        
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=20
        )
        
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def add_human_delays(self, min_seconds: float = 0.5, max_seconds: float = 2.0):
        """
        Adiciona delays que simulam comportamento humano.
        
        Args:
            min_seconds: Delay mínimo
            max_seconds: Delay máximo
        """
        # Delay base aleatório
        base_delay = random.uniform(min_seconds, max_seconds)
        
        # Adicionar variação humana (não linear)
        human_variation = random.gauss(0, 0.3)  # Distribuição normal
        delay = max(0.1, base_delay + human_variation)
        
        # Adicionar micro-delays aleatórios
        if random.random() < 0.3:  # 30% das vezes
            micro_delay = random.uniform(0.05, 0.2)
            delay += micro_delay
        
        time.sleep(delay)
    
    def detect_blockage(self, response: Response) -> Tuple[bool, str]:
        """
        Detecta se a requisição foi bloqueada.
        
        Args:
            response: Resposta HTTP
        
        Returns:
            (is_blocked, reason)
        """
        # Verificar status code
        if response.status_code == 403:
            return True, "403 Forbidden"
        elif response.status_code == 429:
            return True, "429 Too Many Requests"
        elif response.status_code == 503:
            return True, "503 Service Unavailable"
        
        # Verificar conteúdo da resposta
        content = response.text.lower()
        
        # Padrões comuns de bloqueio
        block_patterns = [
            r'access denied',
            r'blocked',
            r'captcha',
            r'cloudflare',
            r'forbidden',
            r'rate limit',
            r'too many requests',
            r'bot detection',
            r'security check',
        ]
        
        for pattern in block_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True, f"Blocked content detected: {pattern}"
        
        # Verificar tamanho da resposta (bloqueios geralmente retornam HTML pequeno)
        if len(response.text) < 1000 and 'json' in response.headers.get('Content-Type', '').lower():
            return True, "Suspicious small response"
        
        return False, ""
    
    def handle_blockage(self, reason: str, session: Session) -> bool:
        """
        Tenta contornar um bloqueio detectado.
        
        Args:
            reason: Razão do bloqueio
            session: Sessão HTTP atual
        
        Returns:
            True se conseguiu contornar, False caso contrário
        """
        logger.warning(f"Bloqueio detectado: {reason}. Tentando contornar...")
        
        self.failure_count += 1
        
        # Estratégia 1: Rotacionar User-Agent após múltiplas falhas
        if self.failure_count >= 3:
            logger.info("Rotacionando User-Agent após múltiplas falhas")
            from utils.anti_block import user_agent_rotator
            new_ua = user_agent_rotator.get_next()
            session.headers['User-Agent'] = new_ua
            self.failure_count = 0
            return True
        
        # Estratégia 2: Aguardar mais tempo
        if "429" in reason or "rate limit" in reason.lower():
            wait_time = random.uniform(30, 60)
            logger.info(f"Aguardando {wait_time:.1f}s devido a rate limit...")
            time.sleep(wait_time)
            return True
        
        # Estratégia 3: Limpar cookies e recomeçar
        if self.failure_count >= 5:
            logger.info("Limpar cookies e recomeçar sessão")
            from utils.cookie_manager import get_cookie_manager
            manager = get_cookie_manager()
            manager.clear_cookies()
            session.cookies.clear()
            self.failure_count = 0
            return True
        
        return False
    
    def make_request_with_bypass(
        self,
        session: Session,
        url: str,
        method: str = "GET",
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        max_retries: int = 3,
        use_cookies: bool = True
    ) -> Optional[Response]:
        """
        Faz uma requisição HTTP com múltiplas estratégias de bypass.
        
        Args:
            session: Sessão HTTP
            url: URL para requisitar
            method: Método HTTP (GET, POST)
            params: Parâmetros da requisição
            headers: Headers customizados (se None, usa rotacionados)
            max_retries: Número máximo de tentativas
            use_cookies: Se True, atualiza cookies após requisição
        
        Returns:
            Response ou None em caso de falha
        """
        from utils.anti_block import api_throttle, add_random_delay
        
        for attempt in range(max_retries):
            try:
                # Throttle antes da requisição
                api_throttle.wait_if_needed()
                
                # Rotacionar headers se necessário
                if headers is None:
                    headers = self.get_rotated_headers()
                    session.headers.update(headers)
                else:
                    session.headers.update(headers)
                
                # Adicionar delay humano
                if attempt > 0:
                    wait_time = random.uniform(2, 5) * (attempt + 1)
                    logger.debug(f"Aguardando {wait_time:.1f}s antes de retry {attempt + 1}...")
                    time.sleep(wait_time)
                
                # Fazer requisição
                if method.upper() == "GET":
                    response = session.get(url, params=params, headers=headers, timeout=30)
                elif method.upper() == "POST":
                    response = session.post(url, json=params, headers=headers, timeout=30)
                else:
                    raise ValueError(f"Método HTTP não suportado: {method}")
                
                # Verificar se foi bloqueado
                is_blocked, reason = self.detect_blockage(response)
                
                if is_blocked:
                    logger.warning(f"Bloqueio detectado na tentativa {attempt + 1}: {reason}")
                    
                    # Tentar contornar
                    if self.handle_blockage(reason, session):
                        continue  # Tentar novamente
                    else:
                        if attempt < max_retries - 1:
                            continue  # Tentar novamente sem contornar
                        else:
                            logger.error(f"Falha após {max_retries} tentativas")
                            return None
                
                # Sucesso - atualizar cookies e retornar
                if use_cookies:
                    update_cookies_from_response(response)
                
                # Adicionar delay após sucesso
                add_random_delay(min_seconds=0.3, max_seconds=1.0)
                
                # Resetar contador de falhas após sucesso
                if response.status_code == 200:
                    self.failure_count = 0
                
                return response
                
            except Exception as e:
                logger.warning(f"Erro na tentativa {attempt + 1}/{max_retries}: {e}")
                
                if attempt < max_retries - 1:
                    # Aguardar antes de retry
                    wait_time = random.uniform(2, 5) * (attempt + 1)
                    time.sleep(wait_time)
                else:
                    logger.error(f"Falha após {max_retries} tentativas: {e}")
                    return None
        
        return None
    
    def inject_js_fingerprint(self, html: str) -> str:
        """
        Injeta JavaScript para simular fingerprint de navegador real.
        
        Args:
            html: HTML original
        
        Returns:
            HTML modificado
        """
        # Padrões comuns de detecção que podem ser contornados
        # Nota: Esta é uma função avançada, use com cuidado
        
        js_injections = [
            # Simular window.navigator
            'window.navigator = window.navigator || {};',
            'window.navigator.platform = "Win32";',
            'window.navigator.hardwareConcurrency = 8;',
            'window.navigator.deviceMemory = 8;',
        ]
        
        # Adicionar antes do fechamento de </head>
        if '</head>' in html.lower():
            injection = '\n'.join(js_injections)
            html = html.replace('</head>', f'<script>{injection}</script></head>')
        
        return html
    
    def randomize_request_timing(self, base_delay: float = 1.0) -> float:
        """
        Gera timing aleatório para requisições que simula comportamento humano.
        
        Args:
            base_delay: Delay base
        
        Returns:
            Delay calculado
        """
        # Distribuição log-normal (mais realista para comportamento humano)
        import math
        mu = math.log(base_delay)
        sigma = 0.5
        delay = math.exp(random.gauss(mu, sigma))
        
        # Adicionar variação aleatória
        delay += random.uniform(-0.2, 0.2) * base_delay
        
        return max(0.1, delay)
    
    def get_proxy_config(self) -> Optional[Dict[str, str]]:
        """
        Retorna configuração de proxy se disponível.
        
        Returns:
            Dict com proxies ou None
        """
        import os
        
        proxy_url = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")
        
        if proxy_url:
            return {
                'http': proxy_url,
                'https': proxy_url
            }
        
        return None
    
    def add_request_noise(self, params: Dict) -> Dict:
        """
        Adiciona "ruído" aleatório aos parâmetros para evitar detecção de padrão.
        
        Args:
            params: Parâmetros originais
        
        Returns:
            Parâmetros com ruído adicionado
        """
        noisy_params = params.copy()
        
        # Adicionar timestamp aleatório (simula cache busting)
        if random.random() < 0.3:  # 30% das vezes
            noisy_params['_t'] = int(time.time() * 1000) + random.randint(-1000, 1000)
        
        # Adicionar parâmetro aleatório (simula tracking)
        if random.random() < 0.2:  # 20% das vezes
            noisy_params['_r'] = random.randint(100000, 999999)
        
        return noisy_params


# Instância global
_bypass_detector: Optional[BypassDetector] = None


def get_bypass_detector() -> BypassDetector:
    """
    Retorna a instância global do bypass detector.
    
    Returns:
        BypassDetector singleton
    """
    global _bypass_detector
    
    if _bypass_detector is None:
        _bypass_detector = BypassDetector()
    
    return _bypass_detector


def make_bypass_request(
    url: str,
    method: str = "GET",
    params: Optional[Dict] = None,
    headers: Optional[Dict] = None,
    use_cookies: bool = True,
    max_retries: int = 3
) -> Optional[Response]:
    """
    Função helper para fazer requisições com bypass automático.
    
    Args:
        url: URL para requisitar
        method: Método HTTP
        params: Parâmetros
        headers: Headers customizados
        use_cookies: Usar cookies persistentes
        max_retries: Número máximo de tentativas
    
    Returns:
        Response ou None
    """
    detector = get_bypass_detector()
    session = detector.create_stealth_session(use_cookies=use_cookies)
    
    return detector.make_request_with_bypass(
        session=session,
        url=url,
        method=method,
        params=params,
        headers=headers,
        max_retries=max_retries,
        use_cookies=use_cookies
    )

