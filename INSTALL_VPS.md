# 🚀 Instalação no VPS - Guia Rápido

## Conectar ao VPS e Executar Instalação

### Método 1: Instalação Automática (Recomendado)

Execute este comando no seu terminal local (Windows PowerShell ou CMD):

```bash
ssh root@195.200.2.26 "bash -s" < <(curl -s https://raw.githubusercontent.com/eusougabrielgadelha/GreenAi/main/remote_install.sh)
```

**OU** conecte manualmente e execute:

```bash
ssh root@195.200.2.26
```

Depois, no VPS, execute:

```bash
cd /tmp
wget https://raw.githubusercontent.com/eusougabrielgadelha/GreenAi/main/install_vps.sh
chmod +x install_vps.sh
bash install_vps.sh
```

### Método 2: Instalação Completa Manual

1. **Conectar ao VPS:**
   ```bash
   ssh root@195.200.2.26
   # Senha: inDubai2023@
   ```

2. **Atualizar sistema:**
   ```bash
   apt update && apt upgrade -y
   ```

3. **Instalar dependências:**
   ```bash
   apt install -y python3 python3-pip python3-venv git curl wget
   curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
   apt install -y nodejs
   npm install -g pm2
   ```

4. **Instalar dependências do Playwright:**
   ```bash
   apt install -y libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libxcomposite1 \
       libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2
   ```

5. **Clonar repositório:**
   ```bash
   mkdir -p /opt/betauto
   cd /opt/betauto
   git clone https://github.com/eusougabrielgadelha/GreenAi.git .
   ```

6. **Configurar ambiente Python:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

7. **Configurar .env:**
   ```bash
   cp env.template .env
   nano .env
   ```
   
   Edite e configure:
   ```
   TELEGRAM_TOKEN=8487738643:AAHfnEEB6PKN6rDlRKrKkrh6HGRyTYtrge0
   TELEGRAM_CHAT_ID=-1002952840130
   ```

8. **Iniciar com PM2:**
   ```bash
   pm2 start main.py --name betauto --interpreter venv/bin/python3
   pm2 save
   pm2 startup
   ```

9. **Verificar status:**
   ```bash
   pm2 status
   pm2 logs betauto
   ```

## Comandos Úteis do PM2

```bash
pm2 status              # Ver status
pm2 logs betauto        # Ver logs
pm2 restart betauto     # Reiniciar
pm2 stop betauto        # Parar
pm2 delete betauto      # Remover
pm2 monit               # Monitoramento em tempo real
```

## Verificar se está funcionando

```bash
# Ver logs em tempo real
pm2 logs betauto --lines 50

# Verificar se está rodando
pm2 list

# Ver uso de recursos
pm2 monit
```

## Troubleshooting

Se houver problemas:

1. **Verificar logs:**
   ```bash
   pm2 logs betauto --err
   ```

2. **Verificar se o .env está correto:**
   ```bash
   cat /opt/betauto/.env
   ```

3. **Testar manualmente:**
   ```bash
   cd /opt/betauto
   source venv/bin/activate
   python main.py
   ```

4. **Reiniciar completamente:**
   ```bash
   pm2 delete betauto
   cd /opt/betauto
   source venv/bin/activate
   pm2 start main.py --name betauto --interpreter venv/bin/python3
   pm2 save
   ```



