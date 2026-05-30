"""Modelo de probabilidades de placar via distribuição Poisson bivariada.

Calibra λ_home, λ_away a partir das odds de 1x2 + Over/Under 2.5 e fornece
probabilidades de qualquer placar/linha de handicap/linha O/U arbitrária.

Módulo puro: sem I/O, sem efeitos colaterais.
"""
import math
import logging
import re
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)

# Constantes
# MAX_GOALS_TO_SUM = 15: tail truncation < 1e-6 pra λ até ~3.5 (cobre futebol real).
# Em λ=2.5 (favorito forte), MAX=10 deixa tail ~6e-5 — quebra somatórios precisos.
# MAX=15 é o sweet spot custo/precisão (256 -> 256, mas as PMFs caem rápido).
MAX_GOALS_TO_SUM = 15
LAMBDA_MIN = 0.1
LAMBDA_MAX = 6.0
# Tolerância pra checagens de soma — truncation pode causar pequenos desvios
# em λ extremos. Usar tol >= 1e-4 em asserts externos.
PROB_SUM_TOLERANCE = 1e-4

# Cache pra fatorial — barato e útil em loops apertados
_FACTORIAL_CACHE = [math.factorial(i) for i in range(MAX_GOALS_TO_SUM + 2)]

# Regex pra extrair linha do total_goals (ex: "Mais de 2.5", "Menos de 1.5")
_TOTAL_GOALS_LINE_RE = re.compile(r'^(mais|menos)\s+de\s+(\d+(?:\.\d+)?)$', re.IGNORECASE)


# ============================================================================
# Helpers privados de extração de odds (formato compatível com decision.py)
# ============================================================================

def _normalize_odd_value(val: Any) -> float:
    """Aceita float direto OU dict {'odd': float, ...}. Retorna 0.0 se inválido."""
    if isinstance(val, (int, float)):
        try:
            return float(val)
        except Exception:
            return 0.0
    if isinstance(val, dict):
        try:
            return float(val.get("odd", 0.0) or 0.0)
        except Exception:
            return 0.0
    return 0.0


# ============================================================================
# Probabilidades implícitas (remove vig)
# ============================================================================

def implied_probs_1x2(odd_home: float, odd_draw: float, odd_away: float) -> Tuple[float, float, float]:
    """
    Probabilidades implícitas normalizadas (remove vig).
    Retorna (p_home, p_draw, p_away) que somam 1.0.
    """
    if odd_home <= 1.0 or odd_draw <= 1.0 or odd_away <= 1.0:
        raise ValueError(f"Odds inválidas: {odd_home}, {odd_draw}, {odd_away} (todas devem ser > 1.0)")
    raw_h = 1.0 / odd_home
    raw_d = 1.0 / odd_draw
    raw_a = 1.0 / odd_away
    overround = raw_h + raw_d + raw_a
    if overround <= 0:
        raise ValueError("Overround inválido")
    return (raw_h / overround, raw_d / overround, raw_a / overround)


def implied_probs_over_under(odd_over: float, odd_under: float) -> Tuple[float, float]:
    """
    Probabilidades implícitas normalizadas do par Over/Under.
    Retorna (p_over, p_under) que somam 1.0.
    """
    if odd_over <= 1.0 or odd_under <= 1.0:
        raise ValueError(f"Odds inválidas: over={odd_over}, under={odd_under}")
    raw_o = 1.0 / odd_over
    raw_u = 1.0 / odd_under
    overround = raw_o + raw_u
    if overround <= 0:
        raise ValueError("Overround inválido")
    return (raw_o / overround, raw_u / overround)


# ============================================================================
# Poisson PMF + Joint
# ============================================================================

def poisson_pmf(k: int, lam: float) -> float:
    """P(X = k) com X ~ Poisson(lam). Implementado à mão (sem dependência scipy)."""
    if k < 0 or lam < 0:
        return 0.0
    if lam == 0:
        return 1.0 if k == 0 else 0.0
    try:
        fact = _FACTORIAL_CACHE[k] if k < len(_FACTORIAL_CACHE) else math.factorial(k)
        return math.exp(-lam) * (lam ** k) / fact
    except (OverflowError, ValueError):
        return 0.0


