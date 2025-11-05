"""Script para ler e consultar dados do banco de dados."""
import sys
from datetime import datetime, timedelta
import pytz
from sqlalchemy import func, Integer, and_

from models.database import SessionLocal, Game, LiveGameTracker, OddHistory
from config.settings import ZONE


def print_separator():
    """Imprime separador visual."""
    print("\n" + "="*60 + "\n")


def _label_for_outcome(game: Game, code: str) -> str:
    """Converte 'home/draw/away' no rótulo legível (time da casa/Empate/time de fora)."""
    if not code:
        return "N/A"
    code = (code or "").strip().lower()
    if code == "home":
        return game.team_home or "Casa"
    if code == "draw":
        return "Empate"
    if code == "away":
        return game.team_away or "Fora"
    return code


def show_summary():
    """Mostra resumo geral do banco."""
    with SessionLocal() as session:
        total = session.query(Game).count()
        scheduled = session.query(Game).filter(Game.status == "scheduled").count()
        live = session.query(Game).filter(Game.status == "live").count()
        ended = session.query(Game).filter(Game.status == "ended").count()
        selected = session.query(Game).filter(Game.will_bet == True).count()
        
        print("RESUMO DO BANCO DE DADOS")
        print(f"   Total de jogos: {total}")
        print(f"   [AGENDADOS] {scheduled}")
        print(f"   [AO VIVO] {live}")
        print(f"   [FINALIZADOS] {ended}")
        print(f"   [SELECIONADOS] {selected}")


def show_accuracy_stats():
    """Mostra estatísticas de acerto."""
    with SessionLocal() as session:
        ended_with_result = session.query(Game).filter(
            Game.status == "ended",
            Game.hit.isnot(None)
        ).all()
        
        if not ended_with_result:
            print("\nESTATISTICAS DE ACERTO")
            print("   Nenhum jogo finalizado com resultado ainda.")
            return
        
        total = len(ended_with_result)
        hits = sum(1 for g in ended_with_result if g.hit)
        accuracy = (hits / total * 100) if total > 0 else 0
        
        # Por pick
        by_pick = {}
        for game in ended_with_result:
            pick = game.pick or "N/A"
            if pick not in by_pick:
                by_pick[pick] = {"total": 0, "hits": 0}
            by_pick[pick]["total"] += 1
            if game.hit:
                by_pick[pick]["hits"] += 1
        
        print("\nESTATISTICAS DE ACERTO")
        print(f"   Taxa geral: {accuracy:.2f}% ({hits}/{total})")
        
        if by_pick:
            print("\n   Por tipo de pick:")
            for pick, stats in sorted(by_pick.items()):
                acc = (stats["hits"] / stats["total"] * 100) if stats["total"] > 0 else 0
                print(f"   • {pick}: {acc:.2f}% ({stats['hits']}/{stats['total']})")


def show_finished_games_with_results(limit=50):
    """Mostra jogos finalizados com resultados (acerto/erro)."""
    with SessionLocal() as session:
        finished_games = session.query(Game).filter(
            Game.status == "ended",
            Game.hit.isnot(None)
        ).order_by(Game.start_time.desc()).limit(limit).all()
        
        if not finished_games:
            print("\nJOGOS FINALIZADOS COM RESULTADO")
            print("   Nenhum jogo finalizado com resultado ainda.")
            return
        
        hits = sum(1 for g in finished_games if g.hit)
        total = len(finished_games)
        accuracy = (hits / total * 100) if total > 0 else 0
        
        print(f"\nJOGOS FINALIZADOS COM RESULTADO ({total})")
        print(f"   Taxa de acerto: {accuracy:.2f}% ({hits}/{total})")
        print("\n" + "-"*60)
        
        for game in finished_games:
            start_local = game.start_time.astimezone(ZONE) if game.start_time else None
            start_str = start_local.strftime("%d/%m/%Y %H:%M") if start_local else "N/A"
            
            # Destaque para acerto/erro
            if game.hit:
                result_label = ">>> ACERTOU <<<"
                result_symbol = "[+]"
            else:
                result_label = ">>> ERROU <<<"
                result_symbol = "[-]"
            
            print(f"\n{result_symbol} {result_label}")
            print(f"   {game.team_home} vs {game.team_away}")
            print(f"   {game.competition or 'N/A'} - {start_str}")
            
            if game.pick:
                pick_label = _label_for_outcome(game, game.pick)
                outcome_label = _label_for_outcome(game, game.outcome) if game.outcome else "N/A"
                print(f"   Pick: {pick_label} | Resultado real: {outcome_label}")
                if game.will_bet:
                    print(f"   [SELECIONADO PARA APOSTAR]")
            
            print("-"*60)


