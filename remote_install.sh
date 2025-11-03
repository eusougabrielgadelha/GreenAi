#!/bin/bash
# Script para execução remota - será enviado via SSH

cd /tmp

# Baixar script de instalação
wget -q https://raw.githubusercontent.com/eusougabrielgadelha/GreenAi/main/install_vps.sh || \
curl -s -o install_vps.sh https://raw.githubusercontent.com/eusougabrielgadelha/GreenAi/main/install_vps.sh

chmod +x install_vps.sh

# Executar instalação
bash install_vps.sh

# Verificar status
echo ""
echo "📊 Status final do PM2:"
pm2 status

echo ""
echo "📋 Últimas linhas dos logs:"
pm2 logs betauto --lines 10 --nostream

