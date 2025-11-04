# 🔄 Recriar Processo PM2 - BetAuto

## Passo a Passo para Recriar o PM2

Execute os comandos abaixo **no VPS**:

### 1. Parar e Remover o Processo Atual

```bash
# Parar o processo (se estiver rodando)
pm2 stop betauto

# Deletar o processo
pm2 delete betauto

# Verificar que foi removido
pm2 status
```

### 2. Verificar Diretório do Projeto

```bash
# Navegar para o diretório do projeto
cd /opt/betauto

# Verificar se está no diretório correto
pwd
ls -la main.py
```

### 3. Ativar Ambiente Virtual

```bash
# Ativar ambiente virtual
source venv/bin/activate

# Verificar que está ativado (deve mostrar o caminho do venv no prompt)
which python
```

### 4. Verificar Arquivo .env

```bash
# Verificar se .env existe
ls -la .env

# Se não existir, criar a partir do template
if [ ! -f ".env" ]; then
    cp env.template .env
    chmod 600 .env
    echo "⚠️  IMPORTANTE: Edite o arquivo .env com suas credenciais!"
    echo "Execute: nano .env"
fi
```

### 5. Recriar Processo PM2

```bash
# Certifique-se de estar no diretório correto e com venv ativado
cd /opt/betauto
source venv/bin/activate

# IMPORTANTE: Usar caminho absoluto do interpretador Python
pm2 start main.py --name betauto --interpreter /opt/betauto/venv/bin/python3 --cwd /opt/betauto

# Verificar status
pm2 status
```

### 6. Salvar Configuração do PM2

```bash
# Salvar configuração do PM2
pm2 save

# Configurar PM2 para iniciar no boot (se ainda não configurado)
pm2 startup
```

### 7. Verificar Logs

```bash
# Ver logs em tempo real
pm2 logs betauto

# Ver últimas 50 linhas
pm2 logs betauto --lines 50

# Ver apenas erros
pm2 logs betauto --err
```

---

## ⚡ Comando Completo (Copiar e Colar)

Execute este bloco completo:

```bash
#!/bin/bash
# Script para recriar PM2 BetAuto

echo "🛑 Parando e removendo processo atual..."
pm2 stop betauto 2>/dev/null || true
pm2 delete betauto 2>/dev/null || true

echo "📁 Navegando para diretório do projeto..."
cd /opt/betauto

echo "🐍 Ativando ambiente virtual..."
source venv/bin/activate

echo "✅ Verificando arquivo .env..."
if [ ! -f ".env" ]; then
    echo "⚠️  Arquivo .env não encontrado! Criando a partir do template..."
    cp env.template .env
    chmod 600 .env
    echo "⚠️  IMPORTANTE: Edite o arquivo .env com suas credenciais!"
fi

echo "🚀 Criando processo PM2..."
pm2 start main.py --name betauto --interpreter /opt/betauto/venv/bin/python3 --cwd /opt/betauto

echo "💾 Salvando configuração..."
pm2 save

echo "✅ Processo recriado!"
echo ""
echo "📊 Status:"
pm2 status
echo ""
echo "📋 Ver logs:"
echo "pm2 logs betauto"
```

---

## 🔍 Verificações Após Recriar

### Verificar Status

```bash
pm2 status
```

Deve mostrar:
- `betauto` com status `online`
- CPU e memória sendo usados

### Verificar Logs

```bash
pm2 logs betauto --lines 20
```

Procure por:
- ✅ Mensagens de inicialização sem erros
- ✅ Conexão com banco de dados OK
- ✅ Agendamento de jobs iniciado

### Verificar se Está Funcionando

```bash
# Ver processos Python rodando
ps aux | grep "python.*main.py"

# Ver uso de recursos
pm2 monit
```

---

## 🐛 Troubleshooting

### Problema: PM2 não inicia

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
pip install -r requirements.txt
```

### Problema: Erro de permissão

```bash
chmod 600 /opt/betauto/.env
chown -R root:root /opt/betauto
```

---

## 📋 Comandos Úteis do PM2

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

# Deletar
pm2 delete betauto

# Monitoramento em tempo real
pm2 monit

# Ver informações detalhadas
pm2 describe betauto
```

---

**Execute os comandos acima para recriar o processo PM2!**

