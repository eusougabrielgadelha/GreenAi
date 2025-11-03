# Script PowerShell para deploy no VPS
$hostname = "195.200.2.26"
$username = "root"
$password = "inDubai2023@"

Write-Host "🚀 Conectando ao VPS e iniciando instalação..." -ForegroundColor Green

# Instalar módulo SSH se necessário
if (-not (Get-Module -ListAvailable -Name Posh-SSH)) {
    Write-Host "📦 Instalando módulo Posh-SSH..." -ForegroundColor Yellow
    Install-Module -Name Posh-SSH -Force -Scope CurrentUser -AllowClobber
}

Import-Module Posh-SSH

# Criar credencial segura
$securePassword = ConvertTo-SecureString $password -AsPlainText -Force
$credential = New-Object System.Management.Automation.PSCredential($username, $securePassword)

try {
    # Conectar ao VPS
    Write-Host "🔌 Conectando ao VPS $hostname..." -ForegroundColor Cyan
    $session = New-SSHSession -ComputerName $hostname -Credential $credential -AcceptKey
    
    if ($session) {
        Write-Host "✅ Conectado com sucesso!" -ForegroundColor Green
        
        # Comandos para executar no VPS
        $commands = @"
cd /tmp
wget -q https://raw.githubusercontent.com/eusougabrielgadelha/GreenAi/main/install_vps.sh || curl -s -o install_vps.sh https://raw.githubusercontent.com/eusougabrielgadelha/GreenAi/main/install_vps.sh
chmod +x install_vps.sh
bash install_vps.sh
"@
        
        Write-Host "📥 Executando instalação..." -ForegroundColor Cyan
        $result = Invoke-SSHCommand -SessionId $session.SessionId -Command $commands
        
        Write-Host "📊 Output da instalação:" -ForegroundColor Yellow
        Write-Host $result.Output
        
        if ($result.Error) {
            Write-Host "⚠️  Erros:" -ForegroundColor Red
            Write-Host $result.Error
        }
        
        # Verificar status do PM2
        Write-Host "`n🔍 Verificando status do PM2..." -ForegroundColor Cyan
        $status = Invoke-SSHCommand -SessionId $session.SessionId -Command "pm2 status"
        Write-Host $status.Output
        
        # Fechar sessão
        Remove-SSHSession -SessionId $session.SessionId | Out-Null
        Write-Host "`n✅ Instalação concluída!" -ForegroundColor Green
        
    } else {
        Write-Host "❌ Falha ao conectar ao VPS" -ForegroundColor Red
    }
    
} catch {
    Write-Host "❌ Erro: $_" -ForegroundColor Red
    Write-Host "`n💡 Alternativa: Execute manualmente no VPS:" -ForegroundColor Yellow
    Write-Host "ssh root@195.200.2.26" -ForegroundColor Cyan
    Write-Host "bash <(curl -s https://raw.githubusercontent.com/eusougabrielgadelha/GreenAi/main/install_vps.sh)" -ForegroundColor Cyan
}

