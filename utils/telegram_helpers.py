"""Funções auxiliares para Telegram."""
from notifications.telegram import tg_send_message


def send_summary_safe(text: str, message_type: str = "summary") -> None:
    """
    Envia mensagem de resumo com fallback para diferentes formatos.
    Tenta HTML primeiro, depois texto simples.
    """
    try:
        tg_send_message(text, parse_mode="HTML", message_type=message_type)
        return
    except Exception:
        from utils.logger import logger
        logger.exception("Falha com HTML; tentando sem parse_mode…")
    try:
        tg_send_message(text, parse_mode=None, message_type=message_type)
    except TypeError:
        try:
            tg_send_message(text, message_type=message_type)
        except Exception:
            logger.exception("Falha ao enviar resumo ao Telegram (fallback simples).")
    except Exception:
        logger.exception("Falha ao enviar resumo ao Telegram (fallback simples).")