def show_recent_games(limit=10):
    """Mostra jogos recentes."""
    with SessionLocal() as session:
        games = session.query(Game).order_by(
            Game.start_time.desc()
        ).limit(limit).all()
        
        if not games:
            print("\nULTIMOS JOGOS")
            print("   Nenhum jogo encontrado.")
            return
        
        print(f"\nULTIMOS {limit} JOGOS")
        for game in games:
            status_label = {
                "scheduled": "[AGENDADO]",
                "live": "[AO VIVO]",
                "ended": "[FINALIZADO]"
            }.get(game.status, "[?]")
            
            start_local = game.start_time.astimezone(ZONE) if game.start_time else None
            start_str = start_local.strftime("%d/%m %H:%M") if start_local else "N/A"
            
            print(f"\n   {status_label} {game.team_home} vs {game.team_away}")
            print(f"      {game.competition or 'N/A'} - {start_str}")
            
            if game.pick:
                prob_str = f"{game.pick_prob:.1%}" if game.pick_prob else "N/A"
                ev_str = f"{game.pick_ev:.3f}" if game.pick_ev else "N/A"
                print(f"      Pick: {game.pick} (prob: {prob_str}, EV: {ev_str})")
            
            if game.will_bet:
                print(f"      [SELECIONADO PARA APOSTAR]")
            
            # Destaque para resultado
            if game.hit is not None:
                if game.hit:
                    result_label = ">>> ACERTOU <<<"
                else:
                    result_label = ">>> ERROU <<<"
                print(f"      {result_label}")
                pick_label = _label_for_outcome(game, game.pick)
                outcome_label = _label_for_outcome(game, game.outcome) if game.outcome else "N/A"
                print(f"      Pick: {pick_label} | Resultado real: {outcome_label}")
            elif game.status == "ended":
                print(f"      [FINALIZADO SEM RESULTADO REGISTRADO]")


def show_live_games():
    """Mostra jogos ao vivo."""
    with SessionLocal() as session:
        live_games = session.query(Game).filter(Game.status == "live").all()
        
        if not live_games:
            print("\nJOGOS AO VIVO")
            print("   Nenhum jogo ao vivo no momento.")
            return
        
        print(f"\nJOGOS AO VIVO ({len(live_games)})")
        for game in live_games:
            tracker = game.tracker
            print(f"\n   {game.team_home} vs {game.team_away}")
            print(f"      {game.competition or 'N/A'}")
            
            if tracker:
                print(f"      Placar: {tracker.current_score or 'N/A'}")
                print(f"      Minuto: {tracker.current_minute or 'N/A'}")
                print(f"      Última análise: {tracker.last_analysis_time}")
                print(f"      Notificações: {tracker.notifications_sent}")
            
            if game.pick:
                print(f"      Pick: {game.pick} (prob: {game.pick_prob:.1%})")


def show_today_games():
    """Mostra jogos de hoje."""
    with SessionLocal() as session:
        now_utc = datetime.now(pytz.UTC)
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        games_today = session.query(Game).filter(
            Game.start_time >= today_start,
            Game.start_time < today_end
        ).order_by(Game.start_time).all()
        
        if not games_today:
            print("\nJOGOS DE HOJE")
            print("   Nenhum jogo encontrado para hoje.")
            return
        
        print(f"\nJOGOS DE HOJE ({len(games_today)})")
        
        scheduled_today = [g for g in games_today if g.status == "scheduled"]
        live_today = [g for g in games_today if g.status == "live"]
        ended_today = [g for g in games_today if g.status == "ended"]
        
        if scheduled_today:
            print(f"\n   [AGENDADOS] ({len(scheduled_today)}):")
            for game in scheduled_today:
                start_local = game.start_time.astimezone(ZONE)
                print(f"      {start_local.strftime('%H:%M')} - {game.team_home} vs {game.team_away}")
                if game.will_bet:
                    print(f"         [SELECIONADO] - Pick: {game.pick}")
        
        if live_today:
            print(f"\n   [AO VIVO] ({len(live_today)}):")
            for game in live_today:
                print(f"      {game.team_home} vs {game.team_away}")
                if game.tracker:
                    print(f"         Placar: {game.tracker.current_score}, Minuto: {game.tracker.current_minute}")
        
        if ended_today:
            print(f"\n   [FINALIZADOS] ({len(ended_today)}):")
            for game in ended_today:
                if game.hit is not None:
                    if game.hit:
                        result = ">>> ACERTOU <<<"
                    else:
                        result = ">>> ERROU <<<"
                    print(f"      {result} {game.team_home} vs {game.team_away}")
                    pick_label = _label_for_outcome(game, game.pick)
                    outcome_label = _label_for_outcome(game, game.outcome) if game.outcome else "N/A"
                    print(f"         Pick: {pick_label} | Resultado real: {outcome_label}")
                else:
                    print(f"      [?] {game.team_home} vs {game.team_away} (sem resultado registrado)")


