"""Migration script: atualiza Games legacy BetNacional → ext_id Betano.

Faz matching cross-source: Games com ext_id legacy (9 dígitos, começando com 9)
são casados contra a overview atual da Betano por nome (normalizado + fuzzy)
e start_time (±30min). Quando há match:

- UPDATE in-place: troca ext_id, game_url e betradar_match_id para os
  valores Betano.
- MERGE: se já existe um Game Betano com o mesmo ext_id+start_time,
  move picks do legacy para o Betano (resolvendo conflitos de
  unique(game_id, market, line)) e deleta o legacy.

Idempotente: após a primeira execução bem-sucedida, os Games legacy
deixam de existir, então a 2ª passagem é no-op.

Commit por Game (não atômico global) — preserva progresso em caso
de falha parcial.

Uso:
    python scripts/migrate_legacy_to_betano.py
"""
import asyncio
import sys
import os
from datetime import timedelta
from difflib import SequenceMatcher

# Permite rodar direto: python scripts/migrate_legacy_to_betano.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.database import SessionLocal, Game, Pick
from scraping.betano import fetch_betano_overview

BETANO_BASE_URL = os.getenv("BETANO_BASE_URL", "https://www.betano.bet.br")


def _normalize_name(name: str) -> str:
    """Normaliza: lowercase, remove acentos, strip."""
    import unicodedata
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return s.lower().strip()


def _name_match(legacy_name: str, betano_name: str, threshold: float = 0.85) -> bool:
    """Match por nome com normalização + fuzzy fallback."""
    a = _normalize_name(legacy_name)
    b = _normalize_name(betano_name)
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


def _find_betano_match(legacy_game, betano_events: dict):
    """Procura evento Betano que bate com legacy_game.

    Critérios (todos exigidos):
      - ardSportId == 1 (futebol)
      - nome home + nome away batem (normalizado/fuzzy)
      - start_time dentro de ±30min do legacy
    """
    from datetime import datetime
    import pytz

    legacy_start = legacy_game.start_time
    if legacy_start and legacy_start.tzinfo is None:
        legacy_start = pytz.UTC.localize(legacy_start)

    for eid, ev in betano_events.items():
        if ev.get("ardSportId") != 1:
            continue
        # Times
        ps = ev.get("participants") or []
        b_home = next((p.get("name") for p in ps if p.get("isHome")), None)
        if b_home is None and ps:
            b_home = ps[0].get("name")
        b_away = next((p.get("name") for p in ps if not p.get("isHome")), None)
        if b_away is None and len(ps) > 1:
            b_away = ps[1].get("name")
        if not (b_home and b_away):
            continue
        # Match nome
        if not _name_match(legacy_game.team_home, b_home):
            continue
        if not _name_match(legacy_game.team_away, b_away):
            continue
        # Match start_time (±30min)
        st_ms = ev.get("startTime") or 0
        if not st_ms:
            continue
        b_start = datetime.fromtimestamp(st_ms / 1000, tz=pytz.UTC)
        if legacy_start and abs((b_start - legacy_start).total_seconds()) > 30 * 60:
            continue
        return ev
    return None


def _merge_legacy_into_betano(session, legacy_game, betano_game):
    """Move picks do legacy pro betano existente, depois deleta legacy.

    Resolve conflito de UniqueConstraint(game_id, market, line):
      - Se já existe pick equivalente no betano, mantém o registro
        mais recente (compara updated_at|created_at) e descarta o outro.
      - Caso contrário, reaponta a pick legacy pro game betano.

    Cascade ON DELETE no schema cuida de odd_history/tracker do legacy.
    """
    legacy_picks = list(session.query(Pick).filter_by(game_id=legacy_game.id).all())
    for lp in legacy_picks:
        existing = session.query(Pick).filter_by(
            game_id=betano_game.id,
            market=lp.market,
            line=lp.line,
        ).first()
        if existing:
            lp_ts = lp.updated_at or lp.created_at
            ex_ts = existing.updated_at or existing.created_at
            # Mantém o mais recente: se legacy é mais novo, copia campos pro existing.
            if lp_ts and ex_ts and lp_ts > ex_ts:
                existing.pick = lp.pick
                existing.pick_prob = lp.pick_prob
                existing.pick_ev = lp.pick_ev
                existing.pick_odd = lp.pick_odd
                existing.pick_reason = lp.pick_reason
                existing.will_bet = lp.will_bet
                if lp.notified_at:
                    existing.notified_at = lp.notified_at
            session.delete(lp)
        else:
            lp.game_id = betano_game.id
    session.flush()
    session.delete(legacy_game)
    session.flush()


def _is_legacy_ext_id(ext_id) -> bool:
    """ext_id legacy BetNacional: 9 dígitos, começa com '9'."""
    if not ext_id:
        return False
    s = str(ext_id)
    return len(s) == 9 and s.startswith("9") and s.isdigit()


async def main():
    overview = await fetch_betano_overview()
    if not overview:
        print("FAIL: overview Betano não acessível")
        return {"matched": 0, "merged": 0, "no_match": 0, "errors": 1}
    events = overview.get("events") or {}
    print(f"Betano overview: {len(events)} eventos")

    counters = {"matched": 0, "merged": 0, "no_match": 0, "errors": 0}

    with SessionLocal() as session:
        # Identifica Games legacy: ext_id 9 dígitos começando com 9
        candidates = session.query(Game).filter(
            Game.status == "scheduled",
            Game.outcome.is_(None),
        ).all()
        legacy_games = [g for g in candidates if _is_legacy_ext_id(g.ext_id)]
        print(f"\nGames legacy detectados: {len(legacy_games)}")

        for g in legacy_games:
            try:
                betano_ev = _find_betano_match(g, events)
                if not betano_ev:
                    print(f"  ⚠️  Sem match: [{g.id}] {g.team_home} vs {g.team_away}")
                    counters["no_match"] += 1
                    continue

                betano_ext_id = str(betano_ev.get("id"))
                betano_url = f"{BETANO_BASE_URL}{betano_ev.get('url', '')}"
                betano_betradar = betano_ev.get("betradarMatchId")

                # Verifica conflito: já existe Game com esse ext_id Betano?
                existing = session.query(Game).filter(
                    Game.ext_id == betano_ext_id,
                    Game.id != g.id,
                ).first()

                if existing:
                    # MERGE: move picks do legacy pro existing, delete legacy
                    print(
                        f"  🔀 MERGE [{g.id}] (legacy {g.ext_id}) "
                        f"INTO [{existing.id}] (betano {betano_ext_id}): "
                        f"{g.team_home} vs {g.team_away}"
                    )
                    _merge_legacy_into_betano(session, g, existing)
                    session.commit()
                    counters["merged"] += 1
                else:
                    # UPDATE in-place
                    print(
                        f"  ✏️  UPDATE [{g.id}] {g.ext_id} → {betano_ext_id} "
                        f"| {g.team_home} vs {g.team_away}"
                    )
                    g.ext_id = betano_ext_id
                    g.game_url = betano_url
                    if betano_betradar is not None:
                        try:
                            g.betradar_match_id = int(betano_betradar)
                        except (TypeError, ValueError):
                            pass
                    session.commit()
                    counters["matched"] += 1
            except Exception as exc:
                session.rollback()
                print(f"  ❌ ERRO [{g.id}]: {exc}")
                counters["errors"] += 1

    print(f"\nResumo: {counters}")
    return counters


if __name__ == "__main__":
    result = asyncio.run(main())
