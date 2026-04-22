#!/bin/bash
# =============================================================
# test-rtsp.sh — Teste une URL RTSP avant de l'ajouter dans Frigate
# Usage : ./test-rtsp.sh rtsp://user:pass@192.168.1.13:554/stream
# =============================================================

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage : $0 rtsp://user:pass@IP:PORT/CHEMIN"
    echo ""
    echo "Chemins RTSP courants à essayer :"
    echo "  /stream            (générique)"
    echo "  /live              (Hikvision lite)"
    echo "  /h264              (Foscam)"
    echo "  /live/ch00_0       (V380 / Xiaomi)"
    echo "  /onvif1            (ONVIF)"
    echo "  /Streaming/Channels/101  (Hikvision)"
    echo "  /cam/realmonitor?channel=1&subtype=0  (Dahua)"
    exit 1
fi

URL="$1"

if ! command -v ffprobe >/dev/null 2>&1; then
    echo "❌ ffprobe non installé. Installer : sudo apt install ffmpeg"
    exit 1
fi

echo "🔍 Test de : $URL"
echo ""

OUTPUT=$(ffprobe -v error -rtsp_transport tcp -timeout 5000000 \
    -show_entries stream=codec_name,width,height,r_frame_rate \
    -of default=noprint_wrappers=1 \
    "$URL" 2>&1) || {
    echo "❌ Échec de connexion RTSP"
    echo "$OUTPUT"
    exit 2
}

echo "✅ Flux RTSP accessible !"
echo "$OUTPUT"
echo ""
echo "→ URL prête à être utilisée dans .env / config/frigate.yml"
