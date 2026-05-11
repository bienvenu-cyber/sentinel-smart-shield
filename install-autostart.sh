#!/bin/bash
# =============================================================
# install-autostart.sh
# Installe le service systemd pour que Sentinel démarre
# automatiquement au boot du serveur Linux.
#
# Couplé avec `restart: always` dans docker-compose.yml,
# ceci garantit que :
#   - Docker démarre au boot
#   - La stack (Frigate, Mosquitto, Alertes, Cloudflared) démarre au boot
#   - Tout conteneur qui tombe est relancé automatiquement par Docker
#
# Usage : sudo ./install-autostart.sh
# =============================================================

set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "❌ Ce script doit être lancé en root : sudo ./install-autostart.sh"
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_SRC="${PROJECT_DIR}/systemd/sentinel.service"
SERVICE_DST="/etc/systemd/system/sentinel.service"

echo "📁 Dossier projet : ${PROJECT_DIR}"

# 1. S'assurer que Docker démarre au boot
echo "🐳 Activation de Docker au démarrage..."
systemctl enable docker
systemctl start docker

# 2. Copier l'unité systemd avec le bon WorkingDirectory
echo "📝 Installation de l'unité systemd..."
sed "s|/opt/sentinel|${PROJECT_DIR}|g" "${SERVICE_SRC}" > "${SERVICE_DST}"
chmod 644 "${SERVICE_DST}"

# 3. Recharger systemd et activer le service
echo "🔄 Activation du service sentinel..."
systemctl daemon-reload
systemctl enable sentinel.service

echo ""
echo "✅ Installation terminée."
echo ""
echo "Commandes utiles :"
echo "  sudo systemctl start sentinel     # Démarrer maintenant"
echo "  sudo systemctl stop sentinel      # Arrêter la stack"
echo "  sudo systemctl status sentinel    # Voir l'état"
echo "  sudo systemctl reload sentinel    # Recréer les conteneurs"
echo "  sudo systemctl disable sentinel   # Désactiver l'autostart"
echo ""
echo "👉 La stack démarrera automatiquement au prochain reboot."
echo "👉 Pour la lancer dès maintenant : sudo systemctl start sentinel"