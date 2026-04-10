#!/bin/bash
# =============================================================
# healthcheck.sh — Vérifie les services et envoie un rapport WhatsApp
# via l'API WapiWay (https://api.wapiway.tech)
# Usage : ./healthcheck.sh  ou  crontab : 0 8 * * * /app/healthcheck.sh
# =============================================================

set -euo pipefail

# --- Charger le .env ---
ENV_FILE="$(dirname "$0")/.env"
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi

WAPIWAY_API_KEY="${WAPIWAY_API_KEY:-}"
WAPIWAY_BASE_URL="https://api.wapiway.tech/api/public"
# Numéros sans "+", séparés par virgule
WAPIWAY_PHONE_NUMBERS="${WAPIWAY_PHONE_NUMBERS:-}"
WAPIWAY_SESSION_ID="${WAPIWAY_SESSION_ID:-}"
FRIGATE_URL="${FRIGATE_URL:-http://frigate:5000}"

if [ -z "$WAPIWAY_API_KEY" ] || [ -z "$WAPIWAY_PHONE_NUMBERS" ]; then
    echo "❌ WAPIWAY_API_KEY ou WAPIWAY_PHONE_NUMBERS manquant"
    exit 1
fi

DATE=$(date '+%d/%m/%Y %H:%M')
GLOBAL_STATUS="✅"
RAPPORT=""

# --- Vérifier un conteneur Docker ---
check_container() {
    local name="$1"
    if docker ps --format '{{.Names}}' | grep -q "^${name}$"; then
        RAPPORT+="✅ *${name}* : en cours d'exécution\n"
    else
        RAPPORT+="❌ *${name}* : ARRÊTÉ\n"
        GLOBAL_STATUS="❌"
    fi
}

# --- Vérifier les conteneurs ---
RAPPORT+="📊 *RAPPORT SYSTÈME*\n"
RAPPORT+="🕐 ${DATE}\n\n"
RAPPORT+="🐳 *Services Docker :*\n"

check_container "frigate"
check_container "mosquitto"
check_container "alertes"

# --- Vérifier l'API Frigate ---
RAPPORT+="\n📹 *API Frigate :*\n"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${FRIGATE_URL}/api/stats" --max-time 5 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    STATS=$(curl -s "${FRIGATE_URL}/api/stats" --max-time 5 2>/dev/null)
    CAMERAS=$(echo "$STATS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len([c for c in d.get('cameras',{}) if d['cameras'][c].get('camera_fps',0)>0]))" 2>/dev/null || echo "?")
    RAPPORT+="✅ API accessible — ${CAMERAS} caméra(s) active(s)\n"
else
    RAPPORT+="❌ API inaccessible (HTTP ${HTTP_CODE})\n"
    GLOBAL_STATUS="❌"
fi

# --- Espace disque ---
RAPPORT+="\n💾 *Espace disque :*\n"
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}')
DISK_AVAIL=$(df -h / | awk 'NR==2 {print $4}')
RAPPORT+="Utilisé : ${DISK_USAGE} — Disponible : ${DISK_AVAIL}\n"

DISK_PCT=$(df / | awk 'NR==2 {print $5}' | tr -d '%')
if [ "$DISK_PCT" -gt 90 ]; then
    RAPPORT+="⚠️ *ATTENTION : disque presque plein !*\n"
    GLOBAL_STATUS="⚠️"
fi

# --- Résumé ---
RAPPORT+="\n${GLOBAL_STATUS} *Statut global : "
if [ "$GLOBAL_STATUS" = "✅" ]; then
    RAPPORT+="Tout fonctionne correctement*"
else
    RAPPORT+="Problème détecté — intervention requise*"
fi

# --- Envoi via WapiWay ---
IFS=',' read -ra PHONES <<< "$WAPIWAY_PHONE_NUMBERS"
for RAW_PHONE in "${PHONES[@]}"; do
    # Retirer le + si présent, trimmer les espaces
    PHONE=$(echo "$RAW_PHONE" | sed 's/^[[:space:]]*+\?//' | sed 's/[[:space:]]*$//')
    [ -z "$PHONE" ] && continue

    BODY="{\"phone_number\":\"${PHONE}\",\"content\":\"$(echo -e "$RAPPORT")\"}"

    # Ajouter session_id si configuré
    if [ -n "$WAPIWAY_SESSION_ID" ]; then
        BODY=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); d['session_id']='${WAPIWAY_SESSION_ID}'; print(json.dumps(d))")
    fi

    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
        "${WAPIWAY_BASE_URL}/messages/send-text" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${WAPIWAY_API_KEY}" \
        -d "$BODY" \
        --max-time 10)

    HTTP_STATUS=$(echo "$RESPONSE" | tail -1)
    RESP_BODY=$(echo "$RESPONSE" | sed '$d')

    if [ "$HTTP_STATUS" = "200" ] || [ "$HTTP_STATUS" = "202" ]; then
        echo "✅ Rapport envoyé à ${PHONE}"
    else
        echo "❌ Échec envoi à ${PHONE} — HTTP ${HTTP_STATUS}: ${RESP_BODY}"
    fi
done

echo "--- Healthcheck terminé ---"
