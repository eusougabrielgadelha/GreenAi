"""Configurações centralizadas do sistema."""
import os
import pytz
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

# ================================
# Playwright (opcional)
# ================================
HAS_PLAYWRIGHT = False
try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except Exception:
    HAS_PLAYWRIGHT = False

# ================================
# Configurações de Timezone
# ================================
APP_TZ = os.getenv("APP_TZ", "America/Sao_Paulo")  # Horário de Brasília
ZONE = pytz.timezone(APP_TZ)
MORNING_HOUR = int(os.getenv("MORNING_HOUR", "6"))

# ================================
# Configurações de Banco de Dados
# ================================
DB_URL = os.getenv("DB_URL", "sqlite:///betauto.sqlite3")

# ================================
# Configurações de Telegram
# ================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ================================
# Configurações de Scraping
# ================================
SCRAPE_BACKEND = os.getenv("SCRAPE_BACKEND", "requests").lower()  # requests | playwright | auto
REQUESTS_TIMEOUT = float(os.getenv("REQUESTS_TIMEOUT", "20"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
)

# ================================
# Configurações de Timeouts (Centralizados)
# ================================
# Timeout para requisições HTTP gerais (requests)
API_TIMEOUT = float(os.getenv("API_TIMEOUT", "20"))  # Requisições à API do Betnacional
HTML_TIMEOUT = float(os.getenv("HTML_TIMEOUT", "30"))  # Scraping de páginas HTML
RESULT_CHECK_TIMEOUT = float(os.getenv("RESULT_CHECK_TIMEOUT", "10"))  # Verificação de resultados
TELEGRAM_TIMEOUT = float(os.getenv("TELEGRAM_TIMEOUT", "15"))  # Requisições ao Telegram
HEALTH_CHECK_TIMEOUT = float(os.getenv("HEALTH_CHECK_TIMEOUT", "10"))  # Health checks

# Timeout para Playwright (em milissegundos)
PLAYWRIGHT_NAVIGATION_TIMEOUT = int(os.getenv("PLAYWRIGHT_NAVIGATION_TIMEOUT", "60000"))  # Navegação (60s)
PLAYWRIGHT_SELECTOR_TIMEOUT = int(os.getenv("PLAYWRIGHT_SELECTOR_TIMEOUT", "15000"))  # Aguardar seletor (15s)
PLAYWRIGHT_NETWORKIDLE_TIMEOUT = int(os.getenv("PLAYWRIGHT_NETWORKIDLE_TIMEOUT", "60000"))  # Network idle (60s)

# Compatibilidade: manter REQUESTS_TIMEOUT para não quebrar código existente
# Se não especificado, usa API_TIMEOUT como padrão
if not os.getenv("REQUESTS_TIMEOUT"):
    REQUESTS_TIMEOUT = API_TIMEOUT

# ================================
# Configurações de Alta Confiança
# ================================
HIGH_CONF_THRESHOLD = float(os.getenv("HIGH_CONF_THRESHOLD", "0.60"))
HIGH_CONF_SENT_MARK = "[HC_SENT]"
# Flag para buscar apenas jogos de alta confiança (ignora outros critérios)
ONLY_HIGH_CONF_GAMES = os.getenv("ONLY_HIGH_CONF_GAMES", "false").lower() == "true"

# ================================
# Links Extras
# ================================
EXTRA_LINKS = [s.strip() for s in os.getenv("BETNACIONAL_LINKS", "").split(",") if s.strip()]

# ================================
# Configurações de Logging
# ================================
LOG_DIR = os.getenv("LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# ================================
# Configurações de Agendamento
# ================================
START_ALERT_MIN = int(os.getenv("START_ALERT_MIN", "15"))
LATE_WATCH_WINDOW_MIN = int(os.getenv("LATE_WATCH_WINDOW_MIN", "130"))

# ================================
# Configurações de Watchlist
# ================================
WATCHLIST_DELTA = float(os.getenv("WATCHLIST_DELTA", "0.05"))
WATCHLIST_MIN_LEAD_MIN = int(os.getenv("WATCHLIST_MIN_LEAD_MIN", "30"))
WATCHLIST_RESCAN_MIN = int(os.getenv("WATCHLIST_RESCAN_MIN", "3"))

# ================================
# Configurações de Apostas
# ================================
MIN_EV = float(os.getenv("MIN_EV", "-0.02"))
MIN_PROB = float(os.getenv("MIN_PROB", "0.20"))
FAV_MODE = os.getenv("FAV_MODE", "on").lower()
FAV_PROB_MIN = float(os.getenv("FAV_PROB_MIN", "0.60"))
FAV_GAP_MIN = float(os.getenv("FAV_GAP_MIN", "0.10"))
EV_TOL = float(os.getenv("EV_TOL", "-0.03"))
FAV_IGNORE_EV = os.getenv("FAV_IGNORE_EV", "on").lower() == "on"
HIGH_ODD_MODE = os.getenv("HIGH_ODD_MODE", "on").lower()
HIGH_ODD_MIN = float(os.getenv("HIGH_ODD_MIN", "1.50"))
HIGH_ODD_MAX_PROB = float(os.getenv("HIGH_ODD_MAX_PROB", "0.45"))
HIGH_ODD_MIN_EV = float(os.getenv("HIGH_ODD_MIN_EV", "-0.15"))

# ================================
# Configurações de Scraping de Campeonatos
# ================================
# Se True, faz scraping apenas em campeonatos importantes
SCRAPE_IMPORTANT_ONLY = os.getenv("SCRAPE_IMPORTANT_ONLY", "false").lower() == "true"

# ================================
# Links de Apostas Monitorados
# ================================
BETTING_LINKS = {
    "UEFA Champions League": {"pais": "Europa", "campeonato": "UEFA Champions League", "link": "https://betnacional.bet.br/events/1/0/7"},
    "Espanha - LaLiga": {"pais": "Espanha", "campeonato": "LaLiga", "link": "https://betnacional.bet.br/events/1/0/8"},
    "Inglaterra - Premier League": {"pais": "Inglaterra", "campeonato": "Premier League", "link": "https://betnacional.bet.br/events/1/0/17"},
    "Brasil - Paulista": {"pais": "Brasil", "campeonato": "Paulista", "link": "https://betnacional.bet.br/events/1/0/15644"},
    "França - Ligue 1": {"pais": "França", "campeonato": "Ligue 1", "link": "https://betnacional.bet.br/events/1/0/34"},
    "Itália - Série A": {"pais": "Itália", "campeonato": "Série A", "link": "https://betnacional.bet.br/events/1/0/23"},
    "Alemanha - Bundesliga": {"pais": "Alemanha", "campeonato": "Bundesliga", "link": "https://betnacional.bet.br/events/1/0/35"},
    "Brasil - Série A": {"pais": "Brasil", "campeonato": "Brasileirão Série A", "link": "https://betnacional.bet.br/events/1/0/325"},
    "Brasil - Série B": {"pais": "Brasil", "campeonato": "Brasileirão Série B", "link": "https://betnacional.bet.br/events/1/0/390"},
    "Brasil - Série C": {"pais": "Brasil", "campeonato": "Brasileirão Série C", "link": "https://betnacional.bet.br/events/1/0/1281"},
    "Argentina - Série A": {"pais": "Argentina", "campeonato": "Argentina Série A", "link": "https://betnacional.bet.br/events/1/0/30106"},
    "Argentina - Série B": {"pais": "Argentina", "campeonato": "Argentina Série B", "link": "https://betnacional.bet.br/events/1/0/703"},
    "Argentina - Super Liga 2": {"pais": "Argentina", "campeonato": "Super Liga", "link": "https://betnacional.bet.br/events/1/0/155"},
    "México - Geral": {"pais": "México", "campeonato": "Todos", "link": "https://betnacional.bet.br/events/1/12/0"},
    "Portugal - Primeira Liga": {"pais": "Portugal", "campeonato": "Primeira Liga", "link": "https://betnacional.bet.br/events/1/0/238"},
    "Estados Unidos - Major League Soccer": {"pais": "Estados Unidos", "campeonato": "Major League Soccer", "link": "https://betnacional.bet.br/events/1/0/242"},
}

def get_all_betting_links() -> list[str]:
    """
    Retorna todos os links de apostas, incluindo extras.
    
    Se SCRAPE_IMPORTANT_ONLY=True, retorna apenas links de campeonatos importantes.
    """
    from scraping.tournaments import get_important_tournaments, get_all_football_tournaments
    
    # Se configurado para apenas importantes, usar mapeamento
    if SCRAPE_IMPORTANT_ONLY:
        logger = __import__('utils.logger', fromlist=['logger']).logger
        try:
            tournaments = get_all_football_tournaments()
            important = get_important_tournaments(tournaments)
            # Retornar URLs dos campeonatos importantes
            important_urls = [t.get('url') for t in important if t.get('url')]
            if important_urls:
                logger.info(f"Modo IMPORTANT_ONLY: usando {len(important_urls)} campeonato(s) importante(s)")
                return important_urls
        except Exception as e:
            logger = __import__('utils.logger', fromlist=['logger']).logger
            logger.warning(f"Erro ao buscar campeonatos importantes: {e}. Usando links padrão.")
    
    # Modo normal: usar BETTING_LINKS
    base = [cfg["link"] for cfg in BETTING_LINKS.values() if "link" in cfg]
    base.extend(EXTRA_LINKS)
    seen, out = set(), []
    for u in base:
        if u not in seen:
            out.append(u)
            seen.add(u)
    return out

def is_high_conf(pick_prob: float) -> bool:
    """Verifica se um jogo tem alta confiança baseado em pick_prob."""
    try:
        return float(pick_prob or 0.0) >= HIGH_CONF_THRESHOLD
    except Exception:
        return False

def was_high_conf_notified(pick_reason: str) -> bool:
    """Verifica se um jogo já foi notificado como alta confiança."""
    return HIGH_CONF_SENT_MARK in (pick_reason or "")

def mark_high_conf_notified(pick_reason: str) -> str:
    """Marca um jogo como notificado de alta confiança."""
    return (f"{(pick_reason or '').strip()} {HIGH_CONF_SENT_MARK}").strip()