def score_probability(home_goals: int, away_goals: int, lam_home: float, lam_away: float) -> float:
    """P(home_goals, away_goals) sob Poisson bivariado independente."""
    return poisson_pmf(home_goals, lam_home) * poisson_pmf(away_goals, lam_away)


# ============================================================================
# Probabilidades derivadas (1x2, O/U)
# ============================================================================

def prob_outcomes_1x2(lam_home: float, lam_away: float) -> Tuple[float, float, float]:
    """Retorna P(home win), P(draw), P(away win) sob Poisson bivariado."""
    p_h = p_d = p_a = 0.0
    # Pré-calcula PMFs (cada lado independente)
    pmf_h = [poisson_pmf(i, lam_home) for i in range(MAX_GOALS_TO_SUM + 1)]
    pmf_a = [poisson_pmf(j, lam_away) for j in range(MAX_GOALS_TO_SUM + 1)]
    for i in range(MAX_GOALS_TO_SUM + 1):
        for j in range(MAX_GOALS_TO_SUM + 1):
            p = pmf_h[i] * pmf_a[j]
            if i > j:
                p_h += p
            elif i == j:
                p_d += p
            else:
                p_a += p
    return p_h, p_d, p_a


def prob_over_under(lam_home: float, lam_away: float, line: float) -> Tuple[float, float]:
    """
    Probabilidade de total de gols > line e <= line.
    Line tipicamente .5/.0 — descarta quartos pra simplicidade.
    Retorna (p_over, p_under).
    """
    pmf_h = [poisson_pmf(i, lam_home) for i in range(MAX_GOALS_TO_SUM + 1)]
    pmf_a = [poisson_pmf(j, lam_away) for j in range(MAX_GOALS_TO_SUM + 1)]
    p_over = 0.0
    p_under = 0.0
    for i in range(MAX_GOALS_TO_SUM + 1):
        for j in range(MAX_GOALS_TO_SUM + 1):
            p = pmf_h[i] * pmf_a[j]
            total = i + j
            if total > line:
                p_over += p
            else:
                p_under += p
    return p_over, p_under


# ============================================================================
# Calibração
# ============================================================================

