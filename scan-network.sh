#!/bin/bash
# =============================================================
# scan-network.sh — Scanne le réseau local pour trouver les caméras IP
# Usage : ./scan-network.sh           (auto-détecte le réseau)
#         ./scan-network.sh 192.168.1.0/24
# =============================================================

set -euo pipefail

NETWORK="${1:-}"

if [ -z "$NETWORK" ]; then
    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || ipconfig getifaddr en0 2>/dev/null || echo "")
    if [ -z "$LOCAL_IP" ]; then
        echo "❌ Impossible de détecter l'IP locale. Préciser le réseau : $0 192.168.1.0/24"
        exit 1
    fi
    NETWORK="${LOCAL_IP%.*}.0/24"
fi

echo "🔍 Scan du réseau $NETWORK pour caméras IP (ports RTSP/HTTP)..."
echo ""

if ! command -v nmap >/dev/null 2>&1; then
    echo "❌ nmap non installé. Installer :"
    echo "   Ubuntu/Debian : sudo apt install nmap"
    echo "   macOS         : brew install nmap"
    exit 1
fi

nmap -p 80,554,8000,8080,8554,8899 --open -T4 "$NETWORK" \
    | grep -E "Nmap scan report|554/tcp|8554/tcp|8899/tcp|80/tcp"

echo ""
echo "→ Pour chaque IP avec port 554 ouvert, tester le flux :"
echo "   ./test-rtsp.sh rtsp://user:pass@IP:554/stream"
