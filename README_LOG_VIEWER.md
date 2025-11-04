# 📋 Visualizador de Logs Web - Opção Simples

Interface web **ultra-simples** para visualizar os logs do BetAuto no navegador. **Zero dependências externas** - usa apenas Python padrão.

## ✅ Vantagens

- ✅ **Zero dependências** - Não precisa instalar nada além do Python
- ✅ **Super leve** - Usa apenas módulos built-in do Python
- ✅ **Rápido de iniciar** - Um comando e pronto
- ✅ **Seguro** - Serve apenas arquivos de log, nada mais

## 🚀 Como Usar

### 1. Executar o servidor

```bash
python web/serve_logs.py
```

### 2. Acessar no navegador

Abra: `http://195.200.2.26:5000` (ou o IP do seu servidor)

### 3. Visualizar logs

- Clique em qualquer arquivo de log para visualizar
- Use `Ctrl+F` (ou `Cmd+F` no Mac) para buscar
- Use `Ctrl+End` para ir ao final do arquivo (logs mais recentes)

## ⚙️ Configuração (Opcional)

No arquivo `.env`, você pode configurar:

```env
# Porta do servidor de logs (padrão: 5000)
LOG_VIEWER_PORT=5000
```

## 🔧 Executar como Serviço (Opcional)

Para rodar o visualizador de logs como serviço no Linux:

### Criar arquivo de serviço
```bash
sudo nano /etc/systemd/system/log-viewer.service
```

Conteúdo:
```ini
[Unit]
Description=Log Viewer - BetAuto (Simple HTTP Server)
After=network.target

[Service]
Type=simple
User=seu_usuario
WorkingDirectory=/opt/betauto
Environment="PATH=/opt/betauto/venv/bin"
Environment="LOG_VIEWER_PORT=5000"
ExecStart=/opt/betauto/venv/bin/python web/serve_logs.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Ativar serviço
```bash
sudo systemctl daemon-reload
sudo systemctl enable log-viewer.service
sudo systemctl start log-viewer.service
sudo systemctl status log-viewer.service
```

## 🔒 Segurança

⚠️ **Importante**: Este servidor expõe os logs publicamente na porta configurada. Para produção, recomenda-se:

1. **Restringir acesso por firewall**:
   ```bash
   # Permitir apenas IPs específicos
   sudo ufw allow from SEU_IP to any port 5000
   ```

2. **Usar Nginx como proxy reverso** com autenticação:
   ```nginx
   server {{
       listen 80;
       server_name 195.200.2.26;

       location /logs {{
           proxy_pass http://127.0.0.1:5000;
           proxy_set_header Host $host;
           
           auth_basic "Log Viewer";
           auth_basic_user_file /etc/nginx/.htpasswd;
       }}
   }}
   ```

3. **Usar SSH Tunnel** (mais seguro):
   ```bash
   # No seu computador local
   ssh -L 5000:localhost:5000 usuario@195.200.2.26
   
   # Depois acesse: http://localhost:5000
   ```

## 📊 Funcionalidades

- ✅ Lista todos os arquivos de log disponíveis
- ✅ Mostra tamanho de cada arquivo
- ✅ Links diretos para visualizar cada log
- ✅ Interface simples e responsiva
- ✅ Tema escuro para melhor legibilidade

## 🎯 Limitações

- ❌ Não tem busca avançada (use `Ctrl+F` do navegador)
- ❌ Não tem filtros por nível (use `Ctrl+F` para buscar "ERROR", "WARNING", etc.)
- ❌ Não atualiza automaticamente (recarregue a página manualmente)
- ❌ Não tem paginação (carrega o arquivo inteiro)

**Para funcionalidades avançadas, use a opção 2 (Flask) descrita no código.**

## 🔄 Alternativa: Servidor HTTP Ainda Mais Simples

Se quiser algo ainda mais básico (sem interface HTML):

```bash
# No diretório de logs
cd logs
python -m http.server 5000

# Acessar: http://195.200.2.26:5000
# Listará todos os arquivos como links simples
```

## 📝 Exemplo de Uso

```bash
# Terminal 1: Iniciar servidor
$ python web/serve_logs.py
🌐 Servidor de logs iniciado!
📁 Diretório: /opt/betauto/logs
🔗 URL: http://localhost:5000
🌍 Para acesso externo: http://195.200.2.26:5000

# Navegador: Acessar
http://195.200.2.26:5000

# Ver lista de arquivos, clicar em "betauto.log"
# Usar Ctrl+F para buscar "ERROR" ou outras palavras-chave
```

## 🎉 Pronto!

Agora você pode visualizar seus logs facilmente no navegador, sem precisar instalar nada além do Python!
