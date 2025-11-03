# 🤖 BetAuto / GreenAi - Sistema Autônomo de Análise e Apostas Esportivas

Sistema automatizado que roda 24/7 em servidor VPS, analisando jogos de futebol, identificando oportunidades de valor e enviando palpites via Telegram.

## 📋 Características

- ✅ **Totalmente Autônomo**: Roda sem intervenção humana
- ✅ **Monitoramento 24/7**: Analisa jogos pré-jogo e ao vivo
- ✅ **Notificações Telegram**: Envia palpites e resultados automaticamente
- ✅ **Estatísticas Completas**: Calcula assertividade diária, semanal e lifetime
- ✅ **Resumos Automáticos**: Envia resumo diário com performance
- ✅ **Recuperação de Erros**: Sistema robusto que não trava em falhas

## 🚀 Deploy em Servidor VPS Ubuntu

### Pré-requisitos

- Ubuntu 20.04+ ou 22.04+
- Python 3.10+ instalado
- Acesso SSH ao servidor
- Conta Telegram com Bot Token e Chat ID

### Passo 1: Instalar Dependências do Sistema

```bash
# Atualizar sistema
sudo apt update && sudo apt upgrade -y

# Instalar Python e ferramentas básicas
sudo apt install -y python3 python3-pip python3-venv git

# Instalar dependências do Playwright (opcional, mas recomendado)
sudo apt install -y libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2
```

### Passo 2: Clonar/Copiar o Projeto

```bash
# Criar diretório para o projeto
mkdir -p ~/betauto
cd ~/betauto

# Copiar todos os arquivos do projeto para este diretório
# (via scp, git clone, ou upload manual)
```

### Passo 3: Criar Ambiente Virtual

```bash
cd ~/betauto
python3 -m venv venv
source venv/bin/activate
```

### Passo 4: Instalar Dependências Python

```bash
# Instalar pacotes Python
pip install --upgrade pip
pip install -r requirements.txt

# Instalar navegadores do Playwright (opcional, mas recomendado)
playwright install chromium
```

### Passo 5: Configurar Variáveis de Ambiente

Copie o arquivo template e configure suas credenciais:

```bash
cd ~/betauto
cp env.template .env
nano .env
```

**IMPORTANTE**: Substitua apenas os valores marcados com `SEU_...`:
- `TELEGRAM_TOKEN=SEU_TOKEN_AQUI` → Seu token do bot Telegram
- `TELEGRAM_CHAT_ID=SEU_CHAT_ID_AQUI` → Seu chat ID do Telegram

Os demais valores podem ser mantidos como estão (são padrões funcionais) ou ajustados conforme necessário.

**Conteúdo mínimo obrigatório**:
```env
TELEGRAM_TOKEN=seu_token_aqui
TELEGRAM_CHAT_ID=seu_chat_id_aqui
BETTING_LINK_1=https://betnacional.bet.br/events/1/0/390
```

Veja o arquivo `env.template` para todas as opções disponíveis.

### Passo 6: Testar a Instalação

```bash
# Ativar ambiente virtual
source venv/bin/activate

# Testar importação e configuração
python3 -c "from config.settings import TELEGRAM_TOKEN; print('✅ Config OK' if TELEGRAM_TOKEN else '❌ Token não configurado')"

# Testar execução (pressione Ctrl+C para parar)
python3 main.py
```

### Passo 7: Configurar Systemd Service

Crie o arquivo de serviço:

```bash
sudo nano /etc/systemd/system/betauto.service
```

Cole o conteúdo (ajuste o caminho se necessário):

```ini
[Unit]
Description=BetAuto - Sistema Autônomo de Análise e Apostas
After=network.target

[Service]
Type=simple
User=seu_usuario
WorkingDirectory=/home/seu_usuario/betauto
Environment="PATH=/home/seu_usuario/betauto/venv/bin"
ExecStart=/home/seu_usuario/betauto/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Limites de recursos
LimitNOFILE=65536
MemoryMax=2G

[Install]
WantedBy=multi-user.target
```

**⚠️ IMPORTANTE**: Substitua `seu_usuario` pelo seu usuário real do sistema.

### Passo 8: Ativar e Iniciar o Serviço

```bash
# Recarregar systemd
sudo systemctl daemon-reload

# Habilitar inicialização automática
sudo systemctl enable betauto.service

# Iniciar o serviço
sudo systemctl start betauto.service

# Verificar status
sudo systemctl status betauto.service

# Ver logs em tempo real
sudo journalctl -u betauto.service -f
```

### Passo 9: Verificar Logs

```bash
# Logs do systemd
sudo journalctl -u betauto.service -n 100 --no-pager

# Logs em tempo real
sudo journalctl -u betauto.service -f

# Logs das últimas 24 horas
sudo journalctl -u betauto.service --since "24 hours ago"
```

