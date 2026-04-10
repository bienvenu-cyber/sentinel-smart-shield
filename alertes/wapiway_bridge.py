#!/usr/bin/env python3
"""
Bridge MQTT Frigate → WhatsApp via WapiWay API
Documentation API : https://api.wapiway.tech
"""

import os
import sys
import json
import time
import logging
import requests
import paho.mqtt.client as mqtt
from datetime import datetime
from dotenv import load_dotenv

# --- Configuration ---
load_dotenv()

WAPIWAY_API_KEY = os.getenv("WAPIWAY_API_KEY", "")
WAPIWAY_BASE_URL = "https://api.wapiway.tech/api/public"
# Numéros sans le "+", séparés par des virgules : "229XXXXXXXX,33612345678"
WAPIWAY_PHONE_NUMBERS = [
    n.strip().lstrip("+")
    for n in os.getenv("WAPIWAY_PHONE_NUMBERS", "").split(",")
    if n.strip()
]
# Session WapiWay (optionnel — si omis, la 1ère session connectée est utilisée)
WAPIWAY_SESSION_ID = os.getenv("WAPIWAY_SESSION_ID", "")

FRIGATE_URL = os.getenv("FRIGATE_URL", "http://frigate:5000")
MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = "frigate/events"

# Filtrage
MIN_SCORE = float(os.getenv("MIN_SCORE", "0.75"))
TRACKED_LABELS = os.getenv("TRACKED_LABELS", "person,car").split(",")
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "60"))

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/app/logs/wapiway_bridge.log", mode="a"),
    ],
)
log = logging.getLogger("wapiway_bridge")

# Anti-spam : dernier envoi par caméra
last_alert: dict[str, float] = {}


# --- WapiWay API ---

def wapiway_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WAPIWAY_API_KEY}",
    }


def send_text(phone_number: str, content: str) -> dict | None:
    """Envoie un message texte via WapiWay POST /messages/send-text"""
    payload = {
        "phone_number": phone_number,
        "content": content[:4096],
    }
    if WAPIWAY_SESSION_ID:
        payload["session_id"] = WAPIWAY_SESSION_ID

    try:
        resp = requests.post(
            f"{WAPIWAY_BASE_URL}/messages/send-text",
            headers=wapiway_headers(),
            json=payload,
            timeout=10,
        )
        if resp.status_code in (200, 202):
            data = resp.json()
            log.info(f"✅ Texte envoyé à {phone_number} — id={data.get('id')}")
            return data
        else:
            log.error(f"❌ Erreur texte {phone_number}: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        log.error(f"❌ Exception texte {phone_number}: {e}")
        return None


def send_media(phone_number: str, media_url: str, caption: str = "", media_type: str = "image") -> dict | None:
    """Envoie un média via WapiWay POST /messages/send-media"""
    payload = {
        "phone_number": phone_number,
        "type": media_type,
        "media_url": media_url,
    }
    if caption:
        payload["caption"] = caption[:4096]
    if WAPIWAY_SESSION_ID:
        payload["session_id"] = WAPIWAY_SESSION_ID

    try:
        resp = requests.post(
            f"{WAPIWAY_BASE_URL}/messages/send-media",
            headers=wapiway_headers(),
            json=payload,
            timeout=15,
        )
        if resp.status_code in (200, 202):
            data = resp.json()
            log.info(f"✅ Média envoyé à {phone_number} — id={data.get('id')}")
            return data
        else:
            log.error(f"❌ Erreur média {phone_number}: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        log.error(f"❌ Exception média {phone_number}: {e}")
        return None


def envoyer_alerte(camera: str, label: str, score: float, event_id: str, zones: list[str]):
    """Envoie une alerte WhatsApp à tous les destinataires configurés."""
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    zone_info = f" (zone: {', '.join(zones)})" if zones else ""

    message = (
        f"🚨 *ALERTE SÉCURITÉ*\n\n"
        f"📷 Caméra : *{camera}*\n"
        f"🏷️ Détection : *{label}* ({score:.0%})\n"
        f"🕐 Heure : {now}\n"
        f"{zone_info}\n\n"
        f"🔗 Live : {FRIGATE_URL}/cameras/{camera}"
    )

    # L'URL du snapshot doit être accessible publiquement pour WapiWay
    # Si Frigate est exposé publiquement, utiliser son URL directement
    # Sinon, il faut un reverse proxy ou un stockage public (S3, etc.)
    snapshot_url = os.getenv("FRIGATE_PUBLIC_URL", FRIGATE_URL)
    media_url = f"{snapshot_url}/api/events/{event_id}/snapshot.jpg"

    for phone in WAPIWAY_PHONE_NUMBERS:
        # Essayer d'envoyer le snapshot en image
        result = send_media(phone, media_url, caption=message)
        if result is None:
            # Fallback : envoyer le texte seul
            log.warning(f"⚠️ Fallback texte pour {phone} (média échoué)")
            send_text(phone, message)


# --- MQTT Callbacks ---

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        log.info(f"✅ Connecté au broker MQTT {MQTT_HOST}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC)
        log.info(f"📡 Abonné à {MQTT_TOPIC}")
    else:
        log.error(f"❌ Connexion MQTT échouée (rc={rc})")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        log.warning("⚠️ Payload MQTT invalide")
        return

    event_type = payload.get("type", "")
    if event_type != "new":
        return

    before = payload.get("before", {})
    after = payload.get("after", {})

    label = after.get("label", "")
    score = after.get("top_score", after.get("score", 0))
    camera = after.get("camera", "unknown")
    event_id = after.get("id", "")
    zones = after.get("current_zones", [])

    # Filtrage
    if label not in TRACKED_LABELS:
        return
    if score < MIN_SCORE:
        return

    # Cooldown anti-spam
    cache_key = f"{camera}_{label}"
    now = time.time()
    if cache_key in last_alert and (now - last_alert[cache_key]) < COOLDOWN_SECONDS:
        log.debug(f"⏳ Cooldown actif pour {cache_key}")
        return
    last_alert[cache_key] = now

    log.info(f"🔔 Alerte : {label} ({score:.0%}) sur {camera}")
    envoyer_alerte(camera, label, score, event_id, zones)


def on_disconnect(client, userdata, rc):
    log.warning(f"⚠️ Déconnecté du broker MQTT (rc={rc}). Reconnexion...")


# --- Main ---

def main():
    if not WAPIWAY_API_KEY:
        log.error("❌ WAPIWAY_API_KEY manquante dans le .env")
        sys.exit(1)
    if not WAPIWAY_PHONE_NUMBERS:
        log.error("❌ WAPIWAY_PHONE_NUMBERS manquant dans le .env")
        sys.exit(1)

    log.info("=" * 50)
    log.info("🚀 WapiWay Bridge démarré")
    log.info(f"   API : {WAPIWAY_BASE_URL}")
    log.info(f"   Destinataires : {len(WAPIWAY_PHONE_NUMBERS)} numéro(s)")
    log.info(f"   Labels suivis : {TRACKED_LABELS}")
    log.info(f"   Score min : {MIN_SCORE}")
    log.info(f"   Cooldown : {COOLDOWN_SECONDS}s")
    log.info("=" * 50)

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    # Reconnexion automatique
    client.reconnect_delay_set(min_delay=1, max_delay=60)

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_forever()
    except KeyboardInterrupt:
        log.info("🛑 Arrêt du bridge")
        client.disconnect()
    except Exception as e:
        log.error(f"❌ Erreur fatale : {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
