"""
Validação end-to-end de coleta de jogos.

1) Coleta N URLs via fetch_events_from_link (XHR primário).
2) Persiste no DB (SQLite efêmero em :memory: ou DB padrão se --persist).
3) Mostra agrupamento por país × liga × dia + amostra.

Uso:
    python scripts/validate_collection.py            # 5 links, DB em memória
    python scripts/validate_collection.py 3          # 3 links
    python scripts/validate_collection.py 5 --persist  # salva no betauto.sqlite3
"""
import os
import sys
import asyncio
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("TELEGRAM_TOKEN", "validate")
os.environ.setdefault("TELEGRAM_CHAT_ID", "validate")

# DB efêmero por padrão pra não poluir o real
if "--persist" not in sys.argv:
    os.environ["DB_URL"] = "sqlite:///:memory:"

from config.settings import BETTING_LINKS, ZONE  # noqa: E402
from scraping.fetchers import fetch_events_from_link  # noqa: E402
from scraping.betnacional import parse_local_datetime  # noqa: E402
from models.database import Game, SessionLocal, init_database  # noqa: E402

init_database()


def _table(rows, headers):
    if not rows:
        print("  (vazio)")
        return
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    print("  " + "  ".join(str(h).ljust(w) for w, h in zip(widths, headers)))
    print("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        print("  " + "  ".join(str(c).ljust(w) for w, c in zip(widths, r)))


async def collect(max_links: int):
    links = list(BETTING_LINKS.items())[:max_links]
    print(f"\n{'='*72}")
    print(f" COLETA — {len(links)} link(s)")
    print(f"{'='*72}\n")

    all_events = []
    per_link = []

    for name, cfg in links:
        url = cfg["link"]
        try:
            events = await fetch_events_from_link(url, backend="auto")
            per_link.append((name, cfg["pais"], len(events), "OK"))
            for ev in events:
                all_events.append(ev)
            print(f"  ✅ {len(events):3d} eventos | {name}")
        except Exception as e:
            per_link.append((name, cfg["pais"], 0, f"ERRO: {type(e).__name__}"))
            print(f"  ❌ erro      | {name}: {type(e).__name__}")

    print(f"\n--- Resumo por link ---")
    _table(per_link, ["Link", "País config", "Eventos", "Status"])
    return all_events


def persist(events):
    saved = 0
    skipped = 0
    with SessionLocal() as s:
        for ev in events:
            ext_id = getattr(ev, "ext_id", None)
            if not ext_id:
                skipped += 1
                continue
            start_dt = parse_local_datetime(ev.start_local_str) if ev.start_local_str else None
            if start_dt is None:
                skipped += 1
                continue
            exists = s.query(Game).filter_by(ext_id=str(ext_id), start_time=start_dt).first()
            if exists:
                continue
            g = Game(
                ext_id=str(ext_id),
                source_link=ev.source_link,
                game_url=getattr(ev, "game_url", None),
                country=getattr(ev, "country", None) or None,
                competition=ev.competition,
                team_home=ev.team_home,
                team_away=ev.team_away,
                start_time=start_dt,
                odds_home=ev.odds_home,
                odds_draw=ev.odds_draw,
                odds_away=ev.odds_away,
                status="live" if getattr(ev, "is_live", False) else "scheduled",
            )
            s.add(g)
            saved += 1
        s.commit()
    return saved, skipped


def report():
    with SessionLocal() as s:
        games = s.query(Game).all()

    total = len(games)
    print(f"\n{'='*72}")
    print(f" DB — {total} jogo(s) persistido(s)")
    print(f"{'='*72}")

    if total == 0:
        print("  (vazio)")
        return

    # País × Liga
    by_country = Counter(g.country or "—" for g in games)
    by_league = Counter(g.competition or "—" for g in games)
    by_country_league = Counter((g.country or "—", g.competition or "—") for g in games)
    by_day = Counter(g.start_time.strftime("%Y-%m-%d") for g in games if g.start_time)
    by_status = Counter(g.status for g in games)
    no_odds = sum(1 for g in games if not (g.odds_home and g.odds_draw and g.odds_away))

    print(f"\n--- Por país ({len(by_country)} distintos) ---")
    _table([[n, c] for c, n in by_country.most_common()], ["#", "País"])

    print(f"\n--- Top 15 ligas ({len(by_league)} distintas) ---")
    _table([[n, l] for l, n in by_league.most_common(15)], ["#", "Liga"])

    print(f"\n--- País × Liga (top 15) ---")
    _table(
        [[n, c, l] for (c, l), n in by_country_league.most_common(15)],
        ["#", "País", "Liga"],
    )

    print(f"\n--- Por dia ---")
    _table([[n, d] for d, n in sorted(by_day.items())], ["#", "Dia"])

    print(f"\n--- Por status ---")
    _table([[n, st] for st, n in by_status.most_common()], ["#", "Status"])

    print(f"\n--- Qualidade ---")
    print(f"  Total:              {total}")
    print(f"  Sem todas as odds:  {no_odds} ({no_odds/total*100:.1f}%)")

    print(f"\n--- Amostra (5 jogos) ---")
    for i, g in enumerate(games[:5], 1):
        when = g.start_time.strftime("%Y-%m-%d %H:%M") if g.start_time else "—"
        print(f"  [{i}] {g.team_home} vs {g.team_away}")
        print(f"      country={g.country!r}  competition={g.competition!r}")
        print(f"      start={when}  ext_id={g.ext_id}")
        print(f"      odds={g.odds_home}/{g.odds_draw}/{g.odds_away}  status={g.status}")


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = int(args[0]) if args else 5
    events = await collect(n)
    if not events:
        print("\n⚠️ Nenhum evento coletado — abortando relatório.")
        return
    saved, skipped = persist(events)
    print(f"\n📥 Persistidos: {saved} novos | skipped: {skipped}")
    report()


if __name__ == "__main__":
    asyncio.run(main())
