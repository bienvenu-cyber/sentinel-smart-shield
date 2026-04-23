#!/usr/bin/env python3
"""
================================================================
 wapiway_bridge.py — Bridge MQTT Frigate → WhatsApp (WapiWay)
================================================================
Écoute les événements `frigate/events`, télécharge le snapshot
(et optionnellement le clip vidéo) depuis Frigate, l'upload sur
un hébergeur public (catbox.moe, fallback tmpfiles.org), puis
envoie une alerte WhatsApp riche (image/vidéo + caption standard)
via l'API WapiWay à tous les destinataires configurés.

Aligné sur la logique validée en démo (`demo/demo_webcam_whatsapp.py`) :
    - Caption standardisée (caméra, label FR, score, zone, horodatage)
    - Upload public en cascade (catbox → tmpfiles)
    - Envoi WapiWay /messages/send-media (image OU vidéo)
    - Fallback texte si l'envoi média échoue
    - Cooldown anti-spam par caméra+label

Documentation API : https://api.wapiway.tech
================================================================
"""

import os
import sys
import json
import time
import logging
import tempfile
import requests
import paho.mqtt.client as mqtt
from datetime import datetime
from dotenv import load_dotenv

# ----------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------
load_dotenv()

WAPIWAY_API_KEY = os.getenv("WAPIWAY_API_KEY", "")
WAPIWAY_BASE_URL = "https://api.wapiway.tech/api/public"
WAPIWAY_PHONE_NUMBERS = [
    n.strip().lstrip("+")
    for n in os.getenv("WAPIWAY_PHONE_NUMBERS", "").split(",")
    if n.strip()
]
WAPIWAY_SESSION_ID = os.getenv("WAPIWAY_SESSION_ID", "")

FRIGATE_URL = os.getenv("FRIGATE_URL", "http://frigate:5000")
# URL publique (Cloudflare Tunnel) — sert juste pour le lien "Live"
# dans la caption. Le téléchargement réel se fait via FRIGATE_URL (interne).
FRIGATE_PUBLIC_URL = os.getenv("FRIGATE_PUBLIC_URL", FRIGATE_URL)

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = "frigate/events"

# Filtrage
MIN_SCORE = float(os.getenv("MIN_SCORE", "0.75"))
TRACKED_LABELS = [l.strip() for l in os.getenv("TRACKED_LABELS", "person,car").split(",") if l.strip()]
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "60"))

# Média
# image | video | both
ALERT_MEDIA_TYPE = os.getenv("ALERT_MEDIA_TYPE", "image").lower()
VIDEO_WAIT_SECONDS = int(os.getenv("VIDEO_WAIT_SECONDS", "15"))

# Traduction labels EN → FR (pour caption lisible par le responsable sécu)
LABEL_FR = {
    "person": "Personne",
    "car": "Véhicule",
    "motorcycle": "Deux-roues",
    "bicycle": "Vélo",
    "truck": "Camion",
    "bus": "Bus",
    "dog": "Chien",
    "cat": "Chat",
    "package": "Colis",
}

# Nom lisible des caméras (clé = nom Frigate, valeur = libellé humain)
CAMERA_DISPLAY = {
    "entree": "CAM-01 Entrée principale",
    "entrepot": "CAM-02 Entrepôt",
    "parking": "CAM-03 Parking",
    "nouvelle": "CAM-04 Nouvelle caméra",
}

# ----------------------------------------------------------------
# Logging
# ----------------------------------------------------------------
os.makedirs("/app/logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/app/logs/wapiway_bridge.log", mode="a"),
    ],
)
log = logging.getLogger("wapiway_bridge")

# Anti-spam : dernier envoi par (caméra, label)
last_alert: dict[str, float] = {}


