"""Formatadores do relatório de assertividade.

Funções puras: recebem `List[DimensionStats]` + título, retornam string.
Inclui também helpers para gerar o relatório completo (4 dimensões) em
formato texto puro (terminal) e HTML (Telegram).
"""
from __future__ import annotations

from typing import List, Optional, Callable, Tuple

from utils.accuracy import (
    DimensionStats,
    accuracy_by_country,
    accuracy_by_competition,
    accuracy_by_team,
    accuracy_by_pick_type,
)


# ---------------------------------------------------------------------------
# Constantes de estilo
# ---------------------------------------------------------------------------

ANSI_GREEN = "\033[92m"
ANSI_RED = "\033[91m"
ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"

# Limites visuais
TERMINAL_MAX_WIDTH = 100
TELEGRAM_MAX_CHARS = 4096

# Larguras das colunas da tabela terminal (soma deve caber em 100 cols)
# Rank(4) | Nome(35) | Jogos(6) | Acertos(8) | Acc%(7) | Lucro u(10) | ROI%(8) | Odd média(10) = 88 + separadores
COL_RANK = 4
COL_NAME = 35
COL_GAMES = 6
COL_HITS = 8
COL_ACC = 7
COL_PROFIT = 10
COL_ROI = 8
COL_ODD = 10

# Telegram: tabela mais compacta (monospace)
TG_COL_RANK = 3
TG_COL_NAME = 18
TG_COL_GAMES = 5
TG_COL_ACC = 6
TG_COL_PROFIT = 8
TG_COL_ROI = 7


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _truncate(text: str, width: int) -> str:
    """Trunca string mantendo ellipsis '…' se exceder width."""
    if text is None:
        text = ""
    text = str(text)
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


def _pad_left(text: str, width: int) -> str:
    return _truncate(text, width).ljust(width)


def _pad_right(text: str, width: int) -> str:
    return _truncate(text, width).rjust(width)


def _color_for_roi(roi_pct: float) -> str:
    """Retorna código ANSI baseado no ROI%."""
    if roi_pct >= 10.0:
        return ANSI_GREEN
    if roi_pct <= -10.0:
        return ANSI_RED
    return ""


def _emoji_for_profit(profit: float) -> str:
    if profit > 0:
        return "🟢"
    if profit < 0:
        return "🔴"
    return "⚪"


def _fmt_pct(value: float) -> str:
    return f"{value:.1f}%"


def _fmt_acc(value: float) -> str:
    # accuracy vem 0.0–1.0 → exibir em %
    return f"{value * 100:.1f}%"


def _fmt_profit(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}u"


def _fmt_odd(value: float) -> str:
    return f"{value:.2f}"


# ---------------------------------------------------------------------------
# Tabela terminal
# ---------------------------------------------------------------------------

def format_terminal_table(stats: List[DimensionStats], title: str, top: int = 15) -> str:
    """Renderiza tabela ASCII colorida (ANSI) para terminal.

    Colunas: Rank | Nome | Jogos | Acertos | Acc% | Lucro u | ROI% | Odd média
    Cores por linha: verde ROI>=10%, vermelho ROI<=-10%, neutro caso contrário.
    Rodapé com totais.
    """
    lines: List[str] = []
    sep = "-" * TERMINAL_MAX_WIDTH

    header_title = f"{ANSI_BOLD}{title}{ANSI_RESET}"
    lines.append(header_title)
    lines.append(sep)

    if not stats:
        lines.append("(sem dados para os filtros aplicados)")
        lines.append(sep)
        return "\n".join(lines)

    header_cols = (
        _pad_left("#", COL_RANK)
        + " "
        + _pad_left("Nome", COL_NAME)
        + " "
        + _pad_right("Jogos", COL_GAMES)
        + " "
        + _pad_right("Acertos", COL_HITS)
        + " "
        + _pad_right("Acc%", COL_ACC)
        + " "
        + _pad_right("Lucro u", COL_PROFIT)
        + " "
        + _pad_right("ROI%", COL_ROI)
        + " "
        + _pad_right("Odd média", COL_ODD)
    )
    lines.append(header_cols)
    lines.append(sep)

    shown = stats[:top]
    total_games = 0
    total_profit = 0.0

    for idx, s in enumerate(shown, start=1):
        color = _color_for_roi(s.roi_pct)
        reset = ANSI_RESET if color else ""

        row = (
            _pad_left(str(idx), COL_RANK)
            + " "
            + _pad_left(s.name or "?", COL_NAME)
            + " "
            + _pad_right(str(s.total), COL_GAMES)
            + " "
            + _pad_right(str(s.hits), COL_HITS)
            + " "
            + _pad_right(_fmt_acc(s.accuracy), COL_ACC)
            + " "
            + _pad_right(_fmt_profit(s.profit_units), COL_PROFIT)
            + " "
            + _pad_right(_fmt_pct(s.roi_pct), COL_ROI)
            + " "
            + _pad_right(_fmt_odd(s.avg_odd), COL_ODD)
        )
        lines.append(f"{color}{row}{reset}")

    # Totais consideram a lista TODA (não apenas top), pra dar visão real
    for s in stats:
        total_games += s.total
        total_profit += s.profit_units

    lines.append(sep)
    footer = (
        f"Linhas exibidas: {len(shown)}/{len(stats)} | "
        f"Jogos (total): {total_games} | "
        f"Lucro total: {_fmt_profit(total_profit)}"
    )
    lines.append(footer)
    lines.append(sep)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Telegram HTML
