# 🔧 Correção dos Problemas no VPS

## Problemas Identificados

1. ❌ Ambiente virtual não encontrado (`venv/bin/activate: No such file or directory`)
2. ❌ PM2 não está instalado (`Command 'pm2' not found`)
3. ⚠️ Diretório do projeto parece estar em `/opt/betauto/GreenAi` (subdiretório extra)

---

## ✅ Solução Passo a Passo

### ETAPA 1: Verificar Estrutura do Diretório

Execute no VPS:

```bash
# Verificar onde você está
pwd

# Ver estrutura do diretório
ls -la /opt/betauto/
ls -la /opt/betauto/GreenAi/ 2>/dev/null || echo "Diretório não existe"
```

---

### ETAPA 2: Corrigir Estrutura do Diretório (se necessário)

Se o projeto está em `/opt/betauto/GreenAi`, você precisa mover os arquivos para `/opt/betauto`:

```bash
# Entrar no diretório do projeto
cd /opt/betauto

# Se existir subdiretório GreenAi, mover conteúdo para o diretório pai
if [ -d "GreenAi" ]; then
    echo "Movendo arquivos do subdiretório..."
    mv GreenAi/* .
    mv GreenAi/.* . 2>/dev/null || true
    rmdir GreenAi
    echo "✅ Arquivos movidos com sucesso"
fi

# Verificar se main.py está no diretório correto
ls -la /opt/betauto/main.py
```

---

### ETAPA 3: Instalar PM2

```bash
# Instalar Node.js (se ainda não estiver instalado)
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs

# Instalar PM2 globalmente
npm install -g pm2

# Verificar instalação
pm2 --version
```

---

### ETAPA 4: Criar Ambiente Virtual Python

```bash
# Navegar para o diretório do projeto
cd /opt/betauto

# Remover ambiente virtual antigo (se existir)
rm -rf venv

# Criar novo ambiente virtual
python3 -m venv venv

# Ativar ambiente virtual
source venv/bin/activate

# Verificar que está ativado (deve mostrar o caminho do venv no prompt)
which python
```

---

### ETAPA 5: Instalar Dependências Python

```bash
# Certifique-se de que o venv está ativado
cd /opt/betauto
source venv/bin/activate

# Atualizar pip
pip install --upgrade pip

# Instalar dependências
pip install -r requirements.txt

# Instalar navegadores do Playwright (opcional mas recomendado)
playwright install chromium || echo "Playwright opcional, continuando..."
```

---

### ETAPA 6: Verificar Arquivo .env

```bash
cd /opt/betauto

# Verificar se .env existe
if [ ! -f ".env" ]; then
    echo "Criando arquivo .env..."
    cp env.template .env
    chmod 600 .env
    echo "⚠️  IMPORTANTE: Edite o arquivo .env com suas credenciais!"
    echo "Execute: nano .env"
else
    echo "✅ Arquivo .env já existe"
fi

# Verificar permissões
chmod 600 .env
```

---

### ETAPA 7: Iniciar Aplicação com PM2

```bash
cd /opt/betauto

# Parar processo antigo se existir
pm2 delete betauto 2>/dev/null || true

# Iniciar aplicação
pm2 start main.py --name betauto --interpreter venv/bin/python3 --cwd /opt/betauto

# Salvar configuração
pm2 save

# Configurar PM2 para iniciar no boot
pm2 startup

# Verificar status
pm2 status
```

---

### ETAPA 8: Verificar Logs

```bash
# Ver logs em tempo real
pm2 logs betauto

# Ver últimas 50 linhas
pm2 logs betauto --lines 50

# Ver apenas erros
pm2 logs betauto --err
```

---

## 🚀 Comando Completo de Correção (Copiar e Colar)

Execute este bloco completo no VPS:

```bash
#!/bin/bash
# Script de correção rápida

echo "🔧 Corrigindo estrutura do projeto..."
cd /opt/betauto

# Mover arquivos se necessário
if [ -d "GreenAi" ]; then
    echo "Movendo arquivos..."
    mv GreenAi/* .
    mv GreenAi/.* . 2>/dev/null || true
    rmdir GreenAi
fi

echo "📦 Instalando Node.js e PM2..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs
npm install -g pm2

echo "🐍 Criando ambiente virtual..."
rm -rf venv
python3 -m venv venv
source venv/bin/activate

echo "📦 Instalando dependências Python..."
pip install --upgrade pip
pip install -r requirements.txt

echo "⚙️  Configurando .env..."
if [ ! -f ".env" ]; then
    cp env.template .env
    chmod 600 .env
    echo "⚠️  Edite o .env com suas credenciais!"
fi

echo "🚀 Iniciando aplicação..."
pm2 delete betauto 2>/dev/null || true
pm2 start main.py --name betauto --interpreter venv/bin/python3 --cwd /opt/betauto
pm2 save
pm2 startup

echo "✅ Correção concluída!"
echo ""
echo "Verifique o status:"
pm2 status
echo ""
echo "Ver logs:"
echo "pm2 logs betauto"
```

---

## ✅ Checklist de Verificação

Execute estes comandos para verificar se tudo está correto:

```bash
# 1. Verificar estrutura
ls -la /opt/betauto/main.py

# 2. Verificar ambiente virtual
ls -la /opt/betauto/venv/bin/activate

# 3. Verificar PM2
pm2 --version

# 4. Verificar dependências Python
cd /opt/betauto
source venv/bin/activate
pip list | grep -E "(beautifulsoup4|requests|APScheduler)"

# 5. Verificar arquivo .env
ls -la /opt/betauto/.env

# 6. Verificar status do PM2
pm2 status

# 7. Verificar logs
pm2 logs betauto --lines 20
```

---

## 🐛 Se Ainda Houver Problemas

### Problema: PM2 não inicia a aplicação

```bash
# Testar manualmente primeiro
cd /opt/betauto
source venv/bin/activate
python main.py
```

Se funcionar manualmente, mas não com PM2:

```bash
# Ver detalhes do erro
pm2 logs betauto --err --lines 50

# Verificar se o caminho está correto
pm2 describe betauto
```

### Problema: Erro de módulo não encontrado

```bash
cd /opt/betauto
source venv/bin/activate
pip install -r requirements.txt --force-reinstall
```

### Problema: Erro de permissão

```bash
chmod 600 /opt/betauto/.env
chown -R root:root /opt/betauto
```

---

## 📋 Comandos Rápidos de Referência

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

# Deletar e recriar
pm2 delete betauto
pm2 start main.py --name betauto --interpreter venv/bin/python3 --cwd /opt/betauto
pm2 save
```

---

**Execute os comandos na ordem acima para corrigir os problemas!**

