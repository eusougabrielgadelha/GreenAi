"""
Sistema de buffer para consolidar mensagens do Telegram.
Agrupa mensagens do mesmo tipo em uma janela de tempo.
"""
import os
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import pytz
from utils.logger import logger
from config.settings import ZONE


@dataclass
class BufferedMessage:
    """Mensagem em buffer aguardando consolidação."""
    message_type: str
    content: str
    game_id: Optional[int] = None
    ext_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(pytz.UTC))


class MessageBuffer:
    """
    Buffer para consolidar mensagens do mesmo tipo.
    """
    
    def __init__(self):
        # Buffers por tipo de mensagem
        self._buffers: Dict[str, List[BufferedMessage]] = {}
        
        # Configurações de consolidação por tipo
        self._buffer_configs = {
            "pick_now": {
                "window_seconds": int(os.getenv("TELEGRAM_PICK_BUFFER_SECONDS", "300")),  # 5 minutos
                "max_items": int(os.getenv("TELEGRAM_PICK_BUFFER_MAX", "10")),  # Máximo 10 picks
                "enabled": os.getenv("TELEGRAM_PICK_BUFFER_ENABLED", "true").lower() == "true"
            },
            "watch_upgrade": {
                "window_seconds": int(os.getenv("TELEGRAM_UPGRADE_BUFFER_SECONDS", "60")),  # 1 minuto
                "max_items": int(os.getenv("TELEGRAM_UPGRADE_BUFFER_MAX", "20")),  # Máximo 20 upgrades
                "enabled": os.getenv("TELEGRAM_UPGRADE_BUFFER_ENABLED", "true").lower() == "true"
            },
            "live_opportunity": {
                "window_seconds": int(os.getenv("TELEGRAM_LIVE_BUFFER_SECONDS", "180")),  # 3 minutos
                "max_items": int(os.getenv("TELEGRAM_LIVE_BUFFER_MAX", "5")),  # Máximo 5 oportunidades
                "enabled": False  # Sempre desabilitado - oportunidades ao vivo devem ser enviadas imediatamente
            }
        }
        
        # Task de flush periódico
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False
    
    def add_message(self, message_type: str, content: str, game_id: Optional[int] = None, 
                   ext_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Adiciona mensagem ao buffer.
        
        Args:
            message_type: Tipo da mensagem
            content: Conteúdo da mensagem
            game_id: ID do jogo (opcional)
            ext_id: ID externo (opcional)
            metadata: Metadados adicionais (opcional)
            
        Returns:
            True se mensagem foi adicionada ao buffer, False se deve ser enviada imediatamente
        """
        config = self._buffer_configs.get(message_type)
        if not config or not config["enabled"]:
            return False  # Não usa buffer, enviar imediatamente
        
        if message_type not in self._buffers:
            self._buffers[message_type] = []
        
        msg = BufferedMessage(
            message_type=message_type,
            content=content,
            game_id=game_id,
            ext_id=ext_id,
            metadata=metadata or {}
        )
        
        self._buffers[message_type].append(msg)
        
        # Verifica se deve fazer flush imediato (muitos itens ou janela expirada)
        buffer = self._buffers[message_type]
        if len(buffer) >= config["max_items"]:
            # Buffer cheio, fazer flush
            asyncio.create_task(self._flush_buffer(message_type))
            return True
        
        # Inicia task de flush periódico se não estiver rodando
        if not self._running:
            self._start_flush_task()
        
        return True  # Mensagem adicionada ao buffer
    
    def _start_flush_task(self):
        """Inicia task de flush periódico."""
        if self._running:
            return
        
        self._running = True
        
        async def periodic_flush():
            while self._running:
                try:
                    await asyncio.sleep(30)  # Verifica a cada 30 segundos
                    await self._flush_expired_buffers()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.exception(f"Erro no flush periódico: {e}")
        
        self._flush_task = asyncio.create_task(periodic_flush())
    
    async def _flush_expired_buffers(self):
        """Faz flush de buffers que expiraram."""
        now = datetime.now(pytz.UTC)
        
        for message_type in list(self._buffers.keys()):
            config = self._buffer_configs.get(message_type)
            if not config:
                continue
            
            buffer = self._buffers[message_type]
            if not buffer:
                continue
            
            # Verifica se a janela expirou (primeira mensagem + window_seconds)
            first_msg = buffer[0]
            elapsed = (now - first_msg.timestamp).total_seconds()
            
            if elapsed >= config["window_seconds"]:
                await self._flush_buffer(message_type)
    
    async def _flush_buffer(self, message_type: str):
        """Faz flush de um buffer específico."""
        if message_type not in self._buffers:
            return
        
        buffer = self._buffers.pop(message_type)
        if not buffer:
            return
        
        # Para picks, agrupa por confiança e envia mensagens separadas
        if message_type == "pick_now":
            await self._flush_picks_by_confidence(buffer)
        else:
            # Para outros tipos, consolida normalmente
            consolidated = self._consolidate_messages(message_type, buffer)
            
            if consolidated:
                # Envia mensagem consolidada
                from notifications.telegram import tg_send_message
                tg_send_message(
                    consolidated,
                    parse_mode="HTML",
                    message_type=message_type,
                    game_id=buffer[0].game_id if buffer else None,
                    ext_id=f"consolidated_{len(buffer)}"
                )
                logger.info(f"📦 Mensagem consolidada enviada: {message_type} ({len(buffer)} itens)")
    
    async def _flush_picks_by_confidence(self, messages: List[BufferedMessage]):
        """Faz flush de picks agrupados por nível de confiança."""
        from config.settings import HIGH_CONF_THRESHOLD
        from models.database import SessionLocal, Game
        from notifications.telegram import tg_send_message
        
        # Agrupa mensagens por nível de confiança
        high_conf = []
        medium_conf = []
        low_conf = []
        
        with SessionLocal() as session:
            for msg in messages:
                game = None
                if msg.game_id:
                    game = session.query(Game).filter_by(id=msg.game_id).first()
                
                if game:
                    prob = game.pick_prob or 0.0
                    if prob >= HIGH_CONF_THRESHOLD:
                        high_conf.append(msg)
                    elif prob >= 0.40:
                        medium_conf.append(msg)
                    else:
                        low_conf.append(msg)
                else:
                    # Se não conseguir buscar o jogo, coloca na média (fallback)
                    medium_conf.append(msg)
        
        # Envia mensagem consolidada para cada nível de confiança
        if high_conf:
            consolidated = self._consolidate_picks_by_confidence(high_conf, "alta")
            if consolidated:
                tg_send_message(
                    consolidated,
                    parse_mode="HTML",
                    message_type="pick_now",
                    game_id=high_conf[0].game_id if high_conf else None,
                    ext_id=f"picks_high_{len(high_conf)}"
                )
                logger.info(f"📦 Picks de alta confiança enviados: {len(high_conf)} itens")
        
        if medium_conf:
            consolidated = self._consolidate_picks_by_confidence(medium_conf, "média")
            if consolidated:
                tg_send_message(
                    consolidated,
                    parse_mode="HTML",
                    message_type="pick_now",
                    game_id=medium_conf[0].game_id if medium_conf else None,
                    ext_id=f"picks_medium_{len(medium_conf)}"
                )
                logger.info(f"📦 Picks de média confiança enviados: {len(medium_conf)} itens")
        
        if low_conf:
            consolidated = self._consolidate_picks_by_confidence(low_conf, "baixa")
            if consolidated:
                tg_send_message(
                    consolidated,
                    parse_mode="HTML",
                    message_type="pick_now",
                    game_id=low_conf[0].game_id if low_conf else None,
                    ext_id=f"picks_low_{len(low_conf)}"
                )
                logger.info(f"📦 Picks de baixa confiança enviados: {len(low_conf)} itens")
    
    def _consolidate_messages(self, message_type: str, messages: List[BufferedMessage]) -> Optional[str]:
        """
        Consolida múltiplas mensagens em uma única.
        
        Args:
            message_type: Tipo da mensagem
            messages: Lista de mensagens para consolidar
            
        Returns:
            Mensagem consolidada ou None se não houver como consolidar
        """
        if not messages:
            return None
        
        if message_type == "pick_now":
            return self._consolidate_picks(messages)
        elif message_type == "watch_upgrade":
            return self._consolidate_upgrades(messages)
        elif message_type == "live_opportunity":
            return self._consolidate_live_opportunities(messages)
        
        # Fallback: junta todas as mensagens
        lines = [msg.content for msg in messages]
        return "\n\n".join(lines)
    
    def _consolidate_picks(self, messages: List[BufferedMessage]) -> str:
        """Consolida picks em uma mensagem única."""
        from utils.formatters import fmt_pick_now
        from models.database import SessionLocal, Game
        
        lines = [
            f"🎯 <b>NOVOS PICKS ({len(messages)})</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        # Agrupa por horário
        with SessionLocal() as session:
            for i, msg in enumerate(messages, 1):
                game = None
                if msg.game_id:
                    game = session.query(Game).filter_by(id=msg.game_id).first()
                
                if game:
                    # Usa formatação do formatter, mas adaptado para lista
                    pick_map = {
                        "home": game.team_home,
                        "draw": "Empate",
                        "away": game.team_away
                    }
                    pick_str = pick_map.get(game.pick, game.pick or "—")
                    
                    start_local = game.start_time.astimezone(ZONE)
                    time_str = start_local.strftime("%H:%M")
                    
                    pick_odd = 0.0
                    if game.pick == "home":
                        pick_odd = game.odds_home or 0
                    elif game.pick == "draw":
                        pick_odd = game.odds_draw or 0
                    elif game.pick == "away":
                        pick_odd = game.odds_away or 0
                    
                    prob = (game.pick_prob or 0) * 100
                    ev = (game.pick_ev or 0) * 100
                    
                    confidence = "🔥" if prob >= 60 else "⭐" if prob >= 40 else "💡"
                    
                    lines.append(
                        f"<b>{i}.</b> {confidence} <b>{game.team_home}</b> vs <b>{game.team_away}</b>\n"
                        f"   🕐 {time_str}h | Pick: <b>{pick_str}</b> @ {pick_odd:.2f}\n"
                        f"   📊 Prob: {prob:.0f}% | EV: {ev:+.1f}%"
                    )
                    lines.append("")
                else:
                    # Fallback: usa conteúdo original
                    lines.append(f"<b>{i}.</b> {msg.content}")
                    lines.append("")
        
        return "\n".join(lines)
    
    def _consolidate_picks_by_confidence(self, messages: List[BufferedMessage], confidence_level: str) -> str:
        """Consolida picks de um nível de confiança específico."""
        from models.database import SessionLocal, Game
        
        # Ícones e labels por nível
        confidence_config = {
            "alta": {"icon": "🔥", "label": "ALTA CONFIANÇA", "threshold": "≥60%"},
            "média": {"icon": "⭐", "label": "MÉDIA CONFIANÇA", "threshold": "40-60%"},
            "baixa": {"icon": "💡", "label": "BAIXA CONFIANÇA", "threshold": "<40%"}
        }
        
        config = confidence_config.get(confidence_level, {"icon": "🎯", "label": "CONFIANÇA", "threshold": ""})
        
        lines = [
            f"{config['icon']} <b>PICKS - {config['label']} ({config['threshold']})</b>",
            f"<i>{len(messages)} jogo(s)</i>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        with SessionLocal() as session:
            # Ordena por horário
            games_with_time = []
            for msg in messages:
                game = None
                if msg.game_id:
                    game = session.query(Game).filter_by(id=msg.game_id).first()
                if game:
                    games_with_time.append((game.start_time, game, msg))
            
            # Ordena por horário
            games_with_time.sort(key=lambda x: x[0])
            
            for i, (start_time, game, msg) in enumerate(games_with_time, 1):
                pick_map = {
                    "home": game.team_home,
                    "draw": "Empate",
                    "away": game.team_away
                }
                pick_str = pick_map.get(game.pick, game.pick or "—")
                
                start_local = game.start_time.astimezone(ZONE)
                time_str = start_local.strftime("%H:%M")
                
                pick_odd = 0.0
                if game.pick == "home":
                    pick_odd = game.odds_home or 0
                elif game.pick == "draw":
                    pick_odd = game.odds_draw or 0
                elif game.pick == "away":
                    pick_odd = game.odds_away or 0
                
                prob = (game.pick_prob or 0) * 100
                ev = (game.pick_ev or 0) * 100
                
                lines.append(
                    f"<b>{i}.</b> <b>{game.team_home}</b> vs <b>{game.team_away}</b>\n"
                    f"   🕐 {time_str}h | Pick: <b>{pick_str}</b> @ {pick_odd:.2f}\n"
                    f"   📊 Prob: {prob:.0f}% | EV: {ev:+.1f}%"
                )
                lines.append("")
        
        return "\n".join(lines)
    
    def _consolidate_upgrades(self, messages: List[BufferedMessage]) -> str:
        """Consolida upgrades da watchlist em uma mensagem única."""
        from utils.formatters import fmt_watch_upgrade
        from models.database import SessionLocal, Game
        
        lines = [
            f"⬆️ <b>UPGRADES DA WATCHLIST ({len(messages)})</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        # Agrupa por horário
        with SessionLocal() as session:
            for i, msg in enumerate(messages, 1):
                game = None
                if msg.game_id:
                    game = session.query(Game).filter_by(id=msg.game_id).first()
                
                if game:
                    pick_map = {
                        "home": game.team_home,
                        "draw": "Empate",
                        "away": game.team_away
                    }
                    pick_str = pick_map.get(game.pick, game.pick or "—")
                    
                    start_local = game.start_time.astimezone(ZONE)
                    time_str = start_local.strftime("%H:%M")
                    
                    pick_odd = 0.0
                    if game.pick == "home":
                        pick_odd = game.odds_home or 0
                    elif game.pick == "draw":
                        pick_odd = game.odds_draw or 0
                    elif game.pick == "away":
                        pick_odd = game.odds_away or 0
                    
                    prob = (game.pick_prob or 0) * 100
                    ev = (game.pick_ev or 0) * 100
                    
                    confidence = "🔥" if prob >= 60 else "⭐" if prob >= 40 else "💡"
                    
                    lines.append(
                        f"<b>{i}.</b> {confidence} <b>{game.team_home}</b> vs <b>{game.team_away}</b>\n"
                        f"   🕐 {time_str}h | Pick: <b>{pick_str}</b> @ {pick_odd:.2f}\n"
                        f"   📊 Prob: {prob:.0f}% | EV: {ev:+.1f}%"
                    )
                    lines.append("")
                else:
                    # Fallback: usa conteúdo original
                    lines.append(f"<b>{i}.</b> {msg.content}")
                    lines.append("")
        
        return "\n".join(lines)
    
    def _consolidate_live_opportunities(self, messages: List[BufferedMessage]) -> str:
        """Consolida oportunidades ao vivo em uma mensagem única."""
        from models.database import SessionLocal, Game
        
        lines = [
            f"⚡ <b>OPORTUNIDADES AO VIVO ({len(messages)})</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        with SessionLocal() as session:
            for i, msg in enumerate(messages, 1):
                game = None
                if msg.game_id:
                    game = session.query(Game).filter_by(id=msg.game_id).first()
                
                # Extrai informações da oportunidade dos metadados
                opportunity = msg.metadata.get("opportunity", {})
                stats = msg.metadata.get("stats", {})
                
                if game and opportunity:
                    match_time = stats.get('match_time', '—')
                    score = stats.get('score', '—')
                    option = opportunity.get('option', '—')
                    odd = opportunity.get('odd', 0.0)
                    est_p = opportunity.get("p_est", 0.0) * 100
                    stake = opportunity.get("stake", 0.0)
                    profit = opportunity.get("profit", 0.0)
                    confidence_score = stats.get('confidence_score', 0.0) * 100
                    
                    urgency = "🔥🔥🔥" if any(x in match_time for x in ["85","86","87","88","89","90"]) else "🔥"
                    
                    lines.append(
                        f"<b>{i}.</b> {urgency} <b>{game.team_home}</b> vs <b>{game.team_away}</b>\n"
                        f"   ⏱ {match_time} | Placar: {score}\n"
                        f"   💰 {option} @ {odd:.2f} | Prob: {est_p:.0f}%\n"
                        f"   📊 Confiança: {confidence_score:.0f}% | Aporte: R$ {stake:.2f} | Lucro: R$ {profit:.2f}"
                    )
                    lines.append("")
                else:
                    # Fallback: usa conteúdo original (mas simplificado)
                    # Remove cabeçalho e separadores para evitar duplicação
                    content = msg.content
                    if "━━━━━━━━━━━━━━━━━━━━" in content:
                        # Pega apenas a parte relevante após o separador
                        parts = content.split("━━━━━━━━━━━━━━━━━━━━")
                        if len(parts) > 1:
                            content = parts[1].strip()
                    
                    lines.append(f"<b>{i}.</b> {content}")
                    lines.append("")
        
        lines.append("\n⚡ <i>Aja rápido — odds ao vivo mudam!</i>")
        return "\n".join(lines)
    
    async def flush_all(self):
        """Faz flush de todos os buffers pendentes."""
        for message_type in list(self._buffers.keys()):
            await self._flush_buffer(message_type)
    
    def stop(self):
        """Para o sistema de buffer."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()


# Instância global
_message_buffer = MessageBuffer()


def add_to_buffer(message_type: str, content: str, game_id: Optional[int] = None,
                 ext_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> bool:
    """
    Adiciona mensagem ao buffer de consolidação.
    
    Returns:
        True se mensagem foi adicionada ao buffer, False se deve ser enviada imediatamente
    """
    return _message_buffer.add_message(message_type, content, game_id, ext_id, metadata)


async def flush_all_buffers():
    """Faz flush de todos os buffers pendentes."""
    await _message_buffer.flush_all()

