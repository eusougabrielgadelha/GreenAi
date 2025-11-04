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
    # FATOR 6: Análise de Estatísticas do Jogo
    # ============================================
    stats_score = 0.0
    
    # Verifica se há estatísticas disponíveis
    shots_home = stats.get("shots_home")
    shots_away = stats.get("shots_away")
    possession_home = stats.get("possession_home")
    corners_home = stats.get("corners_home")
    corners_away = stats.get("corners_away")
    
    if market_key == "match_result":
        # Para Resultado Final, analisa estatísticas que confirmam dominância
        leader = opportunity.get("option", "")
        if leader in ["Casa", "Fora"]:
            # Verifica se o time líder tem mais chutes/posse/escanteios
            if shots_home is not None and shots_away is not None:
                if leader == "Casa" and shots_home > shots_away:
                    stats_score += 0.05
                    confidence_factors.append(("Líder com mais chutes", 0.05))
                elif leader == "Fora" and shots_away > shots_home:
                    stats_score += 0.05
                    confidence_factors.append(("Líder com mais chutes", 0.05))
            
            if possession_home is not None:
                if leader == "Casa" and possession_home > 50:
                    stats_score += 0.03
                    confidence_factors.append(("Líder com mais posse", 0.03))
                elif leader == "Fora" and possession_home < 50:
                    stats_score += 0.03
                    confidence_factors.append(("Líder com mais posse", 0.03))
            
            if corners_home is not None and corners_away is not None:
                if leader == "Casa" and corners_home > corners_away:
                    stats_score += 0.02
                    confidence_factors.append(("Líder com mais escanteios", 0.02))
                elif leader == "Fora" and corners_away > corners_home:
                    stats_score += 0.02
                    confidence_factors.append(("Líder com mais escanteios", 0.02))
    
    elif market_key == "btts" and opportunity.get("option") == "Não":
        # Para BTTS NÃO, verifica se há poucos chutes (confirma que não vai ter gol)
        if shots_home is not None and shots_away is not None:
            total_shots = shots_home + shots_away
            if total_shots < 10:  # Poucos chutes no total
                stats_score += 0.08
                confidence_factors.append(("Poucos chutes no jogo", 0.08))
            elif total_shots < 15:
                stats_score += 0.04
                confidence_factors.append(("Chutes moderados", 0.04))
    
    # ============================================
    # FATOR 7: Análise de Momentum
    # ============================================
    momentum_score = 0.0
    
    # Verifica eventos recentes e padrão do jogo
    last_event = stats.get("last_event", "")
    home_goals = stats.get("home_goals", 0)
    away_goals = stats.get("away_goals", 0)
    
    if market_key == "match_result":
        leader = opportunity.get("option", "")
        goal_diff = abs(home_goals - away_goals)
        
        # Se o último evento foi gol do líder, confirma momentum
        if last_event:
            if leader == "Casa" and ("gol" in last_event.lower() or "goal" in last_event.lower()):
                if home_goals > away_goals:
                    momentum_score += 0.08
                    confidence_factors.append(("Momentum confirmado pelo último gol", 0.08))
            elif leader == "Fora" and ("gol" in last_event.lower() or "goal" in last_event.lower()):
                if away_goals > home_goals:
                    momentum_score += 0.08
                    confidence_factors.append(("Momentum confirmado pelo último gol", 0.08))
        
        # Se há vantagem de múltiplos gols, momentum é mais forte
        if goal_diff >= 2:
            momentum_score += 0.05
            confidence_factors.append(("Vantagem significativa", 0.05))
    
    # ============================================
    # FATOR 8: Análise de Tendência de Odds
    # ============================================
    trend_score = 0.0
    
    with SessionLocal() as session:
        # Busca últimas 3 odds registradas
        recent_odds = (
            session.query(OddHistory)
            .filter(OddHistory.game_id == game.id)
            .order_by(OddHistory.timestamp.desc())
            .limit(3)
            .all()
        )
        
        if len(recent_odds) >= 2:
            current_odd = opportunity.get("odd", 0.0)
            market_key = opportunity.get("market_key", "")
            
            if market_key == "match_result":
                option = opportunity.get("option", "")
                # Compara odd atual com odds anteriores
                prev_odds = []
                for oh in recent_odds[1:]:  # Pula a mais recente (já temos a atual)
                    if option == "Casa":
                        prev_odds.append(oh.odds_home or 0.0)
                    elif option == "Fora":
                        prev_odds.append(oh.odds_away or 0.0)
                    else:
                        prev_odds.append(oh.odds_draw or 0.0)
                
                # Verifica tendência: se odd está diminuindo consistentemente
                if len(prev_odds) >= 1 and prev_odds[0] > 0:
                    if current_odd < prev_odds[0]:
                        # Odd está caindo (mercado confirma)
                        trend_score = 0.10
                        confidence_factors.append(("Tendência de odds favorável", trend_score))
                    elif current_odd > prev_odds[0] * 1.15:
                        # Odd aumentou muito - pode indicar problema
                        rejection_reasons.append("Tendência de odds desfavorável (aumento significativo)")
    
    # ============================================
    # FATOR 9: Análise de Mercado (Disponibilidade)
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
        stats_score +
        momentum_score +
        trend_score +
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
            word in r.lower() for word in ["aumentou significativamente", "incerto", "requerido", "desfavorável"]
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
    - Chutes (total, no gol, fora)
    - Posse de bola
    - Cartões (amarelos, vermelhos)
    - Escanteios
    - Faltas
    - Finalizações perigosas
    """
    from bs4 import BeautifulSoup
    import re
    
    soup = BeautifulSoup(html, "html.parser")
    expanded_stats = {}
    
    # Estratégia 1: Procurar por elementos com classes relacionadas a estatísticas
    stat_containers = soup.select('[class*="stat"], [class*="Stat"], [data-testid*="stat"], [data-testid*="Stat"]')
    
    for container in stat_containers:
        text = container.get_text(strip=True).lower()
        
        # Chutes
        if "chute" in text or "shot" in text:
            numbers = re.findall(r'\d+', text)
            if numbers:
                try:
                    expanded_stats["shots_home"] = int(numbers[0]) if len(numbers) > 0 else None
                    expanded_stats["shots_away"] = int(numbers[1]) if len(numbers) > 1 else None
                    expanded_stats["shots_total"] = (int(numbers[0]) + int(numbers[1])) if len(numbers) > 1 else int(numbers[0])
                except (ValueError, IndexError):
                    pass
        
        # Chutes no gol
        if "chute no gol" in text or "shot on target" in text or "on target" in text:
            numbers = re.findall(r'\d+', text)
            if numbers:
                try:
                    expanded_stats["shots_on_target_home"] = int(numbers[0]) if len(numbers) > 0 else None
                    expanded_stats["shots_on_target_away"] = int(numbers[1]) if len(numbers) > 1 else None
                except (ValueError, IndexError):
                    pass
        
        # Posse de bola
        if "posse" in text or "possession" in text:
            numbers = re.findall(r'\d+', text)
            if numbers:
                try:
                    possession_home = int(numbers[0]) if len(numbers) > 0 else None
                    possession_away = int(numbers[1]) if len(numbers) > 1 else None
                    if possession_home is not None:
                        expanded_stats["possession_home"] = possession_home
                        expanded_stats["possession_away"] = possession_away if possession_away is not None else (100 - possession_home)
                except (ValueError, IndexError):
                    pass
        
        # Cartões amarelos
        if "cartão amarelo" in text or "yellow card" in text or ("amarelo" in text and "cartão" in text):
            numbers = re.findall(r'\d+', text)
            if numbers:
                try:
                    expanded_stats["yellow_cards_home"] = int(numbers[0]) if len(numbers) > 0 else None
                    expanded_stats["yellow_cards_away"] = int(numbers[1]) if len(numbers) > 1 else None
                    expanded_stats["yellow_cards_total"] = (int(numbers[0]) + int(numbers[1])) if len(numbers) > 1 else int(numbers[0])
                except (ValueError, IndexError):
                    pass
        
        # Cartões vermelhos
        if "cartão vermelho" in text or "red card" in text or ("vermelho" in text and "cartão" in text):
            numbers = re.findall(r'\d+', text)
            if numbers:
                try:
                    expanded_stats["red_cards_home"] = int(numbers[0]) if len(numbers) > 0 else None
                    expanded_stats["red_cards_away"] = int(numbers[1]) if len(numbers) > 1 else None
                    expanded_stats["red_cards_total"] = (int(numbers[0]) + int(numbers[1])) if len(numbers) > 1 else int(numbers[0])
                except (ValueError, IndexError):
                    pass
        
        # Escanteios
        if "escanteio" in text or "corner" in text:
            numbers = re.findall(r'\d+', text)
            if numbers:
                try:
                    expanded_stats["corners_home"] = int(numbers[0]) if len(numbers) > 0 else None
                    expanded_stats["corners_away"] = int(numbers[1]) if len(numbers) > 1 else None
                    expanded_stats["corners_total"] = (int(numbers[0]) + int(numbers[1])) if len(numbers) > 1 else int(numbers[0])
                except (ValueError, IndexError):
                    pass
        
        # Faltas
        if "falta" in text or "foul" in text:
            numbers = re.findall(r'\d+', text)
            if numbers:
                try:
                    expanded_stats["fouls_home"] = int(numbers[0]) if len(numbers) > 0 else None
                    expanded_stats["fouls_away"] = int(numbers[1]) if len(numbers) > 1 else None
                except (ValueError, IndexError):
                    pass
    
    # Estratégia 2: Procurar por tabelas de estatísticas
    stat_tables = soup.select('table[class*="stat"], table[class*="Stat"], [data-testid*="stats-table"]')
    for table in stat_tables:
        rows = table.select('tr')
        for row in rows:
            cells = row.select('td, th')
            if len(cells) >= 3:
                label_text = cells[0].get_text(strip=True).lower()
                home_value = cells[1].get_text(strip=True)
                away_value = cells[2].get_text(strip=True)
                
                # Extrai números
                home_num = re.findall(r'\d+', home_value)
                away_num = re.findall(r'\d+', away_value)
                
                if home_num and away_num:
                    try:
                        if "chute" in label_text or "shot" in label_text:
                            expanded_stats["shots_home"] = int(home_num[0])
                            expanded_stats["shots_away"] = int(away_num[0])
                        elif "posse" in label_text or "possession" in label_text:
                            expanded_stats["possession_home"] = int(home_num[0])
                            expanded_stats["possession_away"] = int(away_num[0])
                        elif "escanteio" in label_text or "corner" in label_text:
                            expanded_stats["corners_home"] = int(home_num[0])
                            expanded_stats["corners_away"] = int(away_num[0])
                        elif "cartão" in label_text or "card" in label_text:
                            if "amarelo" in label_text or "yellow" in label_text:
                                expanded_stats["yellow_cards_home"] = int(home_num[0])
                                expanded_stats["yellow_cards_away"] = int(away_num[0])
                            elif "vermelho" in label_text or "red" in label_text:
                                expanded_stats["red_cards_home"] = int(home_num[0])
                                expanded_stats["red_cards_away"] = int(away_num[0])
                    except (ValueError, IndexError):
                        pass
    
    # Estratégia 3: Procurar por elementos de progresso/barra (posse de bola)
    progress_bars = soup.select('[class*="progress"], [class*="bar"], [style*="width"]')
    for bar in progress_bars:
        parent_text = bar.parent.get_text(strip=True).lower() if bar.parent else ""
        if "posse" in parent_text or "possession" in parent_text:
            # Tenta extrair porcentagem do style ou do texto
            style = bar.get("style", "")
            width_match = re.search(r'width[:\s]+(\d+)%', style)
            if width_match:
                try:
                    expanded_stats["possession_home"] = int(width_match.group(1))
                    expanded_stats["possession_away"] = 100 - int(width_match.group(1))
                except (ValueError, IndexError):
                    pass
    
    return expanded_stats

