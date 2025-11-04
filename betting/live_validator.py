"""
Sistema de validação de confiabilidade para oportunidades ao vivo.

ETAPA 1: Encontrar oportunidade (decide_live_bet_opportunity)
ETAPA 2: Validar confiabilidade (este módulo)
"""
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
import pytz
from models.database import SessionLocal, OddHistory, Game
from utils.logger import logger


def validate_opportunity_reliability(
    opportunity: Dict[str, Any],
    live_data: Dict[str, Any],
    game: Any,
    tracker: Any
) -> Tuple[bool, float, str]:
    """
    Valida se uma oportunidade encontrada é realmente confiável.
    
    Retorna:
        (is_reliable, confidence_score, reason)
        - is_reliable: True se a oportunidade é confiável
        - confidence_score: Score de confiança (0.0 a 1.0)
        - reason: Motivo da validação/rejeição
    """
    import os
    
    # Configurações de validação
    MIN_CONFIDENCE_SCORE = float(os.getenv("LIVE_MIN_CONFIDENCE_SCORE", "0.70"))
    REQUIRE_ODD_MOVEMENT = os.getenv("LIVE_REQUIRE_ODD_MOVEMENT", "false").lower() == "true"
    REQUIRE_STATISTICS = os.getenv("LIVE_REQUIRE_STATISTICS", "false").lower() == "true"
    
    stats = live_data.get("stats", {})
    markets = live_data.get("markets", {})
    match_time = stats.get("match_time", "") or ""
    
    confidence_factors = []
    rejection_reasons = []
    
    # ============================================
    # FATOR 1: Movimento de Odds (Comparação com odds iniciais)
    # ============================================
    odd_movement_score = 0.0
    with SessionLocal() as session:
        # Busca a primeira odd registrada (odd inicial)
        first_odd = (
            session.query(OddHistory)
            .filter(OddHistory.game_id == game.id)
            .order_by(OddHistory.timestamp.asc())
            .first()
        )
        
        if first_odd:
            # Compara odd atual com odd inicial
            current_odd = opportunity.get("odd", 0.0)
            market_key = opportunity.get("market_key", "")
            
            if market_key == "match_result":
                # Compara com odd do time correspondente
                option = opportunity.get("option", "")
                if option == "Casa":
                    initial_odd = first_odd.odds_home or 0.0
                elif option == "Fora":
                    initial_odd = first_odd.odds_away or 0.0
                else:
                    initial_odd = first_odd.odds_draw or 0.0
                
                if initial_odd > 0:
                    # Se a odd diminuiu (mais favorável), adiciona confiança
                    if current_odd < initial_odd:
                        movement_pct = ((initial_odd - current_odd) / initial_odd) * 100
                        odd_movement_score = min(0.3, movement_pct / 100)  # Máximo 30% de confiança
                        confidence_factors.append(("Movimento de odds favorável", odd_movement_score))
                    elif current_odd > initial_odd * 1.2:  # Odd aumentou mais de 20%
                        rejection_reasons.append(f"Odd aumentou significativamente ({initial_odd:.2f} → {current_odd:.2f})")
            
            # Para BTTS, não temos odd inicial específica, mas podemos verificar tendência
            if market_key == "btts" and not odd_movement_score:
                # Verifica se odds de resultado final mudaram (indicador indireto)
                if first_odd.odds_home and first_odd.odds_away:
                    # Se houve gols, odds devem ter mudado
                    home_goals = stats.get("home_goals", 0)
                    away_goals = stats.get("away_goals", 0)
                    if home_goals > 0 or away_goals > 0:
                        odd_movement_score = 0.15  # Confiança moderada
                        confidence_factors.append(("Odds ajustadas após gols", odd_movement_score))
        
        if REQUIRE_ODD_MOVEMENT and odd_movement_score == 0:
            rejection_reasons.append("Movimento de odds não detectado (requerido)")
    
    # ============================================
    # FATOR 2: Contexto do Placar e Tempo
    # ============================================
    context_score = 0.0
    home_goals = stats.get("home_goals", 0)
    away_goals = stats.get("away_goals", 0)
    
    # Extrai minuto do jogo
    match_minute = _extract_minute(match_time)
    
    if opportunity.get("market_key") == "btts" and opportunity.get("option") == "Não":
        # BTTS NÃO: mais confiável quanto mais tempo passar sem gols
        if match_minute >= 75:
            context_score = 0.25 + min(0.15, (match_minute - 75) / 100)  # Até 40% de confiança
            confidence_factors.append(("Tempo suficiente sem gols", context_score))
        else:
            rejection_reasons.append(f"Tempo insuficiente para BTTS NÃO (minuto {match_minute})")
    
    elif opportunity.get("market_key") == "match_result":
        # Resultado Final: mais confiável nos minutos finais com vantagem de 1 gol
        goal_diff = abs(home_goals - away_goals)
        if goal_diff == 1 and match_minute >= 85:
            context_score = 0.30  # Alta confiança em resultado nos minutos finais
            confidence_factors.append(("Resultado definido nos minutos finais", context_score))
        elif goal_diff > 1:
            context_score = 0.35  # Ainda mais confiável se vantagem maior
            confidence_factors.append(("Vantagem de múltiplos gols", context_score))
        elif goal_diff == 0 and match_minute >= 85:
            rejection_reasons.append("Jogo empatado nos minutos finais - resultado incerto")
    
    # ============================================
    # FATOR 3: Estabilidade da Oportunidade
    # ============================================
    stability_score = 0.0
    # Verifica se a oportunidade persiste (comparando com análise anterior)
    if tracker.last_pick_key == opportunity.get("pick_key", ""):
        # Se já detectamos essa oportunidade antes, ela é mais estável
        if tracker.last_analysis_time:
            time_since_last = (datetime.now(pytz.UTC) - tracker.last_analysis_time).total_seconds() / 60
            if time_since_last >= 3:  # Oportunidade persiste há pelo menos 3 minutos
                stability_score = 0.15
                confidence_factors.append(("Oportunidade estável", stability_score))
    else:
        # Nova oportunidade - requer mais validação
        stability_score = 0.05
        confidence_factors.append(("Nova oportunidade detectada", stability_score))
    
    # ============================================
    # FATOR 4: Edge e Probabilidade Estimada
    # ============================================
    edge_score = 0.0
    edge = opportunity.get("edge", 0.0)
    p_est = opportunity.get("p_est", 0.0)
    
    if edge >= 0.05:  # Edge alto
        edge_score = 0.20
        confidence_factors.append(("Edge alto", edge_score))
    elif edge >= 0.02:
        edge_score = 0.10
        confidence_factors.append(("Edge moderado", edge_score))
    
    if p_est >= 0.90:  # Probabilidade muito alta
        edge_score += 0.10
        confidence_factors.append(("Probabilidade muito alta", 0.10))
    
    # ============================================
    # FATOR 5: Eventos Recentes (se disponível)
    # ============================================
    event_score = 0.0
    last_event = stats.get("last_event", "")
    
    if last_event:
        # Se último evento foi gol, pode mudar dinâmica
        if "gol" in last_event.lower() or "goal" in last_event.lower():
            # Verifica se o evento favorece a oportunidade
            if opportunity.get("market_key") == "match_result":
                # Gol pode confirmar resultado
                event_score = 0.10
                confidence_factors.append(("Evento recente confirma tendência", event_score))
        elif "cartão" in last_event.lower() or "card" in last_event.lower():
            # Cartão pode indicar mudança de dinâmica (menor confiança)
            event_score = -0.05
            rejection_reasons.append("Cartão recente pode mudar dinâmica do jogo")
    
    # ============================================
    # FATOR 6: Análise de Mercado (Disponibilidade)
    # ============================================
    market_score = 0.0
    market_key = opportunity.get("market_key", "")
    market_data = markets.get(market_key, {})
    
    if market_data and market_data.get("options"):
        # Mercado está disponível e com múltiplas opções
        num_options = len(market_data.get("options", {}))
        if num_options >= 2:
            market_score = 0.05
            confidence_factors.append(("Mercado disponível e completo", market_score))
    
    # ============================================
    # CÁLCULO FINAL DO SCORE DE CONFIANÇA
    # ============================================
    total_confidence = (
        odd_movement_score +
        context_score +
        stability_score +
        edge_score +
        event_score +
        market_score
    )
    
    # Normaliza para 0.0 a 1.0
    total_confidence = min(1.0, max(0.0, total_confidence))
    
    # ============================================
    # DECISÃO FINAL
    # ============================================
    if rejection_reasons:
        # Se houver motivos de rejeição críticos, pode rejeitar mesmo com score alto
        critical_rejections = [r for r in rejection_reasons if any(
            word in r.lower() for word in ["aumentou significativamente", "incerto", "requerido"]
        )]
        if critical_rejections:
            reason = "; ".join(rejection_reasons)
            logger.info(f"❌ Oportunidade rejeitada por validação: {reason}")
            return False, total_confidence, reason
    
    if total_confidence >= MIN_CONFIDENCE_SCORE:
        reason = f"Validada (score: {total_confidence:.2f}) - " + "; ".join([f[0] for f in confidence_factors[:3]])
        logger.info(f"✅ Oportunidade validada com score {total_confidence:.2f}: {reason}")
        return True, total_confidence, reason
    else:
        reason = f"Score insuficiente ({total_confidence:.2f} < {MIN_CONFIDENCE_SCORE})"
        if confidence_factors:
            reason += " - Fatores: " + "; ".join([f[0] for f in confidence_factors[:2]])
        logger.info(f"⚠️ Oportunidade rejeitada: {reason}")
        return False, total_confidence, reason