# ================================================================
# 1) Caption standardisée (alignée sur la démo)
# ================================================================
def build_alert_caption(
    camera: str,
    label_en: str,
    score: float,
    zones: list[str],
    event_id: str,
    bbox: list[int] | None = None,
) -> str:
    """Construit une légende WhatsApp exploitable par le responsable sécurité."""
    now = datetime.now()
    date_str = now.strftime("%d/%m/%Y")
    heure_str = now.strftime("%H:%M:%S")
    score_pct = int(round(score * 100))
    label_fr = LABEL_FR.get(label_en, label_en.capitalize())
    cam_display = CAMERA_DISPLAY.get(camera, camera)
    zone_str = ", ".join(zones) if zones else "—"
    bbox_str = (
        f"[{bbox[0]},{bbox[1]}]→[{bbox[2]},{bbox[3]}]"
        if bbox and len(bbox) >= 4 else "—"
    )
    live_url = f"{FRIGATE_PUBLIC_URL}/cameras/{camera}"

    return (
        f"🚨 *ALERTE SÉCURITÉ — DÉTECTION IA*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📷 Caméra     : *{cam_display}*\n"
        f"🏷️  Détection  : *{label_fr}* (`{label_en}`)\n"
        f"🎯 Confiance  : *{score_pct}%*\n"
        f"📍 Zone       : {zone_str}\n"
        f"📐 Position   : {bbox_str}\n"
        f"🕐 Horodatage : {date_str} à {heure_str}\n"
        f"🆔 Event ID   : `{event_id}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 Live : {live_url}\n"
        f"⚠️ Action recommandée : vérifier le flux live et confirmer."
    )


# ================================================================
# 2) Téléchargement du média depuis Frigate (interne) → fichier local
# ================================================================
def download_snapshot(event_id: str) -> str | None:
    """Télécharge le snapshot JPEG d'un événement Frigate."""
    url = f"{FRIGATE_URL}/api/events/{event_id}/snapshot.jpg?bbox=1&timestamp=1"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200 or not resp.content:
            log.error(f"❌ Snapshot indisponible ({resp.status_code}) pour {event_id}")
            return None
        fd, path = tempfile.mkstemp(suffix=".jpg", prefix=f"frig_{event_id}_")
        with os.fdopen(fd, "wb") as f:
            f.write(resp.content)
        log.info(f"   💾 Snapshot téléchargé : {path} ({len(resp.content)//1024} Ko)")
        return path
    except Exception as e:
        log.error(f"❌ Exception snapshot {event_id}: {e}")
        return None


def download_clip(event_id: str) -> str | None:
    """Télécharge le clip MP4 d'un événement Frigate (après finalisation)."""
    url = f"{FRIGATE_URL}/api/events/{event_id}/clip.mp4"
    try:
        # On laisse Frigate finaliser le clip
        log.info(f"   ⏳ Attente clip {event_id} ({VIDEO_WAIT_SECONDS}s)...")
        time.sleep(VIDEO_WAIT_SECONDS)
        resp = requests.get(url, timeout=60, stream=True)
        if resp.status_code != 200:
            log.error(f"❌ Clip indisponible ({resp.status_code}) pour {event_id}")
            return None
        fd, path = tempfile.mkstemp(suffix=".mp4", prefix=f"frig_{event_id}_")
        size = 0
        with os.fdopen(fd, "wb") as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
                    size += len(chunk)
        log.info(f"   💾 Clip téléchargé : {path} ({size//1024} Ko)")
        return path
    except Exception as e:
        log.error(f"❌ Exception clip {event_id}: {e}")
        return None


