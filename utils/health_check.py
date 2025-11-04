"""
Sistema de health checks e monitoramento do sistema.
"""
import time
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from utils.logger import logger
from config.settings import DB_URL, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, API_TIMEOUT, HEALTH_CHECK_TIMEOUT
from models.database import SessionLocal, Game
from notifications.telegram import tg_send_message


class SystemHealth:
    """
    Classe para verificar a saúde do sistema e gerar alertas.
    """
    
    def __init__(self):
        self.last_checks: Dict[str, Dict[str, Any]] = {}
        self.alert_cooldown: Dict[str, datetime] = {}  # Previne spam de alertas
        self.cooldown_minutes = 30  # Não enviar mesmo alerta por 30 minutos
    
    def check_api_health(self) -> Tuple[bool, Optional[str]]:
        """
        Verifica se a API do Betnacional está respondendo.
        
        Returns:
            Tuple (is_healthy, error_message)
        """
        try:
            import requests
            from scraping.betnacional import fetch_events_from_api
            
            # Testa com um campeonato conhecido (UEFA Champions League)
            start_time = time.time()
            result = fetch_events_from_api(
                sport_id=1,
                category_id=0,
                tournament_id=7,
                market_id=1
            )
            elapsed = time.time() - start_time
            
            if result is None:
                return (False, "API retornou None")
            
            if elapsed > 10.0:
                return (False, f"API muito lenta ({elapsed:.2f}s)")
            
            return (True, None)
            
        except Exception as e:
            error_msg = str(e)[:200]
            return (False, f"Erro ao verificar API: {error_msg}")
    
    def check_db_health(self) -> Tuple[bool, Optional[str]]:
        """
        Verifica se o banco de dados está acessível e funcionando.
        
        Returns:
            Tuple (is_healthy, error_message)
        """
        try:
            session = SessionLocal()
            try:
                # Testa query simples
                start_time = time.time()
                count = session.query(Game).count()
                elapsed = time.time() - start_time
                
                if elapsed > 2.0:
                    return (False, f"Banco muito lento ({elapsed:.2f}s)")
                
                # Testa query com filtro (usando índice)
                start_time = time.time()
                live_count = session.query(Game).filter(Game.status == "live").count()
                elapsed = time.time() - start_time
                
                if elapsed > 2.0:
                    return (False, f"Query com índice muito lenta ({elapsed:.2f}s)")
                
                return (True, None)
                
            finally:
                session.close()
                
        except Exception as e:
            error_msg = str(e)[:200]
            return (False, f"Erro ao verificar banco: {error_msg}")
    
    def check_telegram_health(self) -> Tuple[bool, Optional[str]]:
        """
        Verifica se o Telegram está funcionando (envia mensagem de teste silenciosa).
        
        Returns:
            Tuple (is_healthy, error_message)
        """
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            return (False, "Telegram não configurado (TOKEN/CHAT_ID ausentes)")
        
        try:
            import requests
            
            # Testa apenas getMe (não envia mensagem)
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe"
            response = requests.get(url, timeout=HEALTH_CHECK_TIMEOUT)
            
            if response.status_code != 200:
                return (False, f"Telegram API retornou {response.status_code}")
            
            data = response.json()
            if not data.get("ok"):
                return (False, "Telegram API retornou erro")
            
            return (True, None)
            
        except Exception as e:
            error_msg = str(e)[:200]
            return (False, f"Erro ao verificar Telegram: {error_msg}")
    
    def check_all(self) -> Dict[str, Any]:
        """
        Executa todos os health checks.
        
        Returns:
            Dict com resultados de todos os checks
        """
        results = {
            "timestamp": datetime.now(),
            "api": {},
            "database": {},
            "telegram": {},
            "overall": False
        }
        
        # Check API
        api_healthy, api_error = self.check_api_health()
        results["api"] = {
            "healthy": api_healthy,
            "error": api_error
        }
        self.last_checks["api"] = results["api"]
        
        # Check Database
        db_healthy, db_error = self.check_db_health()
        results["database"] = {
            "healthy": db_healthy,
            "error": db_error
        }
        self.last_checks["database"] = results["database"]
        
        # Check Telegram
        tg_healthy, tg_error = self.check_telegram_health()
        results["telegram"] = {
            "healthy": tg_healthy,
            "error": tg_error
        }
        self.last_checks["telegram"] = results["telegram"]
        
        # Overall health
        results["overall"] = api_healthy and db_healthy and tg_healthy
        
        return results
    
    def should_send_alert(self, check_name: str) -> bool:
        """
        Verifica se deve enviar alerta (considera cooldown).
        
        Args:
            check_name: Nome do check (ex: "api", "database", "telegram")
        
        Returns:
            True se deve enviar alerta
        """
        now = datetime.now()
        last_alert = self.alert_cooldown.get(check_name)
        
        if last_alert is None:
            return True
        
        time_since_last = now - last_alert
        return time_since_last >= timedelta(minutes=self.cooldown_minutes)
    
    def send_alert(self, check_name: str, error: str, alert_type: str = "warning"):
        """
        Envia alerta via Telegram.
        
        Args:
            check_name: Nome do check que falhou
            error: Mensagem de erro
            alert_type: Tipo de alerta (warning, critical)
        """
        if not self.should_send_alert(check_name):
            logger.debug(f"Alerta {check_name} em cooldown, ignorando")
            return
        
        # Atualiza cooldown
        self.alert_cooldown[check_name] = datetime.now()
        
        # Mapeia nomes para português
        check_names = {
            "api": "API do Betnacional",
            "database": "Banco de Dados",
            "telegram": "Telegram"
        }
        
        check_display = check_names.get(check_name, check_name)
        
        # Ícones baseados no tipo
        if alert_type == "critical":
            icon = "🔴"
            severity = "CRÍTICO"
        else:
            icon = "⚠️"
            severity = "ATENÇÃO"
        
        message = (
            f"{icon} <b>ALERTA DE SAÚDE DO SISTEMA</b>\n\n"
            f"<b>Componente:</b> {check_display}\n"
            f"<b>Severidade:</b> {severity}\n"
            f"<b>Erro:</b> {error}\n\n"
            f"<i>Verifique o sistema imediatamente.</i>"
        )
        
        try:
            tg_send_message(
                message,
                message_type="health_alert",
                parse_mode="HTML"
            )
            logger.warning(f"Alerta de saúde enviado: {check_name} - {error}")
        except Exception as e:
            logger.error(f"Erro ao enviar alerta de saúde: {e}")
    
    def check_and_alert(self) -> Dict[str, Any]:
        """
        Executa health checks e envia alertas se necessário.
        
        Returns:
            Dict com resultados dos checks
        """
        results = self.check_all()
        
        # Verifica cada componente e envia alertas
        if not results["api"]["healthy"]:
            self.send_alert(
                "api",
                results["api"]["error"] or "API não está respondendo",
                alert_type="critical"
            )
        
        if not results["database"]["healthy"]:
            self.send_alert(
                "database",
                results["database"]["error"] or "Banco de dados não está respondendo",
                alert_type="critical"
            )
        
        if not results["telegram"]["healthy"]:
            self.send_alert(
                "telegram",
                results["telegram"]["error"] or "Telegram não está funcionando",
                alert_type="warning"
            )
        
        # Se tudo está saudável e havia problemas antes, envia notificação de recuperação
        if results["overall"]:
            # Verifica se havia problemas anteriormente
            had_issues = any(
                not self.last_checks.get(key, {}).get("healthy", True)
                for key in ["api", "database"]
            )
            
            if had_issues:
                message = (
                    "✅ <b>SISTEMA RECUPERADO</b>\n\n"
                    "Todos os componentes estão funcionando normalmente novamente."
                )
                try:
                    tg_send_message(
                        message,
                        message_type="health_recovery",
                        parse_mode="HTML"
                    )
                    logger.info("Notificação de recuperação enviada")
                except Exception as e:
                    logger.error(f"Erro ao enviar notificação de recuperação: {e}")
        
        return results
    
    def get_status_summary(self) -> str:
        """
        Retorna um resumo textual do status do sistema.
        
        Returns:
            String com resumo do status
        """
        if not self.last_checks:
            return "Nenhum check executado ainda"
        
        summary_parts = []
        
        for check_name in ["api", "database", "telegram"]:
            check = self.last_checks.get(check_name, {})
            healthy = check.get("healthy", False)
            status = "✅" if healthy else "❌"
            summary_parts.append(f"{status} {check_name.upper()}")
        
        return " | ".join(summary_parts)


# Instância global
system_health = SystemHealth()

