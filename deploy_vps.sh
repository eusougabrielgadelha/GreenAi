#!/usr/bin/expect -f
# Script para deploy automático no VPS
set timeout 300
set host "195.200.2.26"
set user "root"
set password "inDubai2023@"

spawn ssh ${user}@${host}

expect {
    "yes/no" {
        send "yes\r"
        exp_continue
    }
    "password:" {
        send "${password}\r"
    }
}

expect "# "
send "cd /tmp\r"
expect "# "

send "wget -q https://raw.githubusercontent.com/eusougabrielgadelha/GreenAi/main/install_vps.sh || curl -s -o install_vps.sh https://raw.githubusercontent.com/eusougabrielgadelha/GreenAi/main/install_vps.sh\r"
expect "# "

send "chmod +x install_vps.sh\r"
expect "# "

send "bash install_vps.sh\r"

# Aguardar instalação
expect {
    "✅ Instalação concluída!" {
        send "pm2 status\r"
        expect "# "
        send "pm2 logs betauto --lines 20\r"
        expect "# "
        send "exit\r"
    }
    timeout {
        send "pm2 status\r"
        expect "# "
        send "exit\r"
    }
}

expect eof

