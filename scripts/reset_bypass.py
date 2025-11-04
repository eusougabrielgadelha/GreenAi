#!/usr/bin/env python3
"""
Script para resetar o estado do bypass forçadamente.
Útil quando o sistema está bloqueado e precisa ser resetado.
"""
import sys
import os

# Adicionar diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.bypass_detection import get_bypass_detector
from utils.cookie_manager import get_cookie_manager

def main():
    print("=" * 60)
    print("RESET DO SISTEMA DE BYPASS")
    print("=" * 60)
    
    # 1. Mostrar status atual
    detector = get_bypass_detector()
    status = detector.get_bypass_status()
    
    print("\nStatus ANTES do reset:")
    print(f"  - Bloqueado até: {status['blocked_until']}")
    print(f"  - Está bloqueado: {status['is_blocked']}")
    print(f"  - Falhas consecutivas: {status['consecutive_failures']}")
    print(f"  - DOM fallback ativo: {status['use_dom_fallback']}")
    print(f"  - Challenge cooldown até: {status['challenge_cooldown_until']}")
    print(f"  - Último sucesso: {status['last_success_time']}")
    print(f"  - Total de sucessos: {status['success_count']}")
    print(f"  - Requisições no último minuto: {status['requests_last_minute']}/{status['max_requests_per_minute']}")
    
    # 2. Resetar bypass
    print("\nResetando estado do bypass...")
    detector.reset_bypass_state(force=True)
    
    # 3. Mostrar status após reset
    status_after = detector.get_bypass_status()
    print("\nStatus DEPOIS do reset:")
    print(f"  - Bloqueado até: {status_after['blocked_until']}")
    print(f"  - Está bloqueado: {status_after['is_blocked']}")
    print(f"  - Falhas consecutivas: {status_after['consecutive_failures']}")
    print(f"  - DOM fallback ativo: {status_after['use_dom_fallback']}")
    
    # 4. Verificar cookies
    print("\nVerificando cookies...")
    manager = get_cookie_manager()
    cookie_stats = manager.get_stats()
    print(f"  - Total de cookies: {cookie_stats['total_cookies']}")
    print(f"  - Cookies válidos: {cookie_stats['valid_cookies']}")
    print(f"  - Cookies expirados: {cookie_stats['expired_cookies']}")
    
    if cookie_stats['valid_cookies'] == 0:
        print("\nAVISO: Nenhum cookie válido encontrado!")
        print("O sistema fará warm-up automaticamente na próxima requisição.")
    
    print("\n" + "=" * 60)
    print("Reset concluído!")
    print("=" * 60)

if __name__ == '__main__':
    main()

