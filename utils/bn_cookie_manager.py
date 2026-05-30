"""BetNacional cookie manager — fresh cookies via Playwright, persisted, lazy-reloaded.

Captura cookies frescos via Playwright (headless Chromium) e persiste em arquivo JSON.
O resto do sistema consome via `get_cookies()` para usar com `requests` (HTTP rápido).

Design:
- `refresh_cookies_async` é a forma preferida (chamar de APScheduler async).
- `refresh_cookies` (sync) só serve para scripts CLI / one-shot — usa `asyncio.run`.
- `get_cookies` é sync e nunca dispara refresh sozinho (evita deadlock em loop async).
  Quem chama é responsável por garantir refresh prévio.
"""
import os
import json
import asyncio
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pytz

from utils.logger import logger


# ---------------------------------------------------------------------------
# Config (env override-able)
# ---------------------------------------------------------------------------
COOKIES_FILE = Path(os.getenv("BN_COOKIES_FILE", "/opt/betauto/cookies/bn.json"))
BN_BOOTSTRAP_URL = os.getenv("BN_BOOTSTRAP_URL", "https://betnacional.bet.br/events/1/0/0")
BN_COOKIE_TTL_HOURS = int(os.getenv("BN_COOKIE_TTL_HOURS", "4"))

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Lock pra thread-safety em leitura/escrita de COOKIES_FILE
_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------
def _file_mtime() -> Optional[datetime]:
    """Retorna mtime do arquivo de cookies (UTC) ou None se não existir."""
    if not COOKIES_FILE.exists():
        return None
    try:
        ts = COOKIES_FILE.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=pytz.UTC)
    except OSError:
        return None


def _read_cookies_file() -> dict:
    """Lê o JSON e retorna o dict de cookies. Retorna {} se arquivo ausente / corrompido."""
    if not COOKIES_FILE.exists():
        return {}
    try:
        with open(COOKIES_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        cookies = payload.get("cookies", {})
        if isinstance(cookies, dict):
            return cookies
        logger.warning(f"Cookies BN: formato invalido em {COOKIES_FILE}")
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"Cookies BN: falha lendo {COOKIES_FILE}: {exc}")
        return {}


def _save_cookies(cookies: dict) -> None:
    """Atomic write: tmp file + os.replace."""
    COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = COOKIES_FILE.with_suffix(COOKIES_FILE.suffix + ".tmp")
    payload = {
        "cookies": cookies,
        "saved_at": datetime.now(pytz.UTC).isoformat(),
    }
    with _LOCK:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, COOKIES_FILE)
    logger.info(f"Cookies BN salvos em {COOKIES_FILE} (n={len(cookies)})")


async def _capture_cookies_with_playwright() -> dict:
    """
    Lança Playwright chromium headless, navega para BN_BOOTSTRAP_URL,
    aguarda networkidle + 3s, captura context.cookies().

    Returns:
        dict {nome: valor}. Em caso de erro, retorna {}.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        logger.exception(f"Playwright nao instalado: {exc}")
        return {}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                ctx = await browser.new_context(
                    user_agent=_UA,
                    locale="pt-BR",
                    viewport={"width": 1366, "height": 900},
                )
                page = await ctx.new_page()
                await page.goto(BN_BOOTSTRAP_URL, wait_until="networkidle", timeout=45000)
                # Tempo extra para Cloudflare resolver challenge se houver
                await page.wait_for_timeout(3000)
                raw_cookies = await ctx.cookies()
                return {c["name"]: c["value"] for c in raw_cookies}
            finally:
                await browser.close()
    except Exception as exc:
        logger.exception(f"Falha capturando cookies BN: {exc}")
        return {}


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def is_expired() -> bool:
    """True se arquivo nao existe ou mtime > BN_COOKIE_TTL_HOURS."""
    mtime = _file_mtime()
    if mtime is None:
        return True
    age = datetime.now(pytz.UTC) - mtime
    return age > timedelta(hours=BN_COOKIE_TTL_HOURS)


def get_cookies() -> dict:
    """
    Retorna dict {nome: valor} com cookies persistidos.

    NUNCA dispara refresh sozinho — apenas lê o arquivo.
    Se arquivo ausente ou corrompido, retorna {}.
    Thread-safe via lock.
    """
    with _LOCK:
        return _read_cookies_file()


def get_headers() -> dict:
    """
    Headers padrao pra usar com requests + cookies da BetNacional.
    """
    return {
        "User-Agent": _UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Referer": "https://betnacional.bet.br/",
        "Origin": "https://betnacional.bet.br",
    }


async def refresh_cookies_async(force: bool = False) -> dict:
    """
    Variante async — preferida em ambiente APScheduler async.

    Se force=False e arquivo recente (< TTL), retorna cached sem refresh.
    Caso contrario, captura via Playwright e persiste.

    Returns:
        dict {nome: valor}. Pode ser {} se captura falhar.
    """
    if not force and not is_expired():
        cached = get_cookies()
        if cached:
            logger.debug(f"Cookies BN: cache valido (n={len(cached)}), skip refresh")
            return cached

    logger.info(f"Cookies BN: refresh via Playwright (force={force})")
    cookies = await _capture_cookies_with_playwright()

    if cookies:
        _save_cookies(cookies)
    else:
        logger.warning("Cookies BN: captura retornou vazio, arquivo NAO atualizado")

    return cookies


def refresh_cookies(force: bool = False) -> dict:
    """
    Variante sync — pra scripts CLI / one-shot.

    AVISO: se ja houver um event loop ativo (ex: dentro de codigo async),
    isso vai falhar com `RuntimeError`. Nesse caso use `refresh_cookies_async`.

    Returns:
        dict {nome: valor}. Pode ser {} se captura falhar.
    """
    if not force and not is_expired():
        cached = get_cookies()
        if cached:
            logger.debug(f"Cookies BN: cache valido (n={len(cached)}), skip refresh")
            return cached

    try:
        return asyncio.run(refresh_cookies_async(force=force))
    except RuntimeError as exc:
        # Ja existe loop ativo — chamador deve usar refresh_cookies_async
        logger.error(
            f"refresh_cookies (sync) chamado dentro de event loop ativo: {exc}. "
            "Use refresh_cookies_async em codigo async."
        )
        return {}
