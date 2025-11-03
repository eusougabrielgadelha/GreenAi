"""Gerenciamento da watchlist."""
from datetime import datetime
from typing import Any, Callable, Dict
from models.database import Stat, SessionLocal


def stat_get(session, key: str, default=None):
    """Obtém uma estatística do banco."""
    st = session.query(Stat).filter_by(key=key).one_or_none()
    return (st.value if (st and st.value is not None) else default)


def stat_set(session, key: str, value):
    """Define uma estatística no banco."""
    st = session.query(Stat).filter_by(key=key).one_or_none()
    if st:
        st.value = value
    else:
        st = Stat(key=key, value=value)
        session.add(st)
    session.commit()


def wl_load(session) -> Dict[str, Any]:
    """Carrega a watchlist do banco."""
    return stat_get(session, "watchlist", {"items": []}) or {"items": []}


def wl_save(session, data: Dict[str, Any]) -> None:
    """Salva a watchlist no banco."""
    stat_set(session, "watchlist", data)


def wl_add(session, ext_id: str, link: str, start_time_utc: datetime) -> bool:
    """Adiciona um item à watchlist."""
    wl = wl_load(session)
    items = wl.get("items", [])
    if any((it.get("ext_id") == ext_id and it.get("start_time") == start_time_utc.isoformat()) for it in items):
        return False
    items.append({"ext_id": ext_id, "link": link, "start_time": start_time_utc.isoformat()})
    wl["items"] = items
    wl_save(session, wl)
    return True


def wl_remove(session, predicate: Callable) -> int:
    """Remove itens da watchlist baseado em um predicado."""
    wl = wl_load(session)
    before = len(wl.get("items", []))
    wl["items"] = [it for it in wl.get("items", []) if not predicate(it)]
    wl_save(session, wl)
    return before - len(wl["items"])


async def rescan_watchlist_job():
    """Rechecagem periódica da watchlist."""
    # Esta função será movida para scheduler/jobs.py
    # Mantida aqui apenas para compatibilidade
    pass

