# 🔧 Corrigir Ambiente Virtual no VPS

## Problema Identificado

- ❌ O diretório `venv` não existe em `/opt/betauto`
- ❌ O Python ativo é de outro projeto (`/opt/rouletgreen/.venv/bin/python`)
- ✅ O arquivo `main.py` existe
- ✅ O arquivo `.env` existe

## ✅ Solução - Criar Ambiente Virtual

Execute os comandos abaixo **na ordem**:

### 1. Verificar Estrutura Atual

```bash
cd /opt/betauto
ls -la
```

### 2. Criar Ambiente Virtual

```bash
cd /opt/betauto

# Criar ambiente virtual
python3 -m venv venv

# Verificar se foi criado
ls -la venv/
```

### 3. Ativar Ambiente Virtual

```bash
cd /opt/betauto
source venv/bin/activate

# Verificar que está ativado (deve mostrar /opt/betauto/venv no prompt)
which python
# Deve mostrar: /opt/betauto/venv/bin/python
```

### 4. Atualizar pip e Instalar Dependências

```bash
cd /opt/betauto
source venv/bin/activate

# Atualizar pip
pip install --upgrade pip

# Instalar dependências
pip install -r requirements.txt
```

### 5. Verificar Instalação

```bash
cd /opt/betauto
source venv/bin/activate

# Verificar se as dependências foram instaladas
pip list | grep -E "(beautifulsoup4|requests|APScheduler|SQLAlchemy)"
```

### 6. Recriar PM2

```bash
cd /opt/betauto

# Verificar caminho do Python no venv
ls -la venv/bin/python3

# Se existir, criar PM2
pm2 start main.py --name betauto --interpreter /opt/betauto/venv/bin/python3 --cwd /opt/betauto

# Salvar configuração
pm2 save

# Verificar status
pm2 status
```

---

## ⚡ Script Completo (Copiar e Colar)

Execute este bloco completo:

```bash
#!/bin/bash
cd /opt/betauto

echo "🐍 Criando ambiente virtual..."
python3 -m venv venv

echo "✅ Ativando ambiente virtual..."
source venv/bin/activate

echo "📦 Atualizando pip..."
pip install --upgrade pip

echo "📦 Instalando dependências..."
pip install -r requirements.txt

echo "✅ Verificando instalação..."
pip list | head -10

echo "🚀 Criando processo PM2..."
pm2 delete betauto 2>/dev/null || true
pm2 start main.py --name betauto --interpreter /opt/betauto/venv/bin/python3 --cwd /opt/betauto
pm2 save

echo "✅ Concluído!"
echo ""
pm2 status
```

---

## 🔍 Verificações

### Verificar se venv foi criado

```bash
cd /opt/betauto
ls -la venv/bin/python3
```

### Verificar se está usando o Python correto

```bash
cd /opt/betauto
source venv/bin/activate
which python
# Deve mostrar: /opt/betauto/venv/bin/python
```

### Testar execução manual

```bash
cd /opt/betauto
source venv/bin/activate
python main.py
```

Pressione `Ctrl+C` após verificar que está funcionando.

---

## 🐛 Troubleshooting

### Problema: python3 não encontrado

```bash
# Verificar se Python está instalado
which python3
python3 --version

# Se não estiver, instalar
apt update
apt install -y python3 python3-pip python3-venv
```

### Problema: Erro ao criar venv

```bash
# Verificar permissões
ls -la /opt/betauto/

# Se necessário, ajustar permissões
chown -R root:root /opt/betauto
```

### Problema: Dependências não instalam

```bash
cd /opt/betauto
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt --no-cache-dir
```

---

**Execute os comandos acima para criar o ambiente virtual e configurar o PM2!**

