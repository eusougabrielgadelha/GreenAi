#!/bin/bash
# ============================================
# Script de Instalação do BetAuto/GreenAi no VPS
# ============================================
# Execute como root: bash install_vps.sh

set -e  # Para em caso de erro

echo "🚀 Iniciando instalação do BetAuto/GreenAi..."

# ============================================
# 1. Atualizar sistema
# ============================================
echo "📦 Atualizando sistema..."
apt update && apt upgrade -y

# ============================================
# 2. Instalar dependências do sistema
# ============================================
echo "📦 Instalando dependências do sistema..."
apt install -y python3 python3-pip python3-venv git curl wget

# ============================================
# 3. Instalar Node.js e PM2
# ============================================
echo "📦 Instalando Node.js e PM2..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs
npm install -g pm2

# ============================================
# 4. Instalar dependências do Playwright (opcional, mas recomendado)
# ============================================
echo "📦 Instalando dependências do Playwright..."
apt install -y libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2

# ============================================
# 5. Criar diretório do projeto
# ============================================
PROJECT_DIR="/opt/betauto"
echo "📁 Criando diretório do projeto em $PROJECT_DIR..."
mkdir -p $PROJECT_DIR
cd $PROJECT_DIR

# ============================================
# 6. Clonar repositório do GitHub
# ============================================
echo "📥 Clonando repositório do GitHub..."
if [ -d ".git" ]; then
    echo "⚠️  Repositório já existe, atualizando..."
    git pull origin main
else
    git clone https://github.com/eusougabrielgadelha/GreenAi.git .
fi

# ============================================
# 7. Criar ambiente virtual Python
# ============================================
echo "🐍 Criando ambiente virtual Python..."
python3 -m venv venv
source venv/bin/activate

# ============================================
# 8. Instalar dependências Python
# ============================================
echo "📦 Instalando dependências Python..."
pip install --upgrade pip
pip install -r requirements.txt

# ============================================
# 9. Instalar navegadores do Playwright (opcional)
# ============================================
echo "🌐 Instalando navegadores do Playwright..."
playwright install chromium || echo "⚠️  Playwright não instalado, mas não é crítico"

# ============================================
# 10. Configurar arquivo .env
# ============================================
echo "⚙️  Configurando arquivo .env..."
if [ ! -f ".env" ]; then
    cp env.template .env
    
    # Configurar credenciais do Telegram (já fornecidas)
    sed -i 's/TELEGRAM_TOKEN=SEU_TOKEN_AQUI/TELEGRAM_TOKEN=8487738643:AAHfnEEB6PKN6rDlRKrKkrh6HGRyTYtrge0/' .env
    sed -i 's/TELEGRAM_CHAT_ID=SEU_CHAT_ID_AQUI/TELEGRAM_CHAT_ID=-1002952840130/' .env
    
    echo "✅ Arquivo .env criado e configurado"
else
    echo "⚠️  Arquivo .env já existe, mantendo configurações existentes"
fi

# ============================================
# 11. Configurar permissões
# ============================================
echo "🔐 Configurando permissões..."
chmod 600 .env
chown -R root:root $PROJECT_DIR

# ============================================
# 12. Inicializar banco de dados
# ============================================
echo "💾 Inicializando banco de dados..."
cd $PROJECT_DIR
source venv/bin/activate
python3 -c "from models.database import Base, engine; Base.metadata.create_all(engine)" || echo "⚠️  Erro ao criar banco, mas continuando..."

# ============================================
# 13. Configurar PM2
# ============================================
echo "⚙️  Configurando PM2..."

# Criar arquivo de configuração do PM2
cat > $PROJECT_DIR/ecosystem.config.js << 'EOF'
module.exports = {
  apps: [{
    name: 'betauto',
    script: 'main.py',
    interpreter: 'venv/bin/python3',
    cwd: '/opt/betauto',
    autorestart: true,
    watch: false,
    max_memory_restart: '1G',
    env: {
      PYTHONUNBUFFERED: '1',
      APP_TZ: 'America/Sao_Paulo'
    },
    error_file: '/opt/betauto/logs/pm2-error.log',
    out_file: '/opt/betauto/logs/pm2-out.log',
    log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
    merge_logs: true,
    time: true
  }]
};
EOF

# ============================================
# 14. Iniciar aplicação com PM2
# ============================================
echo "🚀 Iniciando aplicação com PM2..."
cd $PROJECT_DIR
pm2 delete betauto 2>/dev/null || true  # Remove se já existir
pm2 start ecosystem.config.js
pm2 save
pm2 startup

# ============================================
# 15. Verificar status
# ============================================
echo ""
echo "✅ Instalação concluída!"
echo ""
echo "📊 Status do PM2:"
pm2 status
echo ""
echo "📋 Comandos úteis:"
echo "  - Ver logs: pm2 logs betauto"
echo "  - Reiniciar: pm2 restart betauto"
echo "  - Parar: pm2 stop betauto"
echo "  - Status: pm2 status"
echo ""
echo "📁 Diretório do projeto: $PROJECT_DIR"
echo ""