# ================================================================
# 3) Upload public (cascade catbox → tmpfiles) — repris de la démo
# ================================================================
def upload_public(filepath: str, kind: str = "image") -> str | None:
    """Upload un fichier sur catbox.moe (fallback tmpfiles.org). Renvoie l'URL publique."""
    timeout = 120 if kind == "video" else 30

    # --- Essai 1 : catbox.moe (permanent, jusqu'à 200 Mo) ---
    try:
        with open(filepath, "rb") as f:
            resp = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": f},
                headers={"User-Agent": "sentinel-wapiway-bridge/1.0"},
                timeout=timeout,
            )
        if resp.status_code == 200 and resp.text.startswith("http"):
            url = resp.text.strip()
            log.info(f"   📤 Upload catbox OK : {url}")
            return url
        log.warning(f"   ⚠️ catbox refusé : {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        log.warning(f"   ⚠️ Exception catbox : {e}")

    # --- Essai 2 : tmpfiles.org (~1h, surtout pour images) ---
    if kind == "image":
        try:
            with open(filepath, "rb") as f:
                resp = requests.post(
                    "https://tmpfiles.org/api/v1/upload",
                    files={"file": f},
                    timeout=timeout,
                )
            if resp.status_code == 200:
                data = resp.json()
                raw_url = data.get("data", {}).get("url", "")
                if raw_url:
                    direct_url = raw_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
                    log.info(f"   📤 Upload tmpfiles OK : {direct_url}")
                    return direct_url
            log.error(f"   ❌ tmpfiles refusé : {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            log.error(f"   ❌ Exception tmpfiles : {e}")

    log.error("   ❌ Tous les hébergeurs ont échoué")
    return None


# ================================================================
# 4) Envoi WapiWay : média + texte fallback (repris de la démo)
# ================================================================
def _wapiway_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WAPIWAY_API_KEY}",
    }


def send_media(phone: str, media_url: str, caption: str, media_type: str = "image") -> bool:
    """POST /messages/send-media (type=image|video, media_url=URL publique)."""
    payload = {
        "phone_number": phone,
        "type": media_type,
        "media_url": media_url,
        "caption": caption[:4096],
    }
    if WAPIWAY_SESSION_ID:
        payload["session_id"] = WAPIWAY_SESSION_ID
    try:
        resp = requests.post(
            f"{WAPIWAY_BASE_URL}/messages/send-media",
            headers=_wapiway_headers(),
            json=payload,
            timeout=30,
        )
        if resp.status_code in (200, 202):
            log.info(f"✅ {media_type.capitalize()} envoyé à {phone}")
            return True
        log.error(f"❌ Erreur média {phone}: {resp.status_code} {resp.text[:200]}")
        return False
    except Exception as e:
        log.error(f"❌ Exception média {phone}: {e}")
        return False


def send_text(phone: str, content: str) -> bool:
    """POST /messages/send-text (fallback)."""
    payload = {"phone_number": phone, "content": content[:4096]}
    if WAPIWAY_SESSION_ID:
        payload["session_id"] = WAPIWAY_SESSION_ID
    try:
        resp = requests.post(
            f"{WAPIWAY_BASE_URL}/messages/send-text",
            headers=_wapiway_headers(),
            json=payload,
            timeout=10,
        )
        if resp.status_code in (200, 202):
            log.info(f"✅ Texte envoyé à {phone}")
            return True
        log.error(f"❌ Erreur texte {phone}: {resp.status_code} {resp.text[:200]}")
        return False
    except Exception as e:
        log.error(f"❌ Exception texte {phone}: {e}")
        return False


