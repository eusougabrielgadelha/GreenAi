"""Backfill da combined_bet de 14/06/2026 08:00 BRT.

Em 14/06 às 08:01:48 o job rodou (atrasado por lock). Selecionou 10 jogos.
Tentou INSERT 3 vezes (08:02:18, 08:03:19, 08:04:19) — todas falharam com
`(sqlite3.OperationalError) database is locked`. Alerta operacional saiu
ok no Telegram, mas a múltipla nunca foi gravada.

Dados (recuperados do log do parameters do INSERT que falhou):

    parameters: ('match_result', '2026-06-14 00:00:00.000000',
        '[375, 3059, 4044, 4093, 4092, 3246, 3645, 3632, 4076, 4086]',
        '["Alemanha", "Real Tomayapo", "Central SC PE", "Mighty Wanderers",
          "Silver Strikers", "KI Klaksvik", "Raja de Casablanca",
          "Universidad Cesar Vallejo", "Valmiera FC", "FC Ebolowa (F)"]',
        '[1.05, 1.05, 1.21, 1.29, 1.35, 1.36, 1.4, 1.4, 1.39, 1.44]',
        12.395376404744253, 10.0, 123.95376404744253, 0.7176629176597462,
        10, None, 'pending', None, None)

Uso:
    python scripts/backfill_combined_bet_2026_06_14.py

Após o backfill, o resolver (betting/combined_bet_resolver.py) detecta a
linha e aplica a máquina de estados na próxima rodada de
`fetch_finished_games_results_job` (5min).
"""
import os
import sys
from datetime import datetime, timedelta

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.database import CombinedBet, SessionLocal


BET_DATE_UTC = datetime(2026, 6, 14, 0, 0, 0, tzinfo=pytz.UTC)
MARKET = "match_result"

GAME_IDS = [375, 3059, 4044, 4093, 4092, 3246, 3645, 3632, 4076, 4086]
PICKS = [
    "Alemanha",
    "Real Tomayapo",
    "Central SC PE",
    "Mighty Wanderers",
    "Silver Strikers",
    "KI Klaksvik",
    "Raja de Casablanca",
    "Universidad Cesar Vallejo",
    "Valmiera FC",
    "FC Ebolowa (F)",
]
ODDS = [1.05, 1.05, 1.21, 1.29, 1.35, 1.36, 1.4, 1.4, 1.39, 1.44]
COMBINED_ODD = 12.395376404744253
EXAMPLE_STAKE = 10.0
POTENTIAL_RETURN = 123.95376404744253
AVG_CONFIDENCE = 0.7176629176597462
TOTAL_GAMES = 10

RESOLUTION_REASON = (
    "manual_backfill:sqlite_locked_2026-06-14_08:00 — "
    "3 retries falharam com database is locked; "
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
                f"(market={existing.market}, status={existing.status}). Nada a fazer."
            )
            return 0

        bet = CombinedBet(
            market=MARKET,
            bet_date=BET_DATE_UTC.replace(tzinfo=None),
            game_ids=GAME_IDS,
            picks=PICKS,
            odds=ODDS,
            combined_odd=COMBINED_ODD,
            example_stake=EXAMPLE_STAKE,
            potential_return=POTENTIAL_RETURN,
            avg_confidence=AVG_CONFIDENCE,
            total_games=TOTAL_GAMES,
            sent_at=None,
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
        return 0


if __name__ == "__main__":
    sys.exit(main())
