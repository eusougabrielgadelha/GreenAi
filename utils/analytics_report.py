"""Geração de relatórios de analytics diários."""
from datetime import datetime, timedelta
from typing import Dict, List, Any
import pytz
from sqlalchemy import func, and_
from models.database import SessionLocal, AnalyticsEvent, Game
from config.settings import ZONE, MORNING_HOUR
from utils.logger import logger


def generate_daily_analytics_report(target_date: datetime.date) -> str:
    """
    Gera um relatório completo de analytics para uma data específica.
    
    Args:
        target_date: Data do relatório (no timezone ZONE)
    
    Returns:
        String formatada com o relatório completo
    """
    with SessionLocal() as session:
        # Calcula janela UTC para o dia
        day_start = ZONE.localize(datetime(target_date.year, target_date.month, target_date.day, 0, 0)).astimezone(pytz.UTC)
        day_end = ZONE.localize(datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59)).astimezone(pytz.UTC)
        
        # Busca todos os eventos do dia
        events = (
            session.query(AnalyticsEvent)
            .filter(
                and_(
                    AnalyticsEvent.timestamp >= day_start,
                    AnalyticsEvent.timestamp <= day_end
                )
            )
            .order_by(AnalyticsEvent.timestamp)
            .all()
        )
        
        if not events:
            return f"📊 RELATÓRIO DE ANALYTICS - {target_date.strftime('%d/%m/%Y')}\n\nNenhum evento registrado neste dia."
        
        # Agrupa por categoria e tipo
        by_category = {}
        by_type = {}
        for event in events:
            cat = event.event_category
            typ = event.event_type
            by_category.setdefault(cat, []).append(event)
            by_type.setdefault(typ, []).append(event)
        
        # Estatísticas gerais
        total_events = len(events)
        successful = sum(1 for e in events if e.success)
        failed = total_events - successful
        
        # Estatísticas por tipo
        extractions = by_type.get("extraction", [])
        calculations = by_type.get("calculation", [])
        decisions = by_type.get("decision", [])
        signals_sent = by_type.get("signal_sent", [])
        signals_suppressed = by_type.get("signal_suppression", [])
        telegram_sends = by_type.get("telegram_send", [])
        watchlist_actions = by_type.get("watchlist_action", [])
        live_opportunities = by_type.get("live_opportunity", [])
        
        # Estatísticas de extração
        extraction_stats = {
            "total": len(extractions),
            "successful": sum(1 for e in extractions if e.success),
            "failed": sum(1 for e in extractions if not e.success),
            "total_events_extracted": sum(e.event_data.get("events_count", 0) for e in extractions if e.success),
        }
        
        # Estatísticas de decisões
        decisions_stats = {
            "total": len(decisions),
            "will_bet_true": sum(1 for e in decisions if e.event_data.get("will_bet")),
            "will_bet_false": sum(1 for e in decisions if not e.event_data.get("will_bet")),
            "avg_prob": sum(e.event_data.get("pick_prob", 0) for e in decisions if e.event_data.get("pick_prob")) / len(decisions) if decisions else 0,
            "avg_ev": sum(e.event_data.get("pick_ev", 0) for e in decisions if e.event_data.get("pick_ev")) / len(decisions) if decisions else 0,
        }
        
        # Estatísticas de sinais
        signals_stats = {
            "sent": len(signals_sent),
            "suppressed": len(signals_suppressed),
            "suppression_reasons": {}
        }
        for e in signals_suppressed:
            reason = e.reason or "Sem motivo"
            signals_stats["suppression_reasons"][reason] = signals_stats["suppression_reasons"].get(reason, 0) + 1
        
        # Estatísticas de Telegram
        telegram_stats = {
            "total": len(telegram_sends),
            "successful": sum(1 for e in telegram_sends if e.success),
            "failed": sum(1 for e in telegram_sends if not e.success),
            "by_type": {}
        }
        for e in telegram_sends:
            msg_type = e.event_data.get("message_type", "unknown")
            telegram_stats["by_type"][msg_type] = telegram_stats["by_type"].get(msg_type, 0) + 1
        
        # Estatísticas de watchlist
        watchlist_stats = {
            "total_actions": len(watchlist_actions),
            "adds": sum(1 for e in watchlist_actions if e.event_data.get("action") == "add"),
            "removes": sum(1 for e in watchlist_actions if e.event_data.get("action") == "remove"),
            "upgrades": sum(1 for e in watchlist_actions if e.event_data.get("action") == "upgrade"),
        }
        
        # Estatísticas de oportunidades ao vivo
        live_stats = {
            "total_analyses": len(live_opportunities),
            "opportunities_found": sum(1 for e in live_opportunities if e.success),
            "no_opportunity": sum(1 for e in live_opportunities if not e.success),
        }
        
        # Monta o relatório
        report_lines = [
            f"📊 RELATÓRIO DE ANALYTICS - {target_date.strftime('%d/%m/%Y')}",
            "=" * 60,
            "",
            "📈 ESTATÍSTICAS GERAIS",
            f"  • Total de eventos: {total_events}",
            f"  • Sucessos: {successful} ({successful*100/total_events:.1f}%)",
            f"  • Falhas: {failed} ({failed*100/total_events:.1f}%)",
            "",
            "🔍 EXTRAÇÕES (Scraping)",
            f"  • Total de extrações: {extraction_stats['total']}",
            f"  • Sucessos: {extraction_stats['successful']}",
            f"  • Falhas: {extraction_stats['failed']}",
            f"  • Eventos extraídos: {extraction_stats['total_events_extracted']}",
            "",
            "🧮 CÁLCULOS E DECISÕES",
            f"  • Total de cálculos: {len(calculations)}",
            f"  • Total de decisões: {decisions_stats['total']}",
            f"  • Decisões positivas (will_bet=True): {decisions_stats['will_bet_true']}",
            f"  • Decisões negativas (will_bet=False): {decisions_stats['will_bet_false']}",
            f"  • Probabilidade média: {decisions_stats['avg_prob']*100:.1f}%",
            f"  • EV médio: {decisions_stats['avg_ev']*100:.1f}%",
            "",
            "📡 SINAIS",
            f"  • Sinais enviados: {signals_stats['sent']}",
            f"  • Sinais suprimidos: {signals_stats['suppressed']}",
        ]
        
        if signals_stats['suppression_reasons']:
            report_lines.append("  • Motivos de supressão:")
            for reason, count in sorted(signals_stats['suppression_reasons'].items(), key=lambda x: x[1], reverse=True):
                report_lines.append(f"    - {reason}: {count}")
        
        report_lines.extend([
            "",
            "📱 TELEGRAM",
            f"  • Total de mensagens: {telegram_stats['total']}",
            f"  • Enviadas com sucesso: {telegram_stats['successful']}",
            f"  • Falhas: {telegram_stats['failed']}",
        ])
        
        if telegram_stats['by_type']:
            report_lines.append("  • Mensagens por tipo:")
            for msg_type, count in sorted(telegram_stats['by_type'].items(), key=lambda x: x[1], reverse=True):
                report_lines.append(f"    - {msg_type}: {count}")
        
        report_lines.extend([
            "",
            "👀 WATCHLIST",
            f"  • Total de ações: {watchlist_stats['total_actions']}",
            f"  • Adições: {watchlist_stats['adds']}",
            f"  • Remoções: {watchlist_stats['removes']}",
            f"  • Upgrades: {watchlist_stats['upgrades']}",
            "",
            "⚽ JOGOS AO VIVO",
            f"  • Análises realizadas: {live_stats['total_analyses']}",
            f"  • Oportunidades encontradas: {live_stats['opportunities_found']}",
            f"  • Sem oportunidade: {live_stats['no_opportunity']}",
            "",
            "=" * 60,
        ])
        
        # Adiciona detalhes dos sinais suprimidos (amostra)
        if signals_suppressed:
            report_lines.append("\n📋 DETALHES DE SINAIS SUPRIMIDOS (amostra):")
            sample_size = min(10, len(signals_suppressed))
            for i, event in enumerate(signals_suppressed[:sample_size]):
                ext_id = event.ext_id or "N/A"
                reason = event.reason or "Sem motivo"
                prob = event.event_data.get("pick_prob", 0)
                ev = event.event_data.get("pick_ev", 0)
                report_lines.append(
                    f"  {i+1}. ID: {ext_id} | Prob: {prob*100:.1f}% | EV: {ev*100:.1f}% | Motivo: {reason}"
                )
            if len(signals_suppressed) > sample_size:
                report_lines.append(f"  ... e mais {len(signals_suppressed) - sample_size} sinais suprimidos")
        
        # Adiciona detalhes dos sinais enviados (amostra)
        if signals_sent:
            report_lines.append("\n✅ DETALHES DE SINAIS ENVIADOS (amostra):")
            sample_size = min(10, len(signals_sent))
            for i, event in enumerate(signals_sent[:sample_size]):
                ext_id = event.ext_id or "N/A"
                reason = event.reason or "Sem motivo"
                pick = event.event_data.get("pick", "N/A")
                prob = event.event_data.get("pick_prob", 0)
                ev = event.event_data.get("pick_ev", 0)
                report_lines.append(
                    f"  {i+1}. ID: {ext_id} | Pick: {pick} | Prob: {prob*100:.1f}% | EV: {ev*100:.1f}% | Motivo: {reason}"
                )
            if len(signals_sent) > sample_size:
                report_lines.append(f"  ... e mais {len(signals_sent) - sample_size} sinais enviados")
        
        return "\n".join(report_lines)


async def generate_and_save_daily_report(target_date: datetime.date) -> str:
    """
    Gera o relatório diário e salva em arquivo (opcional).
    Retorna o relatório formatado.
    """
    report = generate_daily_analytics_report(target_date)
    
    # Salva em arquivo (opcional)
    import os
    from config.settings import LOG_DIR
    
    report_dir = os.path.join(LOG_DIR, "analytics_reports")
    os.makedirs(report_dir, exist_ok=True)
    
    report_file = os.path.join(report_dir, f"analytics_{target_date.strftime('%Y%m%d')}.txt")
    try:
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)
        logger.info("📊 Relatório de analytics salvo em: %s", report_file)
    except Exception as e:
        logger.exception("Erro ao salvar relatório: %s", e)
    
    return report

