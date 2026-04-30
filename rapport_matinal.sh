#!/bin/bash
# =============================================================
# rapport_matinal.sh — Résumé WhatsApp des événements de la nuit
# Envoyé UNIQUEMENT s'il y a eu au moins 1 événement détecté
# entre la dernière heure ouvrée d'hier et maintenant.
#
# Usage  : ./rapport_matinal.sh
# Cron   : 0 7 * * * /opt/sentinel/rapport_matinal.sh
# =============================================================

set -euo pipefail

ENV_FILE="$(dirname "$0")/.env"
[ -f "$ENV_FILE" ] && { set -a; source "$ENV_FILE"; set +a; }

WAPIWAY_API_KEY="${WAPIWAY_API_KEY:-}"
WAPIWAY_BASE_URL="https://api.wapiway.tech/api/public"
WAPIWAY_PHONE_NUMBERS="${WAPIWAY_PHONE_NUMBERS:-}"
WAPIWAY_SESSION_ID="${WAPIWAY_SESSION_ID:-}"
BUSINESS_HOUR_END="${BUSINESS_HOUR_END:-19}"

# Le journal SQLite est écrit par le bridge dans le volume ./logs/events.db
DB_PATH="$(dirname "$0")/logs/events.db"

if [ -z "$WAPIWAY_API_KEY" ] || [ -z "$WAPIWAY_PHONE_NUMBERS" ]; then
    echo "❌ WAPIWAY_API_KEY ou WAPIWAY_PHONE_NUMBERS manquant"; exit 1
fi
if [ ! -f "$DB_PATH" ]; then
    echo "ℹ️  Aucun journal d'événements ($DB_PATH) — rien à rapporter"; exit 0
fi

# --- Fenêtre : depuis hier 19h jusqu'à maintenant ---
SINCE=$(date -d "yesterday ${BUSINESS_HOUR_END}:00" +%s)
NOW=$(date +%s)
DATE_HUMAIN=$(date '+%d/%m/%Y %H:%M')

# --- Extraction stats via sqlite3 (déléguée à python pour portabilité) ---
STATS=$(python3 - "$DB_PATH" "$SINCE" "$NOW" <<'PY'
import sqlite3, sys, json
db, since, now = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
con = sqlite3.connect(db)
cur = con.cursor()
cur.execute("SELECT COUNT(*) FROM events WHERE ts BETWEEN ? AND ?", (since, now))
total = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM events WHERE ts BETWEEN ? AND ? AND sent=1", (since, now))
envoyees = cur.fetchone()[0]
cur.execute("""SELECT label, COUNT(*) FROM events
               WHERE ts BETWEEN ? AND ? AND sent=1
               GROUP BY label ORDER BY 2 DESC""", (since, now))
par_label = cur.fetchall()
cur.execute("""SELECT camera, COUNT(*) FROM events
               WHERE ts BETWEEN ? AND ? AND sent=1
               GROUP BY camera ORDER BY 2 DESC""", (since, now))
par_cam = cur.fetchall()
cur.execute("""SELECT reason, COUNT(*) FROM events
               WHERE ts BETWEEN ? AND ? AND sent=1
               GROUP BY reason ORDER BY 2 DESC""", (since, now))
par_raison = cur.fetchall()
print(json.dumps({
    "total": total, "envoyees": envoyees,
    "par_label": par_label, "par_cam": par_cam, "par_raison": par_raison
}))
PY
)

TOTAL=$(echo "$STATS" | python3 -c "import sys,json;print(json.load(sys.stdin)['total'])")
ENVOYEES=$(echo "$STATS" | python3 -c "import sys,json;print(json.load(sys.stdin)['envoyees'])")

# --- Si rien ne s'est passé : on n'envoie RIEN (demande PDG) ---
if [ "$TOTAL" -eq 0 ]; then
    echo "✅ Aucun événement entre hier ${BUSINESS_HOUR_END}h et maintenant — pas de rapport envoyé"
    exit 0
fi

# --- Construction du rapport ---
RAPPORT="🌅 *RAPPORT MATINAL — TOLARO GLOBAL*\n"
RAPPORT+="🕐 ${DATE_HUMAIN}\n"
RAPPORT+="━━━━━━━━━━━━━━━━━━━━\n"
RAPPORT+="📊 *Bilan depuis hier ${BUSINESS_HOUR_END}h :*\n"
RAPPORT+="• Détections totales : *${TOTAL}*\n"
RAPPORT+="• Alertes envoyées   : *${ENVOYEES}*\n\n"

DETAILS=$(python3 - <<PY
import json
s = json.loads('''$STATS''')
out = []
if s["par_raison"]:
    out.append("🎯 *Par contexte :*")
    for r, n in s["par_raison"]:
        out.append(f"  • {r} : {n}")
if s["par_label"]:
    out.append("\n🏷️ *Par type :*")
    for l, n in s["par_label"]:
        out.append(f"  • {l} : {n}")
if s["par_cam"]:
    out.append("\n📷 *Par caméra :*")
    for c, n in s["par_cam"]:
        out.append(f"  • {c} : {n}")
print("\n".join(out))
PY
)

RAPPORT+="${DETAILS}\n\n"
RAPPORT+="━━━━━━━━━━━━━━━━━━━━\n"
RAPPORT+="ℹ️ Détail complet dans le dashboard Frigate."

# --- Envoi à chaque destinataire ---
IFS=',' read -ra PHONES <<< "$WAPIWAY_PHONE_NUMBERS"
for RAW in "${PHONES[@]}"; do
    PHONE=$(echo "$RAW" | sed 's/^[[:space:]]*+\?//;s/[[:space:]]*$//')
    [ -z "$PHONE" ] && continue

    BODY=$(python3 -c "
import json, sys
d = {'phone_number': '${PHONE}', 'content': '''$(echo -e "$RAPPORT")'''}
sid = '${WAPIWAY_SESSION_ID}'
if sid: d['session_id'] = sid
print(json.dumps(d))
")

    HTTP=$(curl -s -o /tmp/wapi_resp -w "%{http_code}" -X POST \
        "${WAPIWAY_BASE_URL}/messages/send-text" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${WAPIWAY_API_KEY}" \
        -d "$BODY" --max-time 15)

    if [ "$HTTP" = "200" ] || [ "$HTTP" = "202" ]; then
        echo "✅ Rapport matinal envoyé à ${PHONE}"
    else
        echo "❌ Échec ${PHONE} — HTTP ${HTTP} : $(cat /tmp/wapi_resp)"
    fi
done