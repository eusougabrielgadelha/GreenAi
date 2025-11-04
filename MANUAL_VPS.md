# 📖 Manual de Acesso ao VPS - Passo a Passo

Este manual explica como acessar seu VPS e configurar o ambiente para rodar o projeto GreenAi.

## 🔑 Informações de Acesso

- **Endereço IP:** 195.200.2.26
- **Usuário:** root
- **Senha:** inDubai2023@

---

## 🚀 ETAPA 1: Acessar o VPS via SSH

### No Windows (PowerShell ou CMD):

```bash
ssh root@195.200.2.26
```

**Quando solicitado, digite a senha:** `inDubai2023@`

**Nota:** Ao digitar a senha, ela não aparecerá na tela (por segurança). Apenas digite e pressione Enter.

### No Linux/Mac:

```bash
ssh root@195.200.2.26
```

---

## ✅ ETAPA 2: Verificar Conexão

Após conectar com sucesso, você verá algo como:

```
Welcome to Ubuntu...
root@servidor:~#
```

Isso significa que você está conectado ao VPS.

---

## 🔧 ETAPA 3: Verificar Estado do Sistema

Execute os seguintes comandos para verificar o estado atual:

```bash
# Verificar versão do sistema
lsb_release -a

# Verificar espaço em disco
df -h

# Verificar memória disponível
free -h

# Verificar se Python está instalado
python3 --version

# Verificar se Git está instalado
git --version
```

---

## 📥 ETAPA 4: Baixar o Projeto do GitHub

### Opção A: Usar Script de Instalação Automática (Recomendado)

```bash
cd /tmp
wget https://raw.githubusercontent.com/eusougabrielgadelha/GreenAi/main/install_vps.sh
chmod +x install_vps.sh
bash install_vps.sh
```

### Opção B: Instalação Manual

```bash
# Criar diretório do projeto
mkdir -p /opt/betauto
cd /opt/betauto

# Clonar repositório
git clone https://github.com/eusougabrielgadelha/GreenAi.git .
```

---

## 🐍 ETAPA 5: Configurar Ambiente Python

```bash
# Navegar para o diretório do projeto
cd /opt/betauto

# Criar ambiente virtual
python3 -m venv venv

# Ativar ambiente virtual
source venv/bin/activate

# Atualizar pip
pip install --upgrade pip

# Instalar dependências
pip install -r requirements.txt
```

---

## ⚙️ ETAPA 6: Configurar Variáveis de Ambiente

```bash
# Copiar template
cp env.template .env

# Editar arquivo .env
nano .env
```

**Configure pelo menos:**
- `TELEGRAM_TOKEN` - Token do seu bot Telegram
- `TELEGRAM_CHAT_ID` - ID do seu chat Telegram

**Para salvar no nano:** `Ctrl+X`, depois `Y`, depois `Enter`

---

## 🔐 ETAPA 7: Proteger Arquivo .env

```bash
chmod 600 .env
```

---

## 🚀 ETAPA 8: Iniciar o Projeto

### Opção A: Usar PM2 (Recomendado para produção)

```bash
# Instalar PM2 (se ainda não instalado)
npm install -g pm2

# Iniciar aplicação
cd /opt/betauto
source venv/bin/activate
pm2 start main.py --name betauto --interpreter venv/bin/python3

# Salvar configuração do PM2
pm2 save

# Configurar PM2 para iniciar no boot
pm2 startup
```

### Opção B: Teste Manual (Para verificar se está funcionando)

```bash
cd /opt/betauto
source venv/bin/activate
python main.py
```

Pressione `Ctrl+C` para parar após verificar que está funcionando.

---

## 📊 ETAPA 9: Verificar Status

```bash
# Ver status do PM2
pm2 status

# Ver logs em tempo real
pm2 logs betauto

# Ver últimas 50 linhas de log
pm2 logs betauto --lines 50
```

---

## 🔄 Comandos Úteis

### Gerenciar Aplicação PM2

```bash
# Ver status
pm2 status

# Ver logs
pm2 logs betauto

# Reiniciar
pm2 restart betauto

# Parar
pm2 stop betauto

# Iniciar
pm2 start betauto

# Deletar processo
pm2 delete betauto

# Monitoramento em tempo real
pm2 monit
```

### Atualizar Código

```bash
cd /opt/betauto
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
pm2 restart betauto
```

### Verificar Logs do Sistema

```bash
# Ver logs do PM2
pm2 logs betauto

# Ver logs do sistema
journalctl -u betauto.service -f
```

---

## 🐛 Troubleshooting

### Problema: Não consigo conectar via SSH

**Soluções:**
1. Verifique se o IP está correto: `195.200.2.26`
2. Verifique se a senha está correta: `inDubai2023@`
3. Verifique se o firewall não está bloqueando a porta 22

### Problema: Erro ao instalar dependências Python

```bash
# Atualizar pip
pip install --upgrade pip

# Tentar novamente
pip install -r requirements.txt
```

### Problema: Playwright não funciona

```bash
cd /opt/betauto
source venv/bin/activate
playwright install chromium
playwright install-deps chromium
```

### Problema: Aplicação não inicia

```bash
# Ver logs detalhados
pm2 logs betauto --err

# Testar manualmente
cd /opt/betauto
source venv/bin/activate
python main.py
```

### Problema: Erro de permissão

```bash
# Verificar permissões
ls -la /opt/betauto/

# Ajustar permissões (se necessário)
chmod 600 /opt/betauto/.env
chown -R root:root /opt/betauto
```

---

## 📝 Checklist de Instalação

- [ ] Conectado ao VPS via SSH
- [ ] Sistema atualizado (`apt update && apt upgrade -y`)
- [ ] Python 3 instalado
- [ ] Git instalado
- [ ] Projeto clonado do GitHub
- [ ] Ambiente virtual criado e ativado
- [ ] Dependências Python instaladas
- [ ] Arquivo `.env` configurado
- [ ] PM2 instalado e configurado
- [ ] Aplicação rodando (`pm2 status`)
- [ ] Logs sem erros (`pm2 logs betauto`)

---

## 🆘 Suporte

Se encontrar problemas:

1. Verifique os logs: `pm2 logs betauto`
2. Teste manualmente: `cd /opt/betauto && source venv/bin/activate && python main.py`
3. Verifique o arquivo `.env`: `cat /opt/betauto/.env`
4. Verifique dependências: `pip list`

---

## 📌 Notas Importantes

- **Sempre use o ambiente virtual** antes de executar comandos Python: `source venv/bin/activate`
- **Mantenha o arquivo `.env` seguro** - nunca compartilhe suas credenciais
- **Faça backups regulares** do banco de dados: `cp /opt/betauto/betauto.sqlite3 /opt/betauto/backup/`
- **Monitore os logs regularmente** para identificar problemas rapidamente

---

**Última atualização:** Criado para facilitar o acesso e configuração do VPS.

