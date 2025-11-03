"""Envio de mensagens via Telegram."""
from typing import Optional
import requests
from config.settings import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import logger


def tg_send_message(text: str, parse_mode: Optional[str] = "HTML") -> None:
    """Usa HTML por padrão; omite parse_mode se None para evitar 400."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram não configurado (TOKEN/CHAT_ID ausentes).")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:  # só inclui quando tem valor válido
        payload["parse_mode"] = parse_mode
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code != 200:
            logger.error("Telegram %s: %s", r.status_code, r.text[:300])
    except Exception as e:
        logger.exception("Erro Telegram: %s", e)


def h(b: str) -> str:
    """Helper para texto em negrito HTML."""
    return f"<b>{b}</b>"

