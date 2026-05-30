"""Envio de mensagens via Telegram."""
from typing import Optional
import requests
from config.settings import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_TIMEOUT
from utils.logger import logger


def tg_send_message(text: str, parse_mode: Optional[str] = "HTML", message_type: Optional[str] = None, game_id: Optional[int] = None, ext_id: Optional[str] = None, skip_rate_limit: bool = False) -> None:
    """
    Usa HTML por padrão; omite parse_mode se None para evitar 400.
    
    Args:
        text: Texto da mensagem
        parse_mode: Modo de parsing (HTML, Markdown, None)
        message_type: Tipo da mensagem para analytics (pick_now, watch_upgrade, reminder, etc)
        game_id: ID do jogo relacionado (opcional)
        ext_id: ID externo do jogo (opcional)
        skip_rate_limit: Se True, ignora rate limiting (usar apenas para mensagens críticas)
    """
    from utils.analytics_logger import log_telegram_send
    
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram não configurado (TOKEN/CHAT_ID ausentes).")
        log_telegram_send(
            message_type or "unknown",
            game_id=game_id,
            ext_id=ext_id,
            success=False,
            error="Telegram não configurado"
        )
        return
    
    # Verifica rate limiting (exceto para mensagens críticas)
    if not skip_rate_limit:
        from utils.telegram_rate_limiter import check_rate_limit, record_message_sent
        can_send, reason = check_rate_limit(message_type)
        if not can_send:
            logger.debug(f"⏸️ Mensagem suprimida (rate limit): {message_type} - {reason}")
            log_telegram_send(
                message_type or "unknown",
                game_id=game_id,
                ext_id=ext_id,
                success=False,
                error=f"Rate limit: {reason}"
            )
            return
    
    # Detecta tipo de mensagem automaticamente se não fornecido
    if not message_type:
        if "PICK" in text.upper() or "PALPITE" in text.upper():
            message_type = "pick_now"
        elif "WATCHLIST" in text.upper() or "UPGRADE" in text.upper():
            message_type = "watch_upgrade"
        elif "LEMBRETE" in text.upper() or "REMINDER" in text.upper():
            message_type = "reminder"
        elif "RESUMO" in text.upper() or "SUMMARY" in text.upper():
            message_type = "summary"
        elif "AO VIVO" in text.upper() or "LIVE" in text.upper():
            message_type = "live_opportunity"
        else:
            message_type = "unknown"
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:  # só inclui quando tem valor válido
        payload["parse_mode"] = parse_mode
    try:
        r = requests.post(url, json=payload, timeout=TELEGRAM_TIMEOUT)
        if r.status_code != 200:
            error_msg = f"HTTP {r.status_code}: {r.text[:300]}"
            logger.error("Telegram %s: %s", r.status_code, r.text[:300])
            log_telegram_send(
                message_type,
                game_id=game_id,
                ext_id=ext_id,
                success=False,
                error=error_msg
            )
        else:
            # Registra que mensagem foi enviada (rate limiting)
            if not skip_rate_limit:
                from utils.telegram_rate_limiter import record_message_sent
                record_message_sent(message_type)
            
            log_telegram_send(
                message_type,
                game_id=game_id,
                ext_id=ext_id,
                success=True,
                metadata={"message_length": len(text)}
            )
    except Exception as e:
        error_msg = str(e)[:500]
        logger.exception("Erro Telegram: %s", e)
        log_telegram_send(
            message_type,
            game_id=game_id,
            ext_id=ext_id,
            success=False,
            error=error_msg
        )


def h(b: str) -> str:
    """Helper para texto em negrito HTML."""
    return f"<b>{b}</b>"


def send_pick_message(game, pick) -> None:
    """
    Envia notificação de UM pick específico ao Telegram, via buffer.

    Renderiza usando fmt_pick_now_v2(game, pick) e envia via buffer existente
    (mesmo mecanismo de send_pick_with_buffer — message_type='pick_now').

    Se pick.notified_at já está setado, NÃO reenvia (idempotência).
    Não comita session — só envia mensagem.
    """
    # Idempotência: não reenvia se já notificado
    if getattr(pick, "notified_at", None) is not None:
        return

    # Import lazy pra evitar circular (e tolerar formatters em produção paralela)
    from utils.formatters import fmt_pick_now_v2
    from utils.telegram_message_buffer import add_to_buffer

    text = fmt_pick_now_v2(game, pick)

    metadata = {
        "team_home": getattr(game, "team_home", None),
        "team_away": getattr(game, "team_away", None),
        "market": getattr(pick, "market", None),
        "line": getattr(pick, "line", None),
        "pick_id": getattr(pick, "id", None),
    }

    buffered = add_to_buffer(
        message_type="pick_now",
        content=text,
        game_id=getattr(game, "id", None),
        ext_id=getattr(game, "ext_id", None),
        metadata=metadata,
    )

    if not buffered:
        # Buffer não aceitou — envia imediatamente
        tg_send_message(
            text,
            message_type="pick_now",
            game_id=getattr(game, "id", None),
            ext_id=getattr(game, "ext_id", None),
        )


def send_picks_for_game(game, session) -> int:
    """
    Envia mensagem(s) Telegram pra cada pick will_bet=True do game que ainda
    não foi notificado.

    Ordem garantida: match_result primeiro (se houver), total_goals depois.

    Retorna count de mensagens enfileiradas.

    Não comita — só flush via mark_pick_notified.
    """
    from utils.notification_tracker import should_notify_pick, mark_pick_notified

    count = 0
    if not hasattr(game, "picks") or not game.picks:
        return 0

    # Ordenação: match_result primeiro, depois total_goals (ou demais)
    ordered = sorted(game.picks, key=lambda p: 0 if p.market == "match_result" else 1)

    for pick in ordered:
        ok, _reason = should_notify_pick(pick, check_high_conf=True)
        if not ok:
            continue
        send_pick_message(game, pick)
        mark_pick_notified(pick, session)
        count += 1

    return count