def _extract_minute(match_time: str) -> int:
    """Extrai o minuto numérico do tempo do jogo."""
    if not match_time:
        return 0
    
    match_time_upper = match_time.upper()
    
    # Se já terminou
    if any(x in match_time_upper for x in ["FT", "FINAL", "FIM", "TERMINADO", "ENDED"]):
        return 90
    
    # Se está no intervalo
    if "HT" in match_time_upper or "INTERVALO" in match_time_upper:
        return 45
    
    # Extrai número do minuto
    import re
    numbers = re.findall(r'\d+', match_time)
    if numbers:
        try:
            return int(numbers[0])
        except:
            return 0
    
    return 0


def expand_live_game_stats(html: str) -> Dict[str, Any]:
    """
    Expande a extração de estatísticas do jogo ao vivo.
    Tenta extrair dados adicionais como:
    - Chutes (total, no gol)
    - Posse de bola
    - Cartões
    - Escanteios
    - Faltas
    - Etc.
    """
    from bs4 import BeautifulSoup
    
    soup = BeautifulSoup(html, "html.parser")
    expanded_stats = {}
    
    # Tenta encontrar containers de estatísticas
    # Nota: Estrutura pode variar, então tentamos múltiplas estratégias
    
    # Estratégia 1: Procurar por elementos com classes relacionadas a estatísticas
    stat_containers = soup.select('[class*="stat"], [class*="Stat"], [data-testid*="stat"], [data-testid*="Stat"]')
    
    for container in stat_containers:
        text = container.get_text(strip=True).lower()
        
        # Chutes
        if "chute" in text or "shot" in text:
            numbers = [int(x) for x in text.split() if x.isdigit()]
            if numbers:
                expanded_stats["shots"] = numbers[0] if numbers else None
        
        # Posse de bola
        if "posse" in text or "possession" in text:
            numbers = [int(x) for x in text.split() if x.isdigit()]
            if numbers:
                expanded_stats["possession"] = numbers[0] if numbers else None
        
        # Cartões
        if "cartão" in text or "card" in text or "amarelo" in text or "yellow" in text:
            # Tenta extrair número de cartões
            numbers = [int(x) for x in text.split() if x.isdigit()]
            if numbers:
                expanded_stats["yellow_cards"] = numbers[0] if numbers else None
        
        # Escanteios
        if "escanteio" in text or "corner" in text:
            numbers = [int(x) for x in text.split() if x.isdigit()]
            if numbers:
                expanded_stats["corners"] = numbers[0] if numbers else None
    
    # Estratégia 2: Procurar por tabelas ou listas de estatísticas
    # (pode ser implementada conforme necessário)
    
    return expanded_stats