# ---------------------------------------------------------------------------

def format_telegram_html(stats: List[DimensionStats], title: str, top: int = 10) -> str:
    """Renderiza mensagem HTML pro Telegram (sem ANSI).

    Estrutura:
        <b>📊 {title}</b>
        <pre>... tabela monospace ...</pre>
        Rodapé com totais.
    Limite 4096 chars (corta antes do fechamento de <pre> se necessário).
    """
    parts: List[str] = []
    parts.append(f"<b>📊 {title}</b>")

    if not stats:
        parts.append("<i>Sem dados para os filtros aplicados.</i>")
        return "\n".join(parts)

    shown = stats[:top]

    header = (
        _pad_left("#", TG_COL_RANK)
        + " "
        + _pad_left("Nome", TG_COL_NAME)
        + " "
        + _pad_right("Jg", TG_COL_GAMES)
        + " "
        + _pad_right("Acc%", TG_COL_ACC)
        + " "
        + _pad_right("Lucro", TG_COL_PROFIT)
        + " "
        + _pad_right("ROI%", TG_COL_ROI)
    )
    pre_lines: List[str] = [header, "-" * len(header)]

    for idx, s in enumerate(shown, start=1):
        emoji = _emoji_for_profit(s.profit_units)
        name = f"{emoji} {s.name or '?'}"
        row = (
            _pad_left(str(idx), TG_COL_RANK)
            + " "
            + _pad_left(name, TG_COL_NAME)
            + " "
            + _pad_right(str(s.total), TG_COL_GAMES)
            + " "
            + _pad_right(_fmt_acc(s.accuracy), TG_COL_ACC)
            + " "
            + _pad_right(_fmt_profit(s.profit_units), TG_COL_PROFIT)
            + " "
            + _pad_right(_fmt_pct(s.roi_pct), TG_COL_ROI)
        )
        pre_lines.append(row)

    table_block = "<pre>" + "\n".join(pre_lines) + "</pre>"
    parts.append(table_block)

    total_games = sum(s.total for s in stats)
    total_profit = sum(s.profit_units for s in stats)
    footer = (
        f"<i>Linhas: {len(shown)}/{len(stats)} • "
        f"Jogos: {total_games} • "
        f"Lucro: {_fmt_profit(total_profit)}</i>"
    )
    parts.append(footer)

    message = "\n".join(parts)

    # Garante limite Telegram (4096). Se passar, trunca preservando <pre> fechado.
    if len(message) > TELEGRAM_MAX_CHARS:
        # Corta mantendo abertura e fechando tags principais.
        cutoff = TELEGRAM_MAX_CHARS - 50  # margem pra tags de fechamento
        truncated = message[:cutoff]
        # Garante fechamento de <pre> se ficou aberto
        if "<pre>" in truncated and truncated.count("<pre>") > truncated.count("</pre>"):
            truncated += "</pre>"
        truncated += "\n<i>… (truncado)</i>"
        message = truncated

    return message


# ---------------------------------------------------------------------------
# Relatório completo (4 dimensões)
# ---------------------------------------------------------------------------

def _filters_header(period_days: Optional[int], min_games: int, confidence_min: Optional[float]) -> str:
    period_str = f"últimos {period_days} dias" if period_days else "lifetime"
    conf_str = f">= {confidence_min:.2f}" if confidence_min is not None else "qualquer"
    return (
        f"Período: {period_str} | "
        f"Mínimo de jogos: {min_games} | "
        f"Confiança: {conf_str}"
    )


def _dimensions_for_full() -> List[Tuple[str, Callable, dict]]:
    """Lista (título, função, kwargs extras) das 4 dimensões."""
    return [
        ("Assertividade por País", accuracy_by_country, {}),
        ("Assertividade por Competição", accuracy_by_competition, {}),
        ("Assertividade por Time", accuracy_by_team, {}),
        ("Assertividade por Tipo de Pick", accuracy_by_pick_type, {"is_pick_type": True}),
    ]


