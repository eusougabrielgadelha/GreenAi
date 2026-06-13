"""Relatório semanal de auditoria de assertividade das combined_bets.

Lê as views v_combined_bet_kpis e v_combined_bet_audit e monta um HTML
compacto pro Telegram. Roda domingo 09:00 BRT.

Seções do relatório:
  1. KPIs por market (últimos 7 dias)
  2. KPIs all-time por market
  3. Últimas 7 combinadas (detalhe)
  4. Combinadas em 'unresolved' (sinal de saúde do scraping)
  5. Sumário operacional (pending atrasadas, sem outcome)

Idempotente: só leitura, sem efeitos colaterais.
"""
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

import pytz
from sqlalchemy import text
from sqlalchemy.orm import Session

from models.database import engine
from utils.formatters import esc


ZONE_BR = pytz.timezone("America/Sao_Paulo")


def _fmt_brl(v: Optional[float]) -> str:
    if v is None:
        return "—"
    s = f"R$ {abs(v):.2f}".replace(".", ",")
    return f"-{s}" if v < 0 else s


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:.1f}%"


def _fmt_int(v: Any) -> str:
    if v is None:
        return "0"
    return str(int(v))


def _fmt_date_short(dt: Any) -> str:
    """Aceita datetime ou string ISO ('YYYY-MM-DD ...' do SQLite). Retorna 'dd/mm'."""
    if dt is None:
        return "—"
    if isinstance(dt, str):
        # SQLite retorna 'YYYY-MM-DD HH:MM:SS[.ffffff]' — só preciso dos 10 primeiros chars
        s = dt[:10]
        try:
            y, m, d = s.split("-")
            return f"{int(d):02d}/{int(m):02d}"
        except (ValueError, IndexError):
            return esc(s)
    if not isinstance(dt, datetime):
        return esc(str(dt))
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(ZONE_BR).strftime("%d/%m")


def _query_kpis(window_start_utc: Optional[datetime]) -> list[dict]:
    """Roda v_combined_bet_kpis. Se window_start_utc, filtra por bet_date >= ele.
    Como v_combined_bet_kpis é agregada all-time, pra janela de 7 dias rodamos
    uma agregação ad-hoc no v_combined_bet_audit.
    """
    if window_start_utc is None:
        sql = "SELECT * FROM v_combined_bet_kpis ORDER BY market"
        params = {}
    else:
        sql = """
            SELECT
                market,
                COUNT(*) AS total,
                SUM(was_sent) AS sent,
                SUM(is_resolved_strict) AS resolved_strict,
                SUM(is_resolved_inclusive) AS resolved_inclusive,
                SUM(CASE WHEN status='won'  THEN 1 ELSE 0 END) AS won,
                SUM(CASE WHEN status='lost' THEN 1 ELSE 0 END) AS lost,
                SUM(CASE WHEN status='unresolved' THEN 1 ELSE 0 END) AS unresolved,
                SUM(CASE WHEN status='pending'    THEN 1 ELSE 0 END) AS pending,
                ROUND(100.0 * SUM(CASE WHEN status='won' THEN 1 ELSE 0 END)
                      / NULLIF(SUM(is_resolved_strict),0), 2) AS hit_rate_strict_pct,
                ROUND(100.0 * SUM(CASE WHEN status='won' THEN 1 ELSE 0 END)
                      / NULLIF(SUM(is_resolved_inclusive),0), 2) AS hit_rate_inclusive_pct,
                ROUND(AVG(combined_odd), 2) AS avg_combined_odd,
                ROUND(SUM(COALESCE(realized_pnl,0)), 2) AS total_pnl,
                ROUND(100.0 * SUM(COALESCE(realized_pnl,0))
                      / NULLIF(SUM(CASE WHEN was_sent=1 THEN example_stake ELSE 0 END),0), 2) AS roi_pct_on_sent
            FROM v_combined_bet_audit
            WHERE bet_date >= :start
            GROUP BY market
            ORDER BY market
        """
        params = {"start": window_start_utc.strftime("%Y-%m-%d %H:%M:%S.%f")}

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def _query_last_bets(limit: int = 7) -> list[dict]:
    sql = """
        SELECT id, market, bet_date, total_games, combined_odd, status, hit,
               was_sent, realized_pnl, resolution_reason
        FROM v_combined_bet_audit
        ORDER BY id DESC
        LIMIT :limit
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"limit": limit}).mappings().all()
    return [dict(r) for r in rows]


def _query_unresolved(limit: int = 10) -> list[dict]:
    sql = """
        SELECT id, market, bet_date, total_games, combined_odd, resolution_reason, age_days
        FROM v_combined_bet_audit
        WHERE status = 'unresolved'
        ORDER BY bet_date DESC
        LIMIT :limit
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"limit": limit}).mappings().all()
    return [dict(r) for r in rows]


