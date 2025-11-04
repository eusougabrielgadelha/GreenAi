"""Servidor HTTP simples para visualizar logs (sem dependências externas)."""
import os
import sys
import http.server
import socketserver
from pathlib import Path

# Adiciona o diretório raiz ao path para importar config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config.settings import LOG_DIR
except ImportError:
    # Fallback se não conseguir importar
    LOG_DIR = os.getenv('LOG_DIR', 'logs')

# Porta padrão
PORT = int(os.getenv('LOG_VIEWER_PORT', 5000))
LOG_PATH = Path(LOG_DIR).resolve()


class LogRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Handler customizado para servir logs com interface amigável."""
    
    def end_headers(self):
        """Adiciona headers CORS opcionais."""
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()
    
    def do_GET(self):
        """Processa requisições GET."""
        # Se for a raiz, serve a página HTML customizada
        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(self.get_index_html().encode('utf-8'))
            return
        
        # Se for um arquivo de log específico, serve diretamente
        if self.path.startswith('/betauto.log'):
            file_path = LOG_PATH / self.path.lstrip('/')
            if file_path.exists() and file_path.is_file():
                self.send_response(200)
                self.send_header('Content-type', 'text/plain; charset=utf-8')
                self.send_header('Content-Length', str(file_path.stat().st_size))
                self.end_headers()
                with open(file_path, 'rb') as f:
                    self.wfile.write(f.read())
                return
        
        # Caso contrário, serve arquivos estáticos do diretório de logs
        self.path = str(LOG_PATH / self.path.lstrip('/'))
        return super().do_GET()
    
    def get_index_html(self):
        """Retorna HTML da página principal."""
        # Lista arquivos de log disponíveis
        log_files = []
        for i in range(6):
            if i == 0:
                filename = "betauto.log"
            else:
                filename = f"betauto.log.{i}"
            file_path = LOG_PATH / filename
            if file_path.exists():
                size = file_path.stat().st_size
                size_mb = size / (1024 * 1024)
                log_files.append({
                    'name': filename,
                    'size': f"{size_mb:.2f} MB",
                    'url': f"/{filename}"
                })
        
        files_html = '\n'.join([
            f'        <li><a href="{f["url"]}" target="_blank">{f["name"]}</a> <span style="color: #888;">({f["size"]})</span></li>'
            for f in log_files
        ])
        
        return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Logs - BetAuto</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #1a1a1a;
            color: #e0e0e0;
            padding: 20px;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{
            color: #4CAF50;
            margin-bottom: 10px;
            font-size: 28px;
        }}
        .subtitle {{
            color: #888;
            margin-bottom: 30px;
            font-size: 14px;
        }}
        .info-box {{
            background: #2a2a2a;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }}
        .info-box h2 {{
            color: #4CAF50;
            margin-bottom: 15px;
            font-size: 20px;
        }}
        .file-list {{
            list-style: none;
            padding: 0;
        }}
        .file-list li {{
            padding: 12px;
            margin: 8px 0;
            background: #1a1a1a;
            border-radius: 4px;
            border-left: 3px solid #4CAF50;
        }}
        .file-list a {{
            color: #4CAF50;
            text-decoration: none;
            font-weight: bold;
            font-size: 16px;
        }}
        .file-list a:hover {{
            color: #66BB6A;
            text-decoration: underline;
        }}
        .instructions {{
            background: #2a2a2a;
            padding: 20px;
            border-radius: 8px;
            margin-top: 20px;
        }}
        .instructions h3 {{
            color: #4CAF50;
            margin-bottom: 10px;
        }}
        .instructions ul {{
            margin-left: 20px;
            color: #bbb;
        }}
        .instructions li {{
            margin: 8px 0;
        }}
        code {{
            background: #1a1a1a;
            padding: 2px 6px;
            border-radius: 3px;
            color: #4CAF50;
            font-family: 'Courier New', monospace;
        }}
        .note {{
            background: #3a2a1a;
            border-left: 3px solid #ff9800;
            padding: 15px;
            margin-top: 20px;
            border-radius: 4px;
        }}
        .note strong {{
            color: #ff9800;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📋 Visualizador de Logs - BetAuto</h1>
        <p class="subtitle">Servidor HTTP simples - Sem dependências externas</p>
        
        <div class="info-box">
            <h2>📁 Arquivos de Log Disponíveis</h2>
            <ul class="file-list">
{files_html if files_html else '                <li style="color: #888;">Nenhum arquivo de log encontrado.</li>'}
            </ul>
        </div>
        
        <div class="instructions">
            <h3>📖 Como Usar</h3>
            <ul>
                <li>Clique em qualquer arquivo acima para visualizar o log completo</li>
                <li>Use <code>Ctrl+F</code> (ou <code>Cmd+F</code> no Mac) para buscar dentro do log</li>
                <li>Use <code>Ctrl+End</code> para ir ao final do arquivo (logs mais recentes)</li>
                <li>Os arquivos são listados do mais recente (betauto.log) ao mais antigo (betauto.log.5)</li>
            </ul>
        </div>
        
        <div class="note">
            <strong>💡 Dica:</strong> Para melhor experiência, use a busca do navegador (<code>Ctrl+F</code>) 
            para encontrar palavras-chave, níveis de log (ERROR, WARNING, INFO), ou horários específicos.
        </div>
        
        <div class="info-box" style="margin-top: 20px;">
            <h2>📊 Informações do Servidor</h2>
            <p><strong>Diretório de logs:</strong> <code>{LOG_PATH}</code></p>
            <p><strong>Porta:</strong> <code>{PORT}</code></p>
            <p><strong>URL:</strong> <code>http://{self.server.server_name or 'localhost'}:{PORT}</code></p>
        </div>
    </div>
</body>
</html>"""


def main():
    """Inicia o servidor HTTP."""
    # Verificar se o diretório de logs existe
    if not LOG_PATH.exists():
        print(f"❌ Erro: Diretório de logs não encontrado: {LOG_PATH}")
        print(f"   Verifique a variável LOG_DIR no config/settings.py ou .env")
        return
    
    # Mudar para o diretório de logs para servir arquivos
    os.chdir(LOG_PATH)
    
    # Criar servidor
    with socketserver.TCPServer(("", PORT), LogRequestHandler) as httpd:
        print(f"🌐 Servidor de logs iniciado!")
        print(f"📁 Diretório: {LOG_PATH}")
        print(f"🔗 URL: http://localhost:{PORT}")
        print(f"🌍 Para acesso externo: http://<IP_DO_SERVIDOR>:{PORT}")
        print(f"⏹️  Pressione Ctrl+C para parar\n")
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n🛑 Servidor interrompido pelo usuário.")


if __name__ == '__main__':
    main()