# ================================================================
# 5) Orchestration : envoie une alerte complète
# ================================================================
def envoyer_alerte(
    camera: str,
    label: str,
    score: float,
    event_id: str,
    zones: list[str],
    bbox: list[int] | None = None,
):
    """Télécharge le média Frigate, l'upload, puis envoie via WapiWay à tous les destinataires."""
    caption = build_alert_caption(camera, label, score, zones, event_id, bbox)

    # --- Étape 1 : préparer les médias selon ALERT_MEDIA_TYPE ---
    medias: list[tuple[str, str]] = []  # liste de (media_url, media_type)

    if ALERT_MEDIA_TYPE in ("image", "both"):
        snap_path = download_snapshot(event_id)
        if snap_path:
            url = upload_public(snap_path, kind="image")
            try:
                os.unlink(snap_path)
            except OSError:
                pass
            if url:
                medias.append((url, "image"))

    if ALERT_MEDIA_TYPE in ("video", "both"):
        clip_path = download_clip(event_id)
        if clip_path:
            url = upload_public(clip_path, kind="video")
            try:
                os.unlink(clip_path)
            except OSError:
                pass
            if url:
                medias.append((url, "video"))

    # --- Étape 2 : envoi à chaque destinataire ---
    for phone in WAPIWAY_PHONE_NUMBERS:
        envoye_au_moins_un_media = False
        for idx, (media_url, media_type) in enumerate(medias):
            # Caption seulement sur le 1er média pour ne pas spammer
            cap = caption if idx == 0 else ""
            if send_media(phone, media_url, cap, media_type=media_type):
                envoye_au_moins_un_media = True

        # Fallback texte si AUCUN média n'a pu être envoyé
        if not envoye_au_moins_un_media:
            log.warning(f"⚠️ Fallback texte pour {phone}")
            fallback = caption
            if medias:
                fallback += "\n\n📎 Média : " + medias[0][0]
            send_text(phone, fallback)


# ================================================================
# 6) MQTT — écoute des événements Frigate
# ================================================================
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
    # On déclenche sur 'new' (début de détection). 'end' permettrait d'avoir
    # le clip directement dispo, mais retarderait l'alerte de plusieurs s.
    if event_type != "new":
        return

    after = payload.get("after", {})
    label = after.get("label", "")
    score = after.get("top_score", after.get("score", 0))
    camera = after.get("camera", "unknown")
    event_id = after.get("id", "")
    zones = after.get("current_zones", []) or []
    bbox = after.get("box") or after.get("region")  # [x,y,w,h] en général

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

    log.info(f"🔔 Alerte : {label} ({score:.0%}) sur {camera} (event {event_id})")
    try:
        envoyer_alerte(camera, label, score, event_id, zones, bbox)
    except Exception as e:
        log.exception(f"❌ Erreur traitement alerte {event_id}: {e}")


def on_disconnect(client, userdata, rc):
    log.warning(f"⚠️ Déconnecté du broker MQTT (rc={rc}). Reconnexion auto...")


# ================================================================
# 7) Main
# ================================================================
def main():
    if not WAPIWAY_API_KEY:
        log.error("❌ WAPIWAY_API_KEY manquante dans le .env")
        sys.exit(1)
    if not WAPIWAY_PHONE_NUMBERS:
        log.error("❌ WAPIWAY_PHONE_NUMBERS manquant dans le .env")
        sys.exit(1)
    if ALERT_MEDIA_TYPE not in ("image", "video", "both"):
        log.error(f"❌ ALERT_MEDIA_TYPE invalide : {ALERT_MEDIA_TYPE} (image|video|both)")
        sys.exit(1)

    log.info("=" * 60)
    log.info("🚀 SENTINEL — WapiWay Bridge démarré")
    log.info(f"   API WapiWay      : {WAPIWAY_BASE_URL}")
    log.info(f"   Frigate (interne): {FRIGATE_URL}")
    log.info(f"   Frigate (public) : {FRIGATE_PUBLIC_URL}")
    log.info(f"   MQTT             : {MQTT_HOST}:{MQTT_PORT}")
    log.info(f"   Destinataires    : {len(WAPIWAY_PHONE_NUMBERS)} numéro(s)")
    log.info(f"   Labels suivis    : {TRACKED_LABELS}")
    log.info(f"   Score min        : {MIN_SCORE}")
    log.info(f"   Cooldown         : {COOLDOWN_SECONDS}s")
    log.info(f"   Type d'alerte    : {ALERT_MEDIA_TYPE.upper()}")
    if ALERT_MEDIA_TYPE in ("video", "both"):
        log.info(f"   Attente clip     : {VIDEO_WAIT_SECONDS}s")
    log.info("=" * 60)

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
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