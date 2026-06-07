#!/bin/bash
# =============================================================
# diagnostic.sh — Diagnostic complet de la chaîne d'alerte
#
# Chaîne testée :
#   Caméra ─(RTSP local)─► Frigate ─(MQTT)─► alertes ─(API WapiWay)─► WhatsApp
#
# Important : le flux qui marche dans l'app EZVIZ passe par le CLOUD P2P,
# ça ne prouve PAS que le RTSP LOCAL (utilisé par Frigate) fonctionne.
# Ce script teste chaque maillon séparément.
#
# Usage : ./diagnostic.sh
# =============================================================

cd "$(dirname "$0")"
ENV_FILE=".env"
[ -f "$ENV_FILE" ] && { set -a; source "$ENV_FILE"; set +a; }

OK="✅"; KO="❌"; WARN="⚠️ "; INFO="ℹ️ "
SEP="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
PROBLEMES=()

echo "$SEP"
echo "🔎 DIAGNOSTIC SENTINEL — $(date '+%d/%m/%Y %H:%M')"
echo "$SEP"

# ---------------------------------------------------------------
# 0) Docker dispo + état des conteneurs
# ---------------------------------------------------------------
echo ""
echo "0️⃣  ÉTAT DES CONTENEURS"
echo "$SEP"
if ! command -v docker >/dev/null 2>&1; then
    echo "$KO Docker introuvable sur cette machine."
    PROBLEMES+=("Docker non installé / pas dans le PATH")
else
    docker compose ps 2>/dev/null || docker ps
    for SVC in frigate mosquitto alertes cam-watcher; do
        STATE=$(docker inspect -f '{{.State.Status}}' "$SVC" 2>/dev/null || echo "absent")
        case "$STATE" in
            running)    echo "$OK  $SVC : running" ;;
            restarting) echo "$KO  $SVC : RESTARTING (crash en boucle)"; PROBLEMES+=("$SVC redémarre en boucle → voir 'docker logs $SVC'") ;;
            exited)     echo "$KO  $SVC : ARRÊTÉ";                        PROBLEMES+=("$SVC est arrêté → 'docker compose up -d'") ;;
            absent)     echo "$WARN $SVC : absent" ;;
            *)          echo "$WARN $SVC : $STATE" ;;
        esac
    done
fi

# ---------------------------------------------------------------
# 1) RTSP LOCAL des caméras (ce que l'app EZVIZ ne teste PAS)
# ---------------------------------------------------------------
echo ""
echo "1️⃣  FLUX RTSP LOCAL DES CAMÉRAS"
echo "$SEP"
test_cam() {
    local NOM="$1" IP="$2" PORT="$3" PATH_="$4" PASS="$5"
    [ -z "$IP" ] && { echo "$WARN $NOM : IP non configurée — ignorée"; return; }
    echo "$INFO $NOM ($IP) ..."
    # a) joignable réseau ?
    if ! ping -c 1 -W 2 "$IP" >/dev/null 2>&1; then
        echo "  $KO Caméra injoignable sur le réseau ($IP)"
        PROBLEMES+=("$NOM injoignable ($IP) → IP changée (DHCP) ? câble/wifi ? Voir ./scan-network.sh")
        return
    fi
    echo "  $OK Ping OK"
    # b) RTSP réellement lisible ?
    local URL="rtsp://${FRIGATE_RTSP_USER}:${PASS}@${IP}:${PORT}${PATH_}"
    if command -v ffprobe >/dev/null 2>&1; then
        if ffprobe -v error -rtsp_transport tcp -timeout 5000000 \
             -show_entries stream=codec_name "$URL" >/dev/null 2>&1; then
            echo "  $OK RTSP local lisible"
        else
            echo "  $KO RTSP local INACCESSIBLE (mais cam pingable)"
            PROBLEMES+=("$NOM : RTSP local cassé → mot de passe changé ? RTSP désactivé dans l'app EZVIZ ? (le cloud marche quand même)")
        fi
    else
        echo "  $WARN ffprobe absent — test RTSP sauté (apt install ffmpeg)"
    fi
}
test_cam "rotissage_cam1" "${CAM_ROTISSAGE1_IP:-}" "${CAM_ROTISSAGE1_PORT:-554}" "${CAM_ROTISSAGE1_PATH:-}" "${CAM_ROTISSAGE1_PASSWORD:-}"
test_cam "rotissage_cam2" "${CAM_ROTISSAGE2_IP:-}" "${CAM_ROTISSAGE2_PORT:-554}" "${CAM_ROTISSAGE2_PATH:-}" "${CAM_ROTISSAGE2_PASSWORD:-}"

# ---------------------------------------------------------------
# 2) Frigate : santé + erreurs récentes
# ---------------------------------------------------------------
echo ""
echo "2️⃣  FRIGATE (détection)"
echo "$SEP"
if curl -sf "http://127.0.0.1:5000/api/version" >/dev/null 2>&1; then
    echo "$OK API Frigate répond (http://127.0.0.1:5000)"
else
    echo "$KO API Frigate ne répond pas"
    PROBLEMES+=("Frigate ne répond pas sur le port 5000")
fi
ERR=$(docker logs frigate --tail 80 2>&1 | grep -iE "error|failed|unable|timeout|No frames" | tail -8)
if [ -n "$ERR" ]; then
    echo "$WARN Dernières erreurs Frigate :"
    echo "$ERR" | sed 's/^/    /'
else
    echo "$OK Aucune erreur récente dans les logs Frigate"
fi

# ---------------------------------------------------------------
# 3) MQTT : events qui circulent ?
# ---------------------------------------------------------------
echo ""
echo "3️⃣  MQTT (mosquitto)"
echo "$SEP"
if docker exec mosquitto sh -c 'command -v mosquitto_sub' >/dev/null 2>&1; then
    echo "$INFO Écoute de 'frigate/events' pendant 30 s (provoque une détection devant la cam)..."
    if docker exec mosquitto mosquitto_sub -t 'frigate/events' -C 1 -W 30 >/dev/null 2>&1; then
        echo "$OK Au moins 1 event Frigate reçu sur MQTT → détection OK"
    else
        echo "$WARN Aucun event en 30 s → soit pas de mouvement, soit Frigate ne détecte plus"
    fi
else
    echo "$WARN mosquitto_sub indisponible dans le conteneur — test sauté"
fi

# ---------------------------------------------------------------
# 4) Service alertes : connexion MQTT + envois WapiWay
# ---------------------------------------------------------------
echo ""
echo "4️⃣  SERVICE ALERTES (envoi WhatsApp)"
echo "$SEP"
LOGS=$(docker logs alertes --tail 100 2>&1)
echo "$LOGS" | grep -iqE "mqtt.*(connect|connecté|connected)" \
    && echo "$OK alertes connecté à MQTT" \
    || { echo "$KO alertes PAS connecté à MQTT"; PROBLEMES+=("alertes ne se connecte pas à MQTT"); }

WAERR=$(echo "$LOGS" | grep -iE "401|403|unauthor|session|expir|invalid|déconnect|disconnect" | tail -6)
if [ -n "$WAERR" ]; then
    echo "$KO Erreurs côté WapiWay / WhatsApp :"
    echo "$WAERR" | sed 's/^/    /'
    PROBLEMES+=("Session WhatsApp WapiWay déconnectée / clé API invalide → rescanner le QR sur api.wapiway.tech")
else
    echo "$OK Aucune erreur d'authentification WapiWay récente"
fi
echo "$INFO Dernières lignes du service alertes :"
echo "$LOGS" | tail -6 | sed 's/^/    /'

# ---------------------------------------------------------------
# 5) API WapiWay joignable + clé présente
# ---------------------------------------------------------------
echo ""
echo "5️⃣  API WAPIWAY (clé + connectivité)"
echo "$SEP"
if [ -z "${WAPIWAY_API_KEY:-}" ]; then
    echo "$KO WAPIWAY_API_KEY absente du .env"
    PROBLEMES+=("WAPIWAY_API_KEY manquante dans .env")
else
    echo "$OK Clé API présente (${WAPIWAY_API_KEY:0:8}...)"
    HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
        -H "Authorization: Bearer ${WAPIWAY_API_KEY}" \
        "https://api.wapiway.tech/api/public/sessions" 2>/dev/null || echo "000")
    case "$HTTP" in
        200|202) echo "$OK API WapiWay joignable et clé acceptée (HTTP $HTTP)" ;;
        401|403) echo "$KO Clé API refusée (HTTP $HTTP)"; PROBLEMES+=("Clé WapiWay refusée (HTTP $HTTP) → régénérer la clé") ;;
        000)     echo "$KO Impossible de joindre api.wapiway.tech (pas d'internet ?)"; PROBLEMES+=("Pas d'accès internet vers api.wapiway.tech") ;;
        *)       echo "$WARN Réponse inattendue (HTTP $HTTP)" ;;
    esac
fi

# ---------------------------------------------------------------
# VERDICT
# ---------------------------------------------------------------
echo ""
echo "$SEP"
echo "🧾 VERDICT"
echo "$SEP"
if [ ${#PROBLEMES[@]} -eq 0 ]; then
    echo "$OK Aucun problème détecté sur la chaîne."
    echo "$INFO Si toujours pas d'alerte : provoque une vraie détection devant la cam"
    echo "    et relance le bloc 3️⃣ (MQTT)."
else
    echo "$KO ${#PROBLEMES[@]} problème(s) probable(s) détecté(s) :"
    i=1
    for P in "${PROBLEMES[@]}"; do
        echo "   $i) $P"
        i=$((i+1))
    done
fi
echo "$SEP"