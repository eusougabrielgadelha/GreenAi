#!/bin/bash
# Script de instalação e configuração do BetAuto em VPS Ubuntu
# Uso: ./setup.sh

set -e

echo "🚀 Instalando BetAuto..."

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Verificar se está rodando como root
if [ "$EUID" -eq 0 ]; then 
   echo -e "${RED}❌ Não execute como root. Use seu usuário normal.${NC}"
   exit 1
fi

USER=$(whoami)
PROJECT_DIR="$HOME/betauto"

echo -e "${GREEN}✅ Usuário: $USER${NC}"
echo -e "${GREEN}✅ Diretório: $PROJECT_DIR${NC}"

# Atualizar sistema
echo -e "\n${YELLOW}📦 Atualizando sistema...${NC}"
sudo apt update && sudo apt upgrade -y

# Instalar dependências do sistema
echo -e "\n${YELLOW}📦 Instalando dependências do sistema...${NC}"
sudo apt install -y python3 python3-pip python3-venv git sqlite3

# Instalar dependências do Playwright
echo -e "\n${YELLOW}📦 Instalando dependências do Playwright...${NC}"
sudo apt install -y libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2

# Criar diretório do projeto
if [ ! -d "$PROJECT_DIR" ]; then
    echo -e "\n${YELLOW}📁 Criando diretório do projeto...${NC}"
    mkdir -p "$PROJECT_DIR"
fi

cd "$PROJECT_DIR"

# Criar ambiente virtual
if [ ! -d "venv" ]; then
    echo -e "\n${YELLOW}🐍 Criando ambiente virtual Python...${NC}"
    python3 -m venv venv
fi

# Ativar ambiente virtual
echo -e "\n${YELLOW}🔧 Ativando ambiente virtual...${NC}"
source venv/bin/activate

# Atualizar pip
echo -e "\n${YELLOW}📦 Atualizando pip...${NC}"
pip install --upgrade pip

# Instalar dependências Python
if [ -f "requirements.txt" ]; then
    echo -e "\n${YELLOW}📦 Instalando dependências Python...${NC}"
    pip install -r requirements.txt
else
    echo -e "${RED}❌ Arquivo requirements.txt não encontrado!${NC}"
    exit 1
fi

# Instalar navegadores do Playwright
echo -e "\n${YELLOW}🌐 Instalando navegadores do Playwright...${NC}"
playwright install chromium || echo -e "${YELLOW}⚠️  Playwright opcional, continuando...${NC}"

# Verificar/criar arquivo .env
if [ ! -f ".env" ]; then
    echo -e "\n${YELLOW}📝 Criando arquivo .env de exemplo...${NC}"
    cat > .env << 'EOF'
# Telegram
TELEGRAM_TOKEN=seu_token_aqui
TELEGRAM_CHAT_ID=seu_chat_id_aqui

# Timezone
APP_TZ=America/Sao_Paulo
MORNING_HOUR=6

# Banco de Dados
DB_URL=sqlite:///betauto.sqlite3

# Scraping
SCRAPE_BACKEND=auto
REQUESTS_TIMEOUT=20

# Configurações de Aposta
HIGH_CONF_THRESHOLD=0.60
MIN_EV=0.05
MIN_PROB=0.45

# Links de Apostas (obrigatório pelo menos um)
BETTING_LINK_1=https://betnacional.bet.br/events/1/0/390

# Opcionais
ENABLE_NIGHT_SCAN=false
NIGHT_SCAN_HOUR=22
DAILY_SUMMARY_HOUR=23
WATCHLIST_RESCAN_MIN=5
EOF
    echo -e "${GREEN}✅ Arquivo .env criado. Edite com suas credenciais!${NC}"
    chmod 600 .env
else
    echo -e "${GREEN}✅ Arquivo .env já existe.${NC}"
fi

# Configurar systemd service
echo -e "\n${YELLOW}⚙️  Configurando systemd service...${NC}"

# Criar arquivo de serviço temporário
SERVICE_FILE="/tmp/betauto.service"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=BetAuto - Sistema Autônomo de Análise e Apostas
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$PROJECT_DIR/venv/bin"
ExecStart=$PROJECT_DIR/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Limites de recursos
LimitNOFILE=65536
MemoryMax=2G

[Install]
WantedBy=multi-user.target
EOF

# Copiar para systemd
sudo cp "$SERVICE_FILE" /etc/systemd/system/betauto.service
sudo systemctl daemon-reload

echo -e "${GREEN}✅ Service file criado em /etc/systemd/system/betauto.service${NC}"

# Verificar se main.py existe
if [ ! -f "main.py" ]; then
    echo -e "${RED}❌ Arquivo main.py não encontrado!${NC}"
    echo -e "${YELLOW}⚠️  Certifique-se de que todos os arquivos do projeto estão em $PROJECT_DIR${NC}"
fi

# Teste rápido
echo -e "\n${YELLOW}🧪 Testando instalação...${NC}"
if python -c "from config.settings import APP_TZ; print('✅ Import OK')" 2>/dev/null; then
    echo -e "${GREEN}✅ Teste de importação passou!${NC}"
else
    echo -e "${RED}❌ Erro ao importar módulos. Verifique a estrutura do projeto.${NC}"
fi

echo -e "\n${GREEN}✅ Instalação concluída!${NC}"
echo -e "\n${YELLOW}📋 Próximos passos:${NC}"
echo -e "1. Edite o arquivo .env com suas credenciais:"
echo -e "   ${GREEN}nano $PROJECT_DIR/.env${NC}"
echo -e ""
echo -e "2. Teste manualmente:"
echo -e "   ${GREEN}cd $PROJECT_DIR && source venv/bin/activate && python main.py${NC}"
echo -e ""
echo -e "3. Iniciar como serviço:"
echo -e "   ${GREEN}sudo systemctl enable betauto.service${NC}"
echo -e "   ${GREEN}sudo systemctl start betauto.service${NC}"
echo -e ""
echo -e "4. Verificar status:"
echo -e "   ${GREEN}sudo systemctl status betauto.service${NC}"
echo -e ""
echo -e "5. Ver logs:"
echo -e "   ${GREEN}sudo journalctl -u betauto.service -f${NC}"

