# 🔧 Correção do Git no VPS

## Problema

O diretório `/opt/betauto` não é um repositório git. Isso acontece quando:
- O projeto foi copiado sem o diretório `.git`
- O projeto foi instalado via script que não manteve o git
- O diretório `.git` foi removido acidentalmente

## ✅ Solução

### Opção 1: Clonar o Repositório Novamente (Recomendado)

Se você não tem alterações locais importantes, a melhor opção é clonar novamente:

```bash
# 1. Fazer backup do arquivo .env (se existir)
cd /opt/betauto
cp .env /tmp/.env.backup 2>/dev/null || echo "Arquivo .env não encontrado"

# 2. Voltar para o diretório pai
cd /opt

# 3. Remover o diretório antigo (se não tiver dados importantes)
rm -rf betauto

# 4. Clonar o repositório novamente
git clone https://github.com/eusougabrielgadelha/GreenAi.git betauto

# 5. Entrar no diretório
cd betauto

# 6. Restaurar o arquivo .env
cp /tmp/.env.backup .env 2>/dev/null || echo "Restaurando .env..."
chmod 600 .env

# 7. Verificar se está funcionando
git status
```

### Opção 2: Inicializar Git no Diretório Existente

Se você tem alterações locais ou configurações que não quer perder:

```bash
cd /opt/betauto

# 1. Fazer backup de arquivos importantes
cp .env /tmp/.env.backup 2>/dev/null
cp betauto.sqlite3 /tmp/betauto.sqlite3.backup 2>/dev/null || true

# 2. Inicializar git
git init

# 3. Adicionar remote
git remote add origin https://github.com/eusougabrielgadelha/GreenAi.git

# 4. Fazer fetch do repositório
git fetch origin

# 5. Fazer checkout da branch main
git checkout -b main origin/main

# 6. Verificar se está funcionando
git status

# 7. Restaurar arquivos de backup
cp /tmp/.env.backup .env 2>/dev/null || echo "Restaurando .env..."
chmod 600 .env
```

### Opção 3: Verificar se o Git está em Outro Diretório

Talvez o projeto esteja em outro lugar:

```bash
# Procurar diretórios .git
find /opt -name ".git" -type d 2>/dev/null

# Verificar se há outro diretório do projeto
ls -la /opt/
ls -la /opt/betauto/
```

## 🔄 Após Corrigir

Depois de ter o git funcionando, você pode:

```bash
cd /opt/betauto

# Atualizar o código
git pull origin main

# Verificar status
git status

# Ver últimos commits
git log --oneline -5
```

## 📝 Comandos Úteis

```bash
# Verificar se é repositório git
git status

# Ver remote configurado
git remote -v

# Verificar branch atual
git branch

# Ver histórico de commits
git log --oneline -10

# Atualizar código
git pull origin main
```

---

**Execute os comandos da Opção 1 se não tiver dados importantes locais, ou Opção 2 se quiser manter o que está no servidor.**