def _query_pending_old(min_age_days: float = 1.5) -> list[dict]:
    """Pending muito velha = sinal de algum jogo sem outcome (Betano 403, cancelado, etc)."""
    sql = """
        SELECT id, market, bet_date, total_games, combined_odd, age_days
        FROM v_combined_bet_audit
        WHERE status = 'pending' AND age_days >= :min_age
        ORDER BY age_days DESC
        LIMIT 10
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"min_age": min_age_days}).mappings().all()
    return [dict(r) for r in rows]


def _kpi_block_lines(label: str, kpis: list[dict]) -> list[str]:
    """Bloco de KPIs por market — formato compacto."""
    out = [f"<b>{esc(label)}</b>"]
    if not kpis:
        out.append("<i>— sem dados —</i>")
        return out
    for k in kpis:
        market = esc(str(k.get("market") or "?"))
        total = _fmt_int(k.get("total"))
        sent = _fmt_int(k.get("sent"))
        won = _fmt_int(k.get("won"))
        lost = _fmt_int(k.get("lost"))
        unres = _fmt_int(k.get("unresolved"))
        pending = _fmt_int(k.get("pending"))
        hr_strict = _fmt_pct(k.get("hit_rate_strict_pct"))
        avg_odd = k.get("avg_combined_odd")
        avg_odd_s = f"{avg_odd:.2f}" if avg_odd is not None else "—"
        pnl = _fmt_brl(k.get("total_pnl"))
        roi = _fmt_pct(k.get("roi_pct_on_sent"))
        out.append(
            f"• <b>{market}</b>: {total} (env {sent}) | "
            f"W {won} / L {lost} / U {unres} / P {pending}\n"
            f"   hit rate <b>{hr_strict}</b> | odd média {avg_odd_s} | "
            f"PnL <b>{pnl}</b> | ROI <b>{roi}</b>"
        )
    return out


def _last_bets_lines(bets: Iterable[dict]) -> list[str]:
    out = ["<b>📜 Últimas 7 combinadas</b>"]
    icons = {"won": "✅", "lost": "❌", "unresolved": "⚪", "pending": "⏳"}
    for b in bets:
        icon = icons.get(str(b.get("status") or ""), "•")
        dia = _fmt_date_short(b.get("bet_date"))
        market = esc(str(b.get("market") or "?"))
        n = _fmt_int(b.get("total_games"))
        odd = b.get("combined_odd") or 0.0
        was_sent = "📤" if b.get("was_sent") else "💾"
        pnl = _fmt_brl(b.get("realized_pnl"))
        reason = b.get("resolution_reason") or ""
        reason_short = f" <i>({esc(reason[:32])}{'…' if len(reason) > 32 else ''})</i>" if reason else ""
        out.append(
            f"{icon} <code>#{b.get('id')}</code> {dia} {market} "
            f"{n}j @ {odd:.2f} {was_sent} {pnl}{reason_short}"
        )
    return out


def _unresolved_lines(rows: Iterable[dict]) -> list[str]:
    rows = list(rows)
    if not rows:
        return []
    out = ["<b>⚪ Combinadas unresolved (sinal de scraping)</b>"]
    for r in rows:
        dia = _fmt_date_short(r.get("bet_date"))
        market = esc(str(r.get("market") or "?"))
        reason = esc((r.get("resolution_reason") or "")[:60])
        out.append(f"• <code>#{r.get('id')}</code> {dia} {market} | {reason}")
    return out


def _pending_old_lines(rows: Iterable[dict]) -> list[str]:
    rows = list(rows)
    if not rows:
        return []
    out = ["<b>⏳ Pending atrasadas (&gt;36h)</b>"]
    for r in rows:
        dia = _fmt_date_short(r.get("bet_date"))
        market = esc(str(r.get("market") or "?"))
        age = r.get("age_days") or 0.0
        out.append(f"• <code>#{r.get('id')}</code> {dia} {market} ({age:.1f}d)")
    return out


def generate_weekly_audit_report(now_utc: Optional[datetime] = None) -> str:
    """Gera HTML do relatório semanal de auditoria de combined_bets."""
    if now_utc is None:
        now_utc = datetime.now(pytz.UTC)
    week_start = now_utc - timedelta(days=7)

    kpis_week = _query_kpis(week_start)
    kpis_all = _query_kpis(None)
    last_bets = _query_last_bets(limit=7)
    unresolved = _query_unresolved(limit=10)
    pending_old = _query_pending_old(min_age_days=1.5)

    now_br = now_utc.astimezone(ZONE_BR)

    lines: list[str] = []
    lines.append("📊 <b>RELATÓRIO SEMANAL — Auditoria de Múltiplas</b>")
    lines.append(f"<i>{now_br.strftime('%A, %d/%m/%Y %H:%M')}</i>")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.extend(_kpi_block_lines("🗓 Últimos 7 dias", kpis_week))
    lines.append("")
    lines.extend(_kpi_block_lines("📚 All-time", kpis_all))
    lines.append("")
    lines.extend(_last_bets_lines(last_bets))

    unres_block = _unresolved_lines(unresolved)
    if unres_block:
        lines.append("")
        lines.extend(unres_block)

    pend_block = _pending_old_lines(pending_old)
    if pend_block:
        lines.append("")
        lines.extend(pend_block)

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("<i>Legenda: W=won, L=lost, U=unresolved, P=pending. "
                 "📤 enviada · 💾 só registro. PnL líquido sobre stake R$10.</i>")

    msg = "\n".join(lines)
    # Telegram corta em 4096; trunca defensivo
    if len(msg) > 3900:
        msg = msg[:3900] + "\n…<i>(truncado)</i>"
    return msg
