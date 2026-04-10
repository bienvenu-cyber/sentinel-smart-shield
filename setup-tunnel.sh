#!/bin/bash
# =============================================================
# setup-tunnel.sh — Configure un Cloudflare Tunnel pour Frigate
# Prérequis : compte Cloudflare gratuit + domaine ajouté (gratuit aussi)
# =============================================================

set -euo pipefail

echo "========================================"
echo "  Configuration Cloudflare Tunnel"
echo "========================================"
echo ""

# Vérifier cloudflared
if ! command -v cloudflared &> /dev/null; then
    echo "📥 Installation de cloudflared..."
    curl -L --output /tmp/cloudflared.deb \
        https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
    sudo dpkg -i /tmp/cloudflared.deb
    rm /tmp/cloudflared.deb
    echo "✅ cloudflared installé"
fi

echo ""
echo "📋 Étapes :"
echo ""
echo "1️⃣  Va sur https://one.dash.cloudflare.com"
echo "    → Networks → Tunnels → Create a tunnel"
echo ""
echo "2️⃣  Choisis 'Cloudflared' comme méthode de connexion"
echo ""
echo "3️⃣  Donne un nom au tunnel, ex: 'frigate-surveillance'"
echo ""
echo "4️⃣  Copie le TOKEN affiché (commence par 'eyJ...')"
echo ""
echo "5️⃣  Configure la route publique :"
echo "    - Subdomain : frigate (ou ce que tu veux)"
echo "    - Domain : tondomaine.com"
echo "    - Service : http://frigate:5000"
echo ""
echo "6️⃣  Colle le token dans le .env :"
echo "    CLOUDFLARE_TUNNEL_TOKEN=eyJ..."
echo ""
echo "7️⃣  Mets l'URL publique dans le .env :"
echo "    FRIGATE_PUBLIC_URL=https://frigate.tondomaine.com"
echo ""

read -p "As-tu le token ? Colle-le ici (ou Ctrl+C pour annuler) : " TOKEN

if [ -n "$TOKEN" ]; then
    # Mettre à jour le .env
    if [ -f .env ]; then
        # Remplacer ou ajouter CLOUDFLARE_TUNNEL_TOKEN
        if grep -q "CLOUDFLARE_TUNNEL_TOKEN" .env; then
            sed -i "s|CLOUDFLARE_TUNNEL_TOKEN=.*|CLOUDFLARE_TUNNEL_TOKEN=${TOKEN}|" .env
        else
            echo "CLOUDFLARE_TUNNEL_TOKEN=${TOKEN}" >> .env
        fi
        echo ""
        echo "✅ Token sauvegardé dans .env"
    else
        echo "⚠️  Fichier .env introuvant. Copie .env.example vers .env d'abord."
        echo "    cp .env.example .env"
    fi
fi

echo ""
echo "🚀 Pour démarrer : docker compose up -d"
echo "   Le tunnel sera actif automatiquement."
echo ""