def calibrate_lambdas(
    p_home: float, p_draw: float, p_away: float,
    p_over_2_5: float,
    max_iter: int = 50,
    tol: float = 1e-4,
) -> Optional[Tuple[float, float]]:
    """
    Calibra (lam_home, lam_away) que melhor ajustam p_home e p_over_2_5.

    Estratégia: minimização numérica do erro quadrático em 2 dimensões.

    Usa scipy.optimize.minimize(method='Nelder-Mead') se disponível, senão
    cai pra grid search 60x60.

    Retorna (lam_home, lam_away) ou None se não convergir.
    """

    def loss(params):
        lh, la = params
        if lh <= 0 or la <= 0 or lh > LAMBDA_MAX + 4 or la > LAMBDA_MAX + 4:
            return 1e6
        p_h_model, _p_d_model, _p_a_model = prob_outcomes_1x2(lh, la)
        p_over_model, _ = prob_over_under(lh, la, 2.5)
        # Erro quadrático em duas dimensões (suficiente: p_draw e p_away são
        # determinados pelo restante)
        return (p_h_model - p_home) ** 2 + (p_over_model - p_over_2_5) ** 2

    # Chute inicial — heurística:
    # total_goals_estimate ≈ aproximação grosseira via O/U 2.5
    # Se p_over_2_5 = 0.5 → ~2.5 gols totais esperados
    # Se p_over_2_5 = 0.7 → ~3.2 gols totais
    # share_home ≈ p_home / (p_home + p_away)  (ignora empate pra split)
    if (p_home + p_away) > 0:
        share_home = p_home / (p_home + p_away)
    else:
        share_home = 0.5
    # Total gols esperado: aproximação linear baseada em p_over_2_5
    total_est = 2.5 + (p_over_2_5 - 0.5) * 2.0
    total_est = max(0.5, min(5.5, total_est))
    x0 = [total_est * share_home, total_est * (1 - share_home)]
    # Clampa o chute inicial pra range razoável
    x0[0] = max(LAMBDA_MIN, min(LAMBDA_MAX, x0[0]))
    x0[1] = max(LAMBDA_MIN, min(LAMBDA_MAX, x0[1]))

    try:
        from scipy.optimize import minimize
        result = minimize(
            loss, x0, method='Nelder-Mead',
            options={'maxiter': max_iter * 10, 'xatol': tol, 'fatol': tol}
        )
        # success OU loss < 0.01 (Nelder-Mead pode terminar sem flag success)
        if result.success or result.fun < 0.01:
            lh, la = float(result.x[0]), float(result.x[1])
            if LAMBDA_MIN < lh < LAMBDA_MAX and LAMBDA_MIN < la < LAMBDA_MAX:
                logger.debug(f"calibrate_lambdas: scipy convergiu lh={lh:.3f} la={la:.3f} loss={result.fun:.6f}")
                return (lh, la)
            logger.debug(f"calibrate_lambdas: scipy fora do range lh={lh:.3f} la={la:.3f}")
    except ImportError:
        logger.debug("calibrate_lambdas: scipy indisponível, usando grid search")
    except Exception as e:
        logger.debug(f"calibrate_lambdas: scipy falhou ({e}), tentando grid search")

    # Fallback: grid search 60x60 (passo 0.1 de 0.5 a 6.0)
    best = None
    best_loss = float('inf')
    for lh_step in range(5, 65):  # 0.5 → 6.4
        for la_step in range(5, 65):
            lh = lh_step * 0.1
            la = la_step * 0.1
            l = loss((lh, la))
            if l < best_loss:
                best_loss = l
                best = (lh, la)
    if best and best_loss < 0.01:
        logger.debug(f"calibrate_lambdas: grid search lh={best[0]:.3f} la={best[1]:.3f} loss={best_loss:.6f}")
        return best
    logger.debug(f"calibrate_lambdas: não convergiu (best_loss={best_loss:.4f})")
    return None


# ============================================================================
# Handicap Asiático
# ============================================================================

def prob_handicap_asian(lam_home: float, lam_away: float, side: str, line: float) -> Dict[str, float]:
    """
    Probabilidade de handicap asiático vencer.

    side: 'home' ou 'away'
    line: float — pode ser .5 (sem push), .0 (com push), .25/.75 (quarter line)

    Retorna dict {'win': float, 'push': float, 'lose': float} que somam 1.0.

    Lógica:
      diff = home - away se side='home', senão away - home
      adjusted = diff + line

      Linha .5: adjusted > 0 → win; senão lose. Push = 0.
      Linha .0: adjusted > 0 → win; adjusted == 0 → push; senão lose.
      Linha .25/.75: split em 2 metades (linha de cima + linha de baixo).
    """
    if side not in ("home", "away"):
        raise ValueError(f"side inválido: {side!r}. Deve ser 'home' ou 'away'.")

    # Detecta quarter line — line*2 não é inteiro (ex: -1.25 → -2.5; .75 → 1.5)
    line_x2 = line * 2
    if abs(line_x2 - round(line_x2)) > 1e-9:
        # Quarter line — split em duas metades
        line_low = math.floor(line_x2) / 2.0
        line_high = math.ceil(line_x2) / 2.0
        r1 = prob_handicap_asian(lam_home, lam_away, side, line_low)
        r2 = prob_handicap_asian(lam_home, lam_away, side, line_high)
        return {
            'win': 0.5 * (r1['win'] + r2['win']),
            'push': 0.5 * (r1['push'] + r2['push']),
            'lose': 0.5 * (r1['lose'] + r2['lose']),
        }

    # Linha inteira ou .5 — itera placares
    pmf_h = [poisson_pmf(i, lam_home) for i in range(MAX_GOALS_TO_SUM + 1)]
    pmf_a = [poisson_pmf(j, lam_away) for j in range(MAX_GOALS_TO_SUM + 1)]
    win = push = lose = 0.0
    for i in range(MAX_GOALS_TO_SUM + 1):
        for j in range(MAX_GOALS_TO_SUM + 1):
            p = pmf_h[i] * pmf_a[j]
            diff = (i - j) if side == 'home' else (j - i)
            adjusted = diff + line
            if adjusted > 1e-9:
                win += p
            elif adjusted < -1e-9:
                lose += p
            else:
                push += p
    return {'win': win, 'push': push, 'lose': lose}