## 📊 Comandos Úteis

### Gerenciar o Serviço

```bash
# Parar
sudo systemctl stop betauto.service

# Iniciar
sudo systemctl start betauto.service

# Reiniciar
sudo systemctl restart betauto.service

# Status
sudo systemctl status betauto.service

# Desabilitar inicialização automática
sudo systemctl disable betauto.service
```

### Atualizar o Código

```bash
cd ~/betauto
source venv/bin/activate

# Atualizar código (git pull, scp, etc.)
# ...

# Atualizar dependências (se necessário)
pip install -r requirements.txt

# Reiniciar serviço
sudo systemctl restart betauto.service
```

### Verificar Banco de Dados

```bash
cd ~/betauto
source venv/bin/activate
sqlite3 betauto.sqlite3

# No SQLite:
.tables
SELECT COUNT(*) FROM games;
SELECT * FROM games ORDER BY id DESC LIMIT 5;
.quit
```

## 🔧 Troubleshooting

### Serviço não inicia

```bash
# Verificar erros
sudo journalctl -u betauto.service -n 50

# Verificar se o Python está correto
which python3
/home/seu_usuario/betauto/venv/bin/python --version

# Testar manualmente
cd ~/betauto
source venv/bin/activate
python main.py
```

### Erro de permissão

```bash
# Verificar permissões do diretório
ls -la ~/betauto

# Ajustar se necessário
chmod +x ~/betauto/main.py
chown -R seu_usuario:seu_usuario ~/betauto
```

### Playwright não funciona

```bash
# Reinstalar navegadores
cd ~/betauto
source venv/bin/activate
playwright install chromium

# Verificar dependências do sistema
playwright install-deps chromium
```

### Banco de dados corrompido

```bash
# Fazer backup
cp ~/betauto/betauto.sqlite3 ~/betauto/betauto.sqlite3.backup

# Tentar reparar (SQLite)
sqlite3 ~/betauto/betauto.sqlite3 "PRAGMA integrity_check;"
```

### Serviço reinicia constantemente

```bash
# Verificar logs para erros
sudo journalctl -u betauto.service -n 100

# Verificar se há exceções não tratadas
# O serviço deve reiniciar apenas em caso de crash
```

## 📈 Monitoramento

### Métricas Importantes

O sistema envia automaticamente:
- ✅ Resumo diário (se configurado `DAILY_SUMMARY_HOUR`)
- ✅ Estatísticas de assertividade
- ✅ Notificações de resultados

### Verificar Saúde do Sistema

```bash
# Verificar se o processo está rodando
ps aux | grep "python main.py"

# Verificar uso de recursos
top -p $(pgrep -f "python main.py")

# Verificar espaço em disco
df -h ~/betauto
```

## 🔐 Segurança

### Boas Práticas

1. **Não commitar `.env`**: O arquivo `.env` contém credenciais sensíveis
2. **Permissões restritas**: 
   ```bash
   chmod 600 ~/betauto/.env
   ```
3. **Firewall**: Configure firewall para permitir apenas conexões necessárias
4. **Backups**: Configure backups regulares do banco de dados:
   ```bash
   # Adicionar ao crontab (backup diário às 3h)
   0 3 * * * cp /home/seu_usuario/betauto/betauto.sqlite3 /backup/betauto-$(date +\%Y\%m\%d).sqlite3
   ```

## 📝 Estrutura do Projeto

```
betauto/
├── main.py                 # Ponto de entrada principal
├── .env                    # Variáveis de ambiente (não commitar)
├── requirements.txt        # Dependências Python
├── betauto.sqlite3        # Banco de dados (gerado automaticamente)
├── config/                 # Configurações
│   └── settings.py
├── models/                 # Modelos de banco de dados
│   └── database.py
├── scraping/               # Lógica de scraping
│   ├── fetchers.py
│   └── betnacional.py
├── betting/                # Lógica de decisão de apostas
│   ├── decision.py
│   └── kelly.py
├── scheduler/              # Jobs agendados
│   └── jobs.py
├── notifications/          # Notificações Telegram
│   └── telegram.py
├── utils/                  # Utilitários
│   ├── logger.py
│   ├── stats.py
│   └── formatters.py
├── watchlist/              # Gerenciamento de watchlist
│   └── manager.py
└── live/                   # Monitoramento de jogos ao vivo
    └── tracker.py
```

## 🆘 Suporte

Em caso de problemas:
1. Verifique os logs do systemd
2. Teste manualmente executando `python main.py`
3. Verifique se todas as variáveis de ambiente estão configuradas
4. Verifique conectividade com internet e Telegram API

## 📄 Licença

Uso interno - Sistema proprietário.

