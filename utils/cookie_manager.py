"""
Gerenciador de cookies com persistência e reutilização entre requisições.
"""
import json
import pickle
import os
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime, timedelta
from requests.cookies import RequestsCookieJar
from requests import Session
from utils.logger import logger


class CookieManager:
    """
    Gerencia cookies persistentes para requisições HTTP.
    
    Funcionalidades:
    - Carrega cookies salvos de arquivo
    - Salva cookies após cada requisição
    - Mantém cookies válidos por período configurável
    - Limpa cookies expirados automaticamente
    """
    
    def __init__(
        self,
        cookie_file: str = "cookies/cookies.json",
        max_age_days: int = 30,
        domain: str = "betnacional.bet.br"
    ):
        """
        Inicializa o gerenciador de cookies.
        
        Args:
            cookie_file: Caminho do arquivo para salvar cookies
            max_age_days: Idade máxima dos cookies em dias (padrão: 30)
            domain: Domínio para filtrar cookies
        """
        self.cookie_file = Path(cookie_file)
        self.max_age_days = max_age_days
        self.domain = domain
        
        # Criar diretório se não existir
        self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Carregar cookies salvos
        self.cookies = self._load_cookies()
        
        logger.info(f"CookieManager inicializado: {len(self.cookies)} cookies carregados")
    
    def _load_cookies(self) -> RequestsCookieJar:
        """
        Carrega cookies salvos do arquivo.
        
        Returns:
            RequestsCookieJar com cookies carregados
        """
        cookies = RequestsCookieJar()
        
        if not self.cookie_file.exists():
            logger.debug(f"Arquivo de cookies não encontrado: {self.cookie_file}")
            return cookies
        
        try:
            # Tentar carregar como JSON primeiro
            if self.cookie_file.suffix == '.json':
                with open(self.cookie_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    # Converter para RequestsCookieJar
                    for cookie_data in data.get('cookies', []):
                        name = cookie_data.get('name')
                        value = cookie_data.get('value')
                        domain = cookie_data.get('domain', self.domain)
                        path = cookie_data.get('path', '/')
                        expires = cookie_data.get('expires')
                        
                        # Verificar se cookie não expirou
                        if expires:
                            try:
                                expires_dt = datetime.fromisoformat(expires)
                                if expires_dt < datetime.now():
                                    logger.debug(f"Cookie expirado ignorado: {name}")
                                    continue
                            except (ValueError, TypeError):
                                pass
                        
                        # Adicionar cookie
                        cookies.set(name, value, domain=domain, path=path)
                        
                        # Se tem expires, definir
                        if expires:
                            try:
                                expires_dt = datetime.fromisoformat(expires)
                                expires_timestamp = expires_dt.timestamp()
                                cookies.set(name, value, domain=domain, path=path, expires=expires_timestamp)
                            except (ValueError, TypeError):
                                pass
                
                logger.info(f"Cookies carregados de {self.cookie_file}: {len(cookies)} cookies válidos")
            
            # Tentar carregar como pickle (formato alternativo)
            elif self.cookie_file.suffix == '.pkl':
                with open(self.cookie_file, 'rb') as f:
                    cookies = pickle.load(f)
                logger.info(f"Cookies carregados de {self.cookie_file} (pickle): {len(cookies)} cookies")
            
        except Exception as e:
            logger.warning(f"Erro ao carregar cookies de {self.cookie_file}: {e}")
            cookies = RequestsCookieJar()
        
        # Limpar cookies expirados
        self._clean_expired_cookies(cookies)
        
        return cookies
    
    def _clean_expired_cookies(self, cookies: RequestsCookieJar) -> RequestsCookieJar:
        """
        Remove cookies expirados do jar.
        
        Args:
            cookies: CookieJar para limpar
        
        Returns:
            CookieJar limpo
        """
        now = datetime.now()
        cleaned = RequestsCookieJar()
        
        for cookie in cookies:
            # Verificar se cookie expirou
            if cookie.expires:
                try:
                    expires_dt = datetime.fromtimestamp(cookie.expires)
                    if expires_dt < now:
                        logger.debug(f"Cookie expirado removido: {cookie.name}")
                        continue
                except (ValueError, TypeError):
                    pass
            
            # Verificar idade máxima
            if hasattr(cookie, 'created') and cookie.created:
                try:
                    created_dt = datetime.fromtimestamp(cookie.created)
                    age_days = (now - created_dt).days
                    if age_days > self.max_age_days:
                        logger.debug(f"Cookie muito antigo removido: {cookie.name} ({age_days} dias)")
                        continue
                except (ValueError, TypeError):
                    pass
            
            # Adicionar cookie válido
            cleaned.set(
                cookie.name,
                cookie.value,
                domain=cookie.domain or self.domain,
                path=cookie.path or '/'
            )
        
        return cleaned
    
    def _save_cookies(self, cookies: RequestsCookieJar):
        """
        Salva cookies em arquivo.
        
        Args:
            cookies: CookieJar para salvar
        """
        try:
            # Limpar cookies expirados antes de salvar
            cookies = self._clean_expired_cookies(cookies)
            
            # Converter para formato JSON
            cookies_data = {
                'saved_at': datetime.now().isoformat(),
                'domain': self.domain,
                'cookies': []
            }
            
            for cookie in cookies:
                cookie_data = {
                    'name': cookie.name,
                    'value': cookie.value,
                    'domain': cookie.domain or self.domain,
                    'path': cookie.path or '/'
                }
                
                # Adicionar expires se disponível
                if cookie.expires:
                    try:
                        expires_dt = datetime.fromtimestamp(cookie.expires)
                        cookie_data['expires'] = expires_dt.isoformat()
                    except (ValueError, TypeError):
                        pass
                
                cookies_data['cookies'].append(cookie_data)
            
            # Salvar em JSON
            with open(self.cookie_file, 'w', encoding='utf-8') as f:
                json.dump(cookies_data, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"Cookies salvos em {self.cookie_file}: {len(cookies)} cookies")
            
        except Exception as e:
            logger.warning(f"Erro ao salvar cookies em {self.cookie_file}: {e}")
    
    def get_session(self) -> Session:
        """
        Cria uma sessão HTTP com cookies carregados.
        
        Returns:
            Session com cookies configurados
        """
        session = Session()
        
        # Adicionar cookies carregados à sessão
        session.cookies.update(self.cookies)
        
        return session
    
    def update_cookies(self, response):
        """
        Atualiza cookies a partir de uma resposta HTTP.
        
        Args:
            response: Resposta HTTP do requests
        """
        # Atualizar cookies com os novos da resposta
        self.cookies.update(response.cookies)
        
        # Salvar cookies atualizados
        self._save_cookies(self.cookies)
        
        logger.debug(f"Cookies atualizados: {len(response.cookies)} novos cookies")
    
    def get_cookies_dict(self) -> Dict[str, str]:
        """
        Retorna cookies como dicionário simples.
        
        Returns:
            Dict com nome=valor dos cookies
        """
        return {cookie.name: cookie.value for cookie in self.cookies}
    
    def clear_cookies(self):
        """
        Limpa todos os cookies.
        """
        self.cookies = RequestsCookieJar()
        
        # Remover arquivo de cookies
        if self.cookie_file.exists():
            try:
                os.remove(self.cookie_file)
                logger.info(f"Cookies limpos e arquivo removido: {self.cookie_file}")
            except Exception as e:
                logger.warning(f"Erro ao remover arquivo de cookies: {e}")
    
    def get_stats(self) -> Dict:
        """
        Retorna estatísticas dos cookies.
        
        Returns:
            Dict com estatísticas
        """
        now = datetime.now()
        valid_count = 0
        expired_count = 0
        oldest_cookie = None
        newest_cookie = None
        
        for cookie in self.cookies:
            if cookie.expires:
                try:
                    expires_dt = datetime.fromtimestamp(cookie.expires)
                    if expires_dt < now:
                        expired_count += 1
                    else:
                        valid_count += 1
                        if not oldest_cookie or expires_dt < oldest_cookie:
                            oldest_cookie = expires_dt
                        if not newest_cookie or expires_dt > newest_cookie:
                            newest_cookie = expires_dt
                except (ValueError, TypeError):
                    valid_count += 1
            else:
                valid_count += 1
        
        return {
            'total_cookies': len(self.cookies),
            'valid_cookies': valid_count,
            'expired_cookies': expired_count,
            'oldest_expiry': oldest_cookie.isoformat() if oldest_cookie else None,
            'newest_expiry': newest_cookie.isoformat() if newest_cookie else None,
            'cookie_file': str(self.cookie_file)
        }


# Instância global do gerenciador de cookies
# Carrega cookies de cookies/cookies.json
_cookie_manager: Optional[CookieManager] = None


def get_cookie_manager() -> CookieManager:
    """
    Retorna a instância global do gerenciador de cookies.
    
    Returns:
        CookieManager singleton
    """
    global _cookie_manager
    
    if _cookie_manager is None:
        _cookie_manager = CookieManager(
            cookie_file="cookies/cookies.json",
            max_age_days=30,
            domain="betnacional.bet.br"
        )
    
    return _cookie_manager


def get_session_with_cookies() -> Session:
    """
    Cria uma sessão HTTP com cookies carregados.
    
    Returns:
        Session com cookies configurados
    """
    manager = get_cookie_manager()
    return manager.get_session()


def update_cookies_from_response(response):
    """
    Atualiza cookies a partir de uma resposta HTTP.
    
    Args:
        response: Resposta HTTP do requests
    """
    manager = get_cookie_manager()
    manager.update_cookies(response)

