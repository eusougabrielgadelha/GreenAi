"""Backfill da combined_bet de 13/06/2026 08:00 BRT.

Em 13/06 às 08:00:05 o sistema selecionou os 10 jogos da múltipla. Às 08:00:11
o INSERT em `combined_bets` falhou com `(sqlite3.OperationalError) database is locked`.
O job retornou silenciosamente — a múltipla nunca foi gravada nem enviada.

Resultado: buraco permanente nas estatísticas históricas de assertividade.

Este script recupera os dados EXATOS do log do INSERT e cria a linha
manualmente. Idempotente: se já existir uma combined_bet com
`bet_date=2026-06-13` e `market='match_result'`, não faz nada.

Os dados (game_ids, picks, odds, combined_odd, avg_confidence, total_games)
vieram do log do parameters do INSERT que falhou:

    [parameters: ('match_result', '2026-06-13 00:00:00.000000',
        '[3358, 3611, 3623, 3226, 3783, 3582, 3598, 371, 3700, 846]',
        '["Shelbourne (F)", "FC Wacker Innsbruck", "Iskierka Szczecin",
          "Riga FC", "Asker", "Holbaek", "Altos", "Suíça",
          "Manchester United FC (Dominic) (Esports)", "Colo Colo"]',
        '[1.07, 1.07, 1.07, 1.08, 1.11, 1.16, 1.22, 1.27, 1.88, 1.31]',
        6.500529793488708, 10.0, 65.00529793488708, 0.7927983620435854,
        10, None, 'pending', None, None)]

Uso:
    python scripts/backfill_combined_bet_2026_06_13.py

Após o backfill, o resolver (betting/combined_bet_resolver.py) detecta a
linha em status=pending e aplica a máquina de estados na próxima execução
de `fetch_finished_games_results_job` (5min).
"""
import os
import sys
from datetime import datetime, timedelta

import pytz

# Permite rodar direto: python scripts/backfill_combined_bet_2026_06_13.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.database import CombinedBet, SessionLocal


BET_DATE_UTC = datetime(2026, 6, 13, 0, 0, 0, tzinfo=pytz.UTC)
MARKET = "match_result"

GAME_IDS = [3358, 3611, 3623, 3226, 3783, 3582, 3598, 371, 3700, 846]
PICKS = [
    "Shelbourne (F)",
    "FC Wacker Innsbruck",
    "Iskierka Szczecin",
    "Riga FC",
    "Asker",
    "Holbaek",
    "Altos",
    "Suíça",
    "Manchester United FC (Dominic) (Esports)",
    "Colo Colo",
]
ODDS = [1.07, 1.07, 1.07, 1.08, 1.11, 1.16, 1.22, 1.27, 1.88, 1.31]
COMBINED_ODD = 6.500529793488708
EXAMPLE_STAKE = 10.0
POTENTIAL_RETURN = 65.00529793488708
AVG_CONFIDENCE = 0.7927983620435854
TOTAL_GAMES = 10

RESOLUTION_REASON = (
    "manual_backfill:sqlite_locked_2026-06-13_08:00:11 — "
    "INSERT em combined_bets falhou no momento original; "
    "dados recuperados do log do SQLAlchemy"
)


def main() -> int:
    start_of_day = BET_DATE_UTC
    end_of_day = BET_DATE_UTC + timedelta(days=1)

    with SessionLocal() as session:
        existing = session.query(CombinedBet).filter(
            CombinedBet.bet_date >= start_of_day,
            CombinedBet.bet_date < end_of_day,
            CombinedBet.market == MARKET,
        ).first()

        if existing is not None:
            print(
                f"⏭️  já existe combined_bet id={existing.id} "
                f"(market={existing.market}, bet_date={existing.bet_date}, status={existing.status}). "
                "Nada a fazer."
            )
            return 0

        bet = CombinedBet(
            market=MARKET,
            bet_date=BET_DATE_UTC.replace(tzinfo=None),  # banco guarda naive UTC
            game_ids=GAME_IDS,
            picks=PICKS,
            odds=ODDS,
            combined_odd=COMBINED_ODD,
            example_stake=EXAMPLE_STAKE,
            potential_return=POTENTIAL_RETURN,
            avg_confidence=AVG_CONFIDENCE,
            total_games=TOTAL_GAMES,
            sent_at=None,  # NÃO foi enviada — auditoria precisa refletir isso
            status="pending",
            hit=None,
            outcome=None,
            resolution_reason=RESOLUTION_REASON,
            resolved_at=None,
        )
        session.add(bet)
        session.commit()
        session.refresh(bet)

        print(
            f"✅ backfill OK: combined_bet id={bet.id} "
            f"(market={bet.market}, total_games={bet.total_games}, "
            f"combined_odd={bet.combined_odd:.4f}, status={bet.status})"
        )
        print("   resolution_reason:", bet.resolution_reason)
        print(
            "   próximo passo: o resolver (fetch_finished_games_results_job) "
            "vai aplicar a máquina de estados na próxima rodada (5min)."
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