# ============================================================================
# Helper de alto nível — extrai do dict markets
# ============================================================================

def _extract_1x2_odds(markets: Dict) -> Optional[Tuple[float, float, float]]:
    """Extrai (odd_home, odd_draw, odd_away) do markets['match_result']."""
    mr = markets.get('match_result') if isinstance(markets, dict) else None
    if not mr or not isinstance(mr, dict):
        return None
    options = mr.get('options') or {}
    if not isinstance(options, dict) or not options:
        return None
    odd_h = _normalize_odd_value(options.get('Casa'))
    odd_d = _normalize_odd_value(options.get('Empate'))
    odd_a = _normalize_odd_value(options.get('Fora'))
    if odd_h <= 1.0 or odd_d <= 1.0 or odd_a <= 1.0:
        return None
    return (odd_h, odd_d, odd_a)


def _extract_over_under_pair(markets: Dict, preferred_line: float = 2.5) -> Optional[Tuple[float, float, float]]:
    """
    Extrai (odd_over, odd_under, line_efetiva) do markets['total_goals'].
    Tenta primeiro a linha preferida (2.5). Se não tiver par completo,
    procura linhas próximas (preferência: 2.5 > 1.5 > 3.5 > demais).
    """
    tg = markets.get('total_goals') if isinstance(markets, dict) else None
    if not tg or not isinstance(tg, dict):
        return None
    options = tg.get('options') or {}
    if not isinstance(options, dict) or not options:
        return None

    # Extrai todas as linhas disponíveis
    lines_dict: Dict[float, Dict[str, float]] = {}
    for key, raw_val in options.items():
        if not isinstance(key, str):
            continue
        m = _TOTAL_GOALS_LINE_RE.match(key.strip())
        if not m:
            continue
        side = m.group(1).lower()
        try:
            line_val = float(m.group(2))
        except ValueError:
            continue
        odd_val = _normalize_odd_value(raw_val)
        if odd_val <= 1.0:
            continue
        entry = lines_dict.setdefault(line_val, {})
        if side == 'mais':
            entry['over'] = odd_val
        elif side == 'menos':
            entry['under'] = odd_val

    # Filtra linhas com par completo
    complete = {k: v for k, v in lines_dict.items() if 'over' in v and 'under' in v}
    if not complete:
        return None

    # Tenta a linha preferida primeiro
    if preferred_line in complete:
        v = complete[preferred_line]
        return (v['over'], v['under'], preferred_line)

    # Senão, escolhe a mais próxima — preferindo linhas .5 sobre .0
    sorted_lines = sorted(complete.keys(), key=lambda x: (abs(x - preferred_line), x))
    chosen = sorted_lines[0]
    v = complete[chosen]
    return (v['over'], v['under'], chosen)


