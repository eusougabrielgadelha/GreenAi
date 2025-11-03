# 🚀 Guia Rápido de Deploy - BetAuto

Guia passo a passo para deploy em produção no VPS Ubuntu da Hostinger.

## ⚡ Setup Rápido (5 minutos)

### 1. Conectar ao VPS

```bash
ssh usuario@seu-vps-ip
```

### 2. Executar Script de Instalação

```bash
# Baixar/copiar arquivos do projeto para o servidor
cd ~
mkdir betauto
cd betauto
# (copiar todos os arquivos aqui via scp, git, ou upload)

# Tornar script executável
chmod +x setup.sh

# Executar instalação
./setup.sh
```

### 3. Configurar Credenciais

```bash
nano ~/betauto/.env
```

**Editar com suas credenciais:**
- `TELEGRAM_TOKEN`: Token do seu bot Telegram
- `TELEGRAM_CHAT_ID`: ID do seu chat Telegram

### 4. Testar Manualmente

```bash
cd ~/betauto
source venv/bin/activate
python main.py
```

**Pressione `Ctrl+C` após verificar que está funcionando.**

### 5. Iniciar como Serviço

```bash
# Substituir usuário no service file
sudo sed -i "s/seu_usuario/$(whoami)/g" /etc/systemd/system/betauto.service

# Habilitar e iniciar
sudo systemctl daemon-reload
sudo systemctl enable betauto.service
sudo systemctl start betauto.service

# Verificar status
sudo systemctl status betauto.service
```

### 6. Verificar Logs

```bash
# Logs em tempo real
sudo journalctl -u betauto.service -f

# Últimas 50 linhas
sudo journalctl -u betauto.service -n 50
```

## ✅ Verificação de Funcionamento

### Checklist

- [ ] Serviço está rodando: `sudo systemctl status betauto.service`
- [ ] Não há erros nos logs: `sudo journalctl -u betauto.service -n 100`
- [ ] Recebeu mensagem de teste no Telegram
- [ ] Banco de dados foi criado: `ls -lh ~/betauto/betauto.sqlite3`
- [ ] Logs estão sendo gerados: `ls -lh ~/betauto/logs/`

## 🔄 Comandos Úteis

### Gerenciar Serviço

```bash
# Parar
sudo systemctl stop betauto.service

# Iniciar
sudo systemctl start betauto.service

# Reiniciar
sudo systemctl restart betauto.service

# Status
sudo systemctl status betauto.service
```

### Ver Logs

```bash
# Tempo real
sudo journalctl -u betauto.service -f

# Últimas 100 linhas
sudo journalctl -u betauto.service -n 100

# De hoje
sudo journalctl -u betauto.service --since today

# Últimas 24 horas
sudo journalctl -u betauto.service --since "24 hours ago"
```

### Atualizar Código

```bash
cd ~/betauto
source venv/bin/activate

# Atualizar dependências (se necessário)
pip install -r requirements.txt

# Reiniciar serviço
sudo systemctl restart betauto.service
```

## 🐛 Troubleshooting

### Serviço não inicia

```bash
# Ver erros detalhados
sudo journalctl -u betauto.service -n 50

# Verificar se o Python está correto
ls -la ~/betauto/venv/bin/python

# Testar manualmente
cd ~/betauto
source venv/bin/activate
python main.py
```

### Erro de permissão

```bash
# Verificar permissões
ls -la ~/betauto/

# Ajustar permissões
chmod 600 ~/betauto/.env
chown -R $USER:$USER ~/betauto
```

### Playwright não funciona

```bash
cd ~/betauto
source venv/bin/activate
playwright install chromium
playwright install-deps chromium
```

### Serviço reinicia constantemente

```bash
# Verificar logs para identificar erro
sudo journalctl -u betauto.service -n 100

# Verificar se há exceções não tratadas
# O sistema deve reiniciar automaticamente em caso de crash
```

## 📊 Monitoramento

### Verificar se está rodando

```bash
ps aux | grep "python main.py"
```

### Verificar uso de recursos

```bash
top -p $(pgrep -f "python main.py")
```

### Verificar espaço em disco

```bash
df -h ~/betauto
du -sh ~/betauto/*
```

## 🔐 Segurança

### Proteger arquivo .env

```bash
chmod 600 ~/betauto/.env
```

### Backup do banco de dados

```bash
# Backup manual
cp ~/betauto/betauto.sqlite3 ~/betauto/betauto-$(date +%Y%m%d).sqlite3

# Backup automático (adicionar ao crontab)
crontab -e
# Adicionar linha:
0 3 * * * cp ~/betauto/betauto.sqlite3 ~/backup/betauto-$(date +\%Y\%m\%d).sqlite3
```

## 📝 Estrutura de Arquivos Esperada

```
~/betauto/
├── main.py
├── .env
├── requirements.txt
├── betauto.sqlite3 (gerado automaticamente)
├── logs/ (gerado automaticamente)
│   └── betauto.log
├── venv/ (criado pelo setup.sh)
├── config/
├── models/
├── scraping/
├── betting/
├── scheduler/
├── notifications/
├── utils/
├── watchlist/
└── live/
```

## 🆘 Suporte

Se algo não funcionar:

1. Verifique os logs: `sudo journalctl -u betauto.service -n 100`
2. Teste manualmente: `cd ~/betauto && source venv/bin/activate && python main.py`
3. Verifique configurações: `cat ~/betauto/.env`
4. Verifique dependências: `pip list`