def format_full_report(
    session,
    period_days: Optional[int] = None,
    min_games: int = 5,
    confidence_min: Optional[float] = None,
    top: int = 15,
) -> str:
    """Relatório completo em texto puro (terminal) com as 4 dimensões."""
    sep = "=" * 60
    blocks: List[str] = []
    blocks.append(sep)
    blocks.append("RELATÓRIO DE ASSERTIVIDADE — Green AI")
    blocks.append(_filters_header(period_days, min_games, confidence_min))
    blocks.append(sep)

    any_data = False
    for title, fn, extras in _dimensions_for_full():
        is_pick_type = extras.get("is_pick_type", False)
        try:
            if is_pick_type:
                stats = fn(
                    session,
                    period_days=period_days,
                    confidence_min=confidence_min,
                )
            else:
                stats = fn(
                    session,
                    period_days=period_days,
                    min_games=min_games,
                    confidence_min=confidence_min,
                )
        except Exception as exc:  # pragma: no cover - protege CLI
            blocks.append(f"[{title}] erro ao calcular: {exc}")
            blocks.append(sep)
            continue

        if stats:
            any_data = True
        blocks.append(format_terminal_table(stats, title, top=top))
        blocks.append(sep)

    if not any_data:
        blocks.append("Nenhum dado disponível no banco para os filtros aplicados.")
        blocks.append(sep)

    return "\n".join(blocks)


def format_full_telegram(
    session,
    period_days: Optional[int] = None,
    min_games: int = 5,
    confidence_min: Optional[float] = None,
    top: int = 10,
) -> str:
    """Versão HTML pro Telegram. Concatena 4 seções com separadores."""
    sep = "━" * 20
    blocks: List[str] = []
    blocks.append("<b>📈 Relatório de Assertividade — Green AI</b>")
    blocks.append(f"<i>{_filters_header(period_days, min_games, confidence_min)}</i>")
    blocks.append(sep)

    any_data = False
    for title, fn, extras in _dimensions_for_full():
        is_pick_type = extras.get("is_pick_type", False)
        try:
            if is_pick_type:
                stats = fn(
                    session,
                    period_days=period_days,
                    confidence_min=confidence_min,
                )
            else:
                stats = fn(
                    session,
                    period_days=period_days,
                    min_games=min_games,
                    confidence_min=confidence_min,
                )
        except Exception as exc:  # pragma: no cover
            blocks.append(f"<b>{title}</b>\n<i>erro: {exc}</i>")
            blocks.append(sep)
            continue

        if stats:
            any_data = True
        blocks.append(format_telegram_html(stats, title, top=top))
        blocks.append(sep)

    if not any_data:
        blocks.append("<i>Nenhum dado disponível para os filtros aplicados.</i>")

    message = "\n".join(blocks)

    # Limite global de 4096 chars (margem de segurança)
    if len(message) > TELEGRAM_MAX_CHARS:
        cutoff = TELEGRAM_MAX_CHARS - 50
        truncated = message[:cutoff]
        if truncated.count("<pre>") > truncated.count("</pre>"):
            truncated += "</pre>"
        truncated += "\n<i>… (truncado)</i>"
        message = truncated

    return message


# ---------------------------------------------------------------------------
# Helper para CLI: gerar relatório de uma única dimensão
# ---------------------------------------------------------------------------

DIMENSION_REGISTRY = {
    "country": ("Assertividade por País", accuracy_by_country, False),
    "competition": ("Assertividade por Competição", accuracy_by_competition, False),
    "team": ("Assertividade por Time", accuracy_by_team, False),
    "pick": ("Assertividade por Tipo de Pick", accuracy_by_pick_type, True),
}


def render_single_dimension(
    session,
    dimension: str,
    period_days: Optional[int],
    min_games: int,
    confidence_min: Optional[float],
    top: int,
    telegram: bool = False,
) -> str:
    """Roda uma dimensão específica e retorna a string formatada."""
    if dimension not in DIMENSION_REGISTRY:
        raise ValueError(f"Dimensão desconhecida: {dimension}")

    title, fn, is_pick_type = DIMENSION_REGISTRY[dimension]
    if is_pick_type:
        stats = fn(session, period_days=period_days, confidence_min=confidence_min)
    else:
        stats = fn(
            session,
            period_days=period_days,
            min_games=min_games,
            confidence_min=confidence_min,
        )

    if telegram:
        header = (
            f"<b>📈 {title}</b>\n"
            f"<i>{_filters_header(period_days, min_games, confidence_min)}</i>\n"
        )
        return header + format_telegram_html(stats, title, top=top)

    header = (
        "=" * 60 + "\n"
        "RELATÓRIO DE ASSERTIVIDADE — Green AI\n"
        f"{_filters_header(period_days, min_games, confidence_min)}\n"
        + "=" * 60 + "\n"
    )
    return header + format_terminal_table(stats, title, top=top)
