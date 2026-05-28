"""CLI — Relatório de Assertividade do Green AI.

Uso:
    python scripts/accuracy_report.py                        # lifetime, todas dimensões, terminal
    python scripts/accuracy_report.py --period 30            # últimos 30 dias
    python scripts/accuracy_report.py --period 7 --min 3     # mínimo 3 jogos por dimensão
    python scripts/accuracy_report.py --confidence 0.6       # só picks com prob >= 60%
    python scripts/accuracy_report.py --dimension country    # só uma dimensão
    python scripts/accuracy_report.py --top 5                # top 5 por dimensão
    python scripts/accuracy_report.py --telegram             # envia pro Telegram (HTML)
    python scripts/accuracy_report.py --telegram --period 7  # combinado
"""
import os
import sys
from pathlib import Path

# Garante que o root do projeto esteja no sys.path ANTES de qualquer import local
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import argparse  # noqa: E402

from models.database import SessionLocal  # noqa: E402
from utils.accuracy_formatters import (  # noqa: E402
    format_full_report,
    format_full_telegram,
    render_single_dimension,
)


VALID_DIMENSIONS = ["country", "competition", "team", "pick", "all"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="accuracy_report",
        description="Relatório de assertividade dos picks do Green AI.",
    )
    parser.add_argument(
        "--period",
        type=int,
        default=None,
        help="Janela em dias (default: lifetime).",
    )
    parser.add_argument(
        "--min",
        type=int,
        default=5,
        dest="min_games",
        help="Mínimo de jogos por dimensão (default: 5). Ignorado em pick.",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=None,
        help="Filtro de probabilidade mínima do pick (0.0–1.0).",
    )
    parser.add_argument(
        "--dimension",
        type=str,
        choices=VALID_DIMENSIONS,
        default="all",
        help="Dimensão a reportar (default: all).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="Top N linhas por dimensão (default: 15 terminal / 10 telegram).",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Envia relatório HTML pro grupo configurado em .env.",
    )
    return parser


def _validate_confidence(value):
    if value is None:
        return
    if value < 0.0 or value > 1.0:
        print(f"[ERRO] --confidence precisa estar entre 0.0 e 1.0 (recebido: {value})", file=sys.stderr)
        sys.exit(2)


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    _validate_confidence(args.confidence)

    # top default depende do canal
    if args.top is None:
        top = 10 if args.telegram else 15
    else:
        top = max(1, args.top)

    session = SessionLocal()
    try:
        if args.telegram:
            if args.dimension == "all":
                message = format_full_telegram(
                    session,
                    period_days=args.period,
                    min_games=args.min_games,
                    confidence_min=args.confidence,
                    top=top,
                )
            else:
                message = render_single_dimension(
                    session,
                    dimension=args.dimension,
                    period_days=args.period,
                    min_games=args.min_games,
                    confidence_min=args.confidence,
                    top=top,
                    telegram=True,
                )

            if not message or not message.strip():
                print("[INFO] Nenhum dado para enviar (DB vazio ou filtros bloqueando tudo).")
                return 0

            from notifications.telegram import tg_send_message

            tg_send_message(message, parse_mode="HTML")
            print(f"[OK] Relatório enviado pro Telegram ({len(message)} chars).")
            return 0

        # Saída texto puro pro terminal
        if args.dimension == "all":
            output = format_full_report(
                session,
                period_days=args.period,
                min_games=args.min_games,
                confidence_min=args.confidence,
                top=top,
            )
        else:
            output = render_single_dimension(
                session,
                dimension=args.dimension,
                period_days=args.period,
                min_games=args.min_games,
                confidence_min=args.confidence,
                top=top,
                telegram=False,
            )

        if not output or not output.strip():
            print("Nenhum dado encontrado para os filtros aplicados.")
            return 0

        print(output)
        return 0
    except Exception as exc:
        print(f"[ERRO] Falha ao gerar relatório: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            session.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