def show_selected_games(limit=20):
    """Mostra jogos selecionados para apostar."""
    with SessionLocal() as session:
        selected = session.query(Game).filter(
            Game.will_bet == True
        ).order_by(Game.start_time.desc()).limit(limit).all()
        
        if not selected:
            print("\nJOGOS SELECIONADOS")
            print("   Nenhum jogo selecionado ainda.")
            return
        
        # Separar por status
        scheduled_sel = [g for g in selected if g.status == "scheduled"]
        live_sel = [g for g in selected if g.status == "live"]
        ended_sel = [g for g in selected if g.status == "ended"]
        
        print(f"\nJOGOS SELECIONADOS ({len(selected)})")
        
        # Jogos finalizados com destaque especial
        if ended_sel:
            print(f"\n   >>> FINALIZADOS ({len(ended_sel)}) <<<")
            for game in ended_sel:
                start_local = game.start_time.astimezone(ZONE) if game.start_time else None
                start_str = start_local.strftime("%d/%m/%Y %H:%M") if start_local else "N/A"
                
                print(f"\n   {game.team_home} vs {game.team_away}")
                print(f"      {game.competition or 'N/A'} - {start_str}")
                print(f"      Pick: {game.pick} (prob: {game.pick_prob:.1%}, EV: {game.pick_ev:.3f})")
                
                if game.pick_notified_at:
                    print(f"      [NOTIFICADO] em: {game.pick_notified_at.astimezone(ZONE).strftime('%d/%m/%Y %H:%M')}")
                
                # Resultado destacado
                if game.hit is not None:
                    if game.hit:
                        result_label = ">>> ACERTOU <<<"
                    else:
                        result_label = ">>> ERROU <<<"
                    print(f"      {result_label}")
                    pick_label = _label_for_outcome(game, game.pick)
                    outcome_label = _label_for_outcome(game, game.outcome) if game.outcome else "N/A"
                    print(f"      Pick: {pick_label} | Resultado real: {outcome_label}")
                else:
                    print(f"      [FINALIZADO SEM RESULTADO REGISTRADO]")
        
        # Jogos ao vivo
        if live_sel:
            print(f"\n   [AO VIVO] ({len(live_sel)}):")
            for game in live_sel:
                start_local = game.start_time.astimezone(ZONE) if game.start_time else None
                start_str = start_local.strftime("%d/%m/%Y %H:%M") if start_local else "N/A"
                print(f"      {game.team_home} vs {game.team_away} - {start_str}")
                print(f"         Pick: {game.pick} (prob: {game.pick_prob:.1%})")
                if game.tracker:
                    print(f"         Placar: {game.tracker.current_score}, Minuto: {game.tracker.current_minute}")
        
        # Jogos agendados
        if scheduled_sel:
            print(f"\n   [AGENDADOS] ({len(scheduled_sel)}):")
            for game in scheduled_sel:
                start_local = game.start_time.astimezone(ZONE) if game.start_time else None
                start_str = start_local.strftime("%d/%m/%Y %H:%M") if start_local else "N/A"
                print(f"      {game.team_home} vs {game.team_away} - {start_str}")
                print(f"         Pick: {game.pick} (prob: {game.pick_prob:.1%}, EV: {game.pick_ev:.3f})")
                if game.pick_notified_at:
                    print(f"         [NOTIFICADO] em: {game.pick_notified_at.astimezone(ZONE).strftime('%d/%m/%Y %H:%M')}")


def main():
    """Função principal."""
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "summary":
            show_summary()
        elif command == "accuracy":
            show_accuracy_stats()
        elif command == "finished" or command == "results":
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 50
            show_finished_games_with_results(limit)
        elif command == "recent":
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
            show_recent_games(limit)
        elif command == "live":
            show_live_games()
        elif command == "today":
            show_today_games()
        elif command == "selected":
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
            show_selected_games(limit)
        elif command == "all":
            show_summary()
            show_accuracy_stats()
            show_finished_games_with_results(30)
            show_selected_games(20)
            show_today_games()
            show_live_games()
            show_recent_games(10)
        else:
            print(f"Comando desconhecido: {command}")
            print("\nComandos disponíveis:")
            print("  python read_db.py summary    - Resumo geral")
            print("  python read_db.py accuracy   - Estatísticas de acerto")
            print("  python read_db.py finished [N] - Jogos finalizados com resultado (padrão: 50)")
            print("  python read_db.py recent [N] - Últimos N jogos (padrão: 10)")
            print("  python read_db.py live       - Jogos ao vivo")
            print("  python read_db.py today    - Jogos de hoje")
            print("  python read_db.py selected [N] - Jogos selecionados (padrão: 20)")
            print("  python read_db.py all       - Mostra tudo")
    else:
        # Mostra tudo por padrão
        show_summary()
        show_accuracy_stats()
        show_finished_games_with_results(30)
        show_selected_games(10)
        show_today_games()
        show_live_games()
        show_recent_games(5)


if __name__ == "__main__":
    try:
        main()
        print_separator()
    except Exception as e:
        print(f"\n[ERRO] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