def calibrate_from_markets(markets: Dict) -> Optional[Tuple[float, float]]:
    """
    Helper de alto nível — recebe o dict markets do EventDigest/game_data e
    extrai p_home/p_draw/p_away/p_over_2_5, depois chama calibrate_lambdas.

    Args:
        markets: dict com 'match_result' e 'total_goals' (formato já existente)

    Retorna (lam_home, lam_away) ou None se faltar dados.

    Espera:
        markets['match_result']['options'] = {'Casa': odd_h, 'Empate': odd_d, 'Fora': odd_a}
        markets['total_goals']['options'] = {'Mais de 2.5': odd_over, 'Menos de 2.5': odd_under, ...}

    Pega especificamente a linha 2.5 do total_goals. Se não tiver, tenta a linha mais próxima.

    NOTA: se a linha O/U usada não for 2.5, a calibração ainda funciona porém o
    sistema vai estar resolvendo p_over_X (não 2.5). Isso degrada um pouco a
    precisão pra prever o.u 2.5 — aceitável como fallback.
    """
    if not isinstance(markets, dict):
        return None

    odds_1x2 = _extract_1x2_odds(markets)
    if not odds_1x2:
        logger.debug("calibrate_from_markets: 1x2 ausente ou inválido")
        return None
    odd_h, odd_d, odd_a = odds_1x2

    ou_data = _extract_over_under_pair(markets, preferred_line=2.5)
    if not ou_data:
        logger.debug("calibrate_from_markets: total_goals ausente ou sem par completo")
        return None
    odd_over, odd_under, line_eff = ou_data

    try:
        p_home, p_draw, p_away = implied_probs_1x2(odd_h, odd_d, odd_a)
        p_over, _p_under = implied_probs_over_under(odd_over, odd_under)
    except ValueError as e:
        logger.debug(f"calibrate_from_markets: erro nas probs implícitas: {e}")
        return None

    # Se a linha não for 2.5, alertamos via debug — a função `calibrate_lambdas`
    # vai resolver pra 2.5 internamente, então rebatimos a meta pra equivalente
    # aproximado na 2.5 (manter simples: usar a mesma p_over como aproximação)
    if abs(line_eff - 2.5) > 1e-9:
        logger.debug(f"calibrate_from_markets: usando linha O/U {line_eff} como proxy de 2.5")

    return calibrate_lambdas(p_home, p_draw, p_away, p_over)


# ============================================================================
# Smoke test / validação inline
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("Smoke test — betting/poisson.py")
    print("=" * 70)

    # Detecta se scipy está disponível pra reportar
    try:
        import scipy  # noqa: F401
        scipy_status = f"scipy {scipy.__version__} disponível"
    except ImportError:
        scipy_status = "scipy INDISPONÍVEL — fallback grid search"
    print(f"\n[INFO] {scipy_status}\n")

    # --------------------------------------------------------------------
    # Cenário 1: Jogo equilibrado (PSG vs Arsenal hipotético)
    # --------------------------------------------------------------------
    print("-" * 70)
    print("CENÁRIO 1 — Jogo equilibrado (odds 2.4 / 3.4 / 3.0, O/U 2.5: 1.85 / 2.0)")
    print("-" * 70)
    p_h, p_d, p_a = implied_probs_1x2(2.4, 3.4, 3.0)
    print(f"1x2 probs implícitas: home={p_h:.2%} draw={p_d:.2%} away={p_a:.2%} (soma={p_h+p_d+p_a:.4f})")

    p_o, p_u = implied_probs_over_under(1.85, 2.0)
    print(f"O/U 2.5 probs implícitas: over={p_o:.2%} under={p_u:.2%}")

    result = calibrate_lambdas(p_h, p_d, p_a, p_o)
    print(f"Calibrated lambdas: {result}")
    assert result, "FALHOU calibrar cenário 1"
    lh, la = result

    p_h2, p_d2, p_a2 = prob_outcomes_1x2(lh, la)
    print(f"Verify 1x2:  home={p_h2:.2%} (alvo {p_h:.2%}) | "
          f"draw={p_d2:.2%} (alvo {p_d:.2%}) | "
          f"away={p_a2:.2%} (alvo {p_a:.2%})")
    p_o2, _ = prob_over_under(lh, la, 2.5)
    print(f"Verify O/U:  over_2.5={p_o2:.2%} (alvo {p_o:.2%})")

    # Tolerância de 5% relativa nas probs alvo (home + over)
    assert abs(p_h2 - p_h) < 0.05, f"home divergiu demais: {p_h2:.2%} vs {p_h:.2%}"
    assert abs(p_o2 - p_o) < 0.05, f"over divergiu demais: {p_o2:.2%} vs {p_o:.2%}"

    # Handicap asiático home -0.5 (igual a "home vence" puro)
    hcp = prob_handicap_asian(lh, la, 'home', -0.5)
    print(f"Handicap home -0.5: win={hcp['win']:.2%} push={hcp['push']:.2%} lose={hcp['lose']:.2%}")
    assert abs(hcp['push']) < 1e-9, "linha .5 deve ter push=0"
    assert abs((hcp['win'] + hcp['push'] + hcp['lose']) - 1.0) < PROB_SUM_TOLERANCE, "soma != 1"
    # win do -0.5 deve ser equivalente a p_h2 (home vence puro)
    assert abs(hcp['win'] - p_h2) < 1e-6, f"home -0.5 deveria == home win: {hcp['win']:.4f} vs {p_h2:.4f}"

    # Handicap home -1.5 (vencer por 2+)
    hcp = prob_handicap_asian(lh, la, 'home', -1.5)
    print(f"Handicap home -1.5: win={hcp['win']:.2%} push={hcp['push']:.2%} lose={hcp['lose']:.2%}")
    assert abs(hcp['push']) < 1e-9, "linha .5 deve ter push=0"
    assert abs((hcp['win'] + hcp['push'] + hcp['lose']) - 1.0) < PROB_SUM_TOLERANCE

    # Handicap home -1.0 (linha cheia, COM push)
    hcp = prob_handicap_asian(lh, la, 'home', -1.0)
    print(f"Handicap home -1.0: win={hcp['win']:.2%} push={hcp['push']:.2%} lose={hcp['lose']:.2%}")
    assert hcp['push'] > 0, "linha .0 deve ter push > 0"
    assert abs((hcp['win'] + hcp['push'] + hcp['lose']) - 1.0) < PROB_SUM_TOLERANCE

    # Handicap quarter line home -0.75 (split entre -0.5 e -1.0)
    hcp = prob_handicap_asian(lh, la, 'home', -0.75)
    print(f"Handicap home -0.75 (quarter): win={hcp['win']:.2%} push={hcp['push']:.2%} lose={hcp['lose']:.2%}")
    assert abs((hcp['win'] + hcp['push'] + hcp['lose']) - 1.0) < PROB_SUM_TOLERANCE

    # --------------------------------------------------------------------
    # Cenário 2: Favorito forte em casa (Man City vs lanterna)
    # --------------------------------------------------------------------
    print()
    print("-" * 70)
    print("CENÁRIO 2 — Favorito forte (odds 1.30 / 5.5 / 9.0, O/U 2.5: 1.50 / 2.6)")
    print("-" * 70)
    p_h, p_d, p_a = implied_probs_1x2(1.30, 5.5, 9.0)
    print(f"1x2 probs implícitas: home={p_h:.2%} draw={p_d:.2%} away={p_a:.2%}")
    p_o, p_u = implied_probs_over_under(1.50, 2.6)
    print(f"O/U 2.5 probs implícitas: over={p_o:.2%} under={p_u:.2%}")

    result = calibrate_lambdas(p_h, p_d, p_a, p_o)
    print(f"Calibrated lambdas: {result}")
    assert result, "FALHOU calibrar cenário 2"
    lh, la = result

    p_h2, p_d2, p_a2 = prob_outcomes_1x2(lh, la)
    print(f"Verify 1x2:  home={p_h2:.2%} (alvo {p_h:.2%}) | draw={p_d2:.2%} | away={p_a2:.2%}")
    p_o2, _ = prob_over_under(lh, la, 2.5)
    print(f"Verify O/U:  over_2.5={p_o2:.2%} (alvo {p_o:.2%})")
    assert abs(p_h2 - p_h) < 0.05
    assert abs(p_o2 - p_o) < 0.05

    # Em jogo favorito, handicap home -2.0 deve ter probabilidade razoável
    hcp = prob_handicap_asian(lh, la, 'home', -2.0)
    print(f"Handicap home -2.0: win={hcp['win']:.2%} push={hcp['push']:.2%} lose={hcp['lose']:.2%}")
    assert abs((hcp['win'] + hcp['push'] + hcp['lose']) - 1.0) < PROB_SUM_TOLERANCE

    # --------------------------------------------------------------------
    # Cenário 3: Jogo zebra (visitante favorito) + calibrate_from_markets
    # --------------------------------------------------------------------
    print()
    print("-" * 70)
    print("CENÁRIO 3 — calibrate_from_markets() com dict de mercados")
    print("-" * 70)

    fake_markets = {
        'match_result': {
            'options': {
                'Casa': 3.5,
                'Empate': 3.3,
                'Fora': 2.0,
            }
        },
        'total_goals': {
            'options': {
                'Mais de 0.5': 1.10,
                'Menos de 0.5': 7.5,
                'Mais de 1.5': 1.35,
                'Menos de 1.5': 3.1,
                'Mais de 2.5': 2.05,
                'Menos de 2.5': 1.75,
                'Mais de 3.5': 3.6,
                'Menos de 3.5': 1.28,
            }
        }
    }

    result = calibrate_from_markets(fake_markets)
    print(f"Calibrated lambdas from markets: {result}")
    assert result, "FALHOU calibrate_from_markets"
    lh, la = result

    # Visitante favorito → la > lh esperado
    print(f"  lh={lh:.3f}, la={la:.3f} — visitante favorito → la deve ser > lh: {'OK' if la > lh else 'INVERTIDO'}")
    assert la > lh, f"esperado la > lh (visitante favorito), got lh={lh}, la={la}"

    # Verifica que P(away win) > P(home win) reproduz o input
    p_h2, p_d2, p_a2 = prob_outcomes_1x2(lh, la)
    p_h_exp, p_d_exp, p_a_exp = implied_probs_1x2(3.5, 3.3, 2.0)
    print(f"  1x2 modelo: home={p_h2:.2%} draw={p_d2:.2%} away={p_a2:.2%}")
    print(f"  1x2 alvo:   home={p_h_exp:.2%} draw={p_d_exp:.2%} away={p_a_exp:.2%}")

    # Handicap visitante -0.5 (visitante vence puro)
    hcp = prob_handicap_asian(lh, la, 'away', -0.5)
    print(f"  Handicap away -0.5: win={hcp['win']:.2%} push={hcp['push']:.2%} lose={hcp['lose']:.2%}")
    assert abs(hcp['win'] - p_a2) < 1e-6

    # --------------------------------------------------------------------
    # Cenário 4: Edge case — markets vazio/inválido
    # --------------------------------------------------------------------
    print()
    print("-" * 70)
    print("CENÁRIO 4 — edge cases (dados ausentes)")
    print("-" * 70)
    assert calibrate_from_markets({}) is None
    assert calibrate_from_markets({'match_result': {}}) is None
    assert calibrate_from_markets(None) is None  # type: ignore[arg-type]
    print("OK — calibrate_from_markets() retorna None com input inválido")

    # poisson_pmf edge cases
    assert poisson_pmf(0, 0) == 1.0
    assert poisson_pmf(1, 0) == 0.0
    assert poisson_pmf(-1, 1.5) == 0.0
    assert abs(poisson_pmf(2, 1.5) - (math.exp(-1.5) * 1.5**2 / 2)) < 1e-9
    print("OK — poisson_pmf edge cases")

    print()
    print("=" * 70)
    print("TODOS OS TESTES PASSARAM")
    print("=" * 70)
