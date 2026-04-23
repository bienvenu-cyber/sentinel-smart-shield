#!/usr/bin/env python3
"""
================================================================
 demo_webcam_whatsapp.py
================================================================
Démo locale : ouvre la webcam du Mac avec OpenCV, affiche le flux,
et envoie une alerte WhatsApp (TEXTE + IMAGE de la webcam) via
l'API WapiWay quand on appuie sur la touche 'A'.
(simule une détection d'IA)

Usage :
    python demo_webcam_whatsapp.py

Touches :
    A  → capture la frame courante + envoie alerte WhatsApp avec photo
    Q  → quitte le programme

Prérequis :
    pip install opencv-python requests python-dotenv

Note sur l'envoi d'image :
    WapiWay attend une URL publique (pas un upload direct).
    On upload donc la frame sur 0x0.st (gratuit, sans compte,
    expire automatiquement après ~30 jours) puis on passe l'URL
    à WapiWay. En production tu pourras remplacer cette étape
    par ton propre stockage public (S3, Cloudflare R2, etc.).
================================================================
"""

import os
import sys
import time
import random
import select
import termios
import tty
from datetime import datetime

import cv2
import requests
from dotenv import load_dotenv

# --- Configuration (lue depuis variables d'env ou .env local) ---
load_dotenv()

WAPIWAY_API_KEY = os.getenv("WAPIWAY_API_KEY", "")
WAPIWAY_BASE_URL = "https://api.wapiway.tech/api/public"
WAPIWAY_PHONE_NUMBERS = [
    n.strip().lstrip("+")
    for n in os.getenv("WAPIWAY_PHONE_NUMBERS", "").split(",")
    if n.strip()
]
WAPIWAY_SESSION_ID = os.getenv("WAPIWAY_SESSION_ID", "")

# Anti-spam : 30s entre deux alertes manuelles
COOLDOWN_SECONDS = 30
_last_alert_ts = 0.0

# Délai d'auto-extinction de la webcam après une alerte (secondes)
WEBCAM_OFF_DELAY = int(os.getenv("WEBCAM_OFF_DELAY", "5"))
# Nombre de frames à "chauffer" avant capture (capteur s'auto-règle)
WEBCAM_WARMUP_FRAMES = int(os.getenv("WEBCAM_WARMUP_FRAMES", "8"))
# Durée d'enregistrement vidéo (secondes) — touche X
VIDEO_DURATION = int(os.getenv("VIDEO_DURATION", "5"))
# FPS cible pour l'enregistrement vidéo
VIDEO_FPS = int(os.getenv("VIDEO_FPS", "20"))

# Dossier où on sauvegarde les snapshots avant upload
SNAPSHOT_DIR = "snapshots"
os.makedirs(SNAPSHOT_DIR, exist_ok=True)
VIDEO_DIR = "videos"
os.makedirs(VIDEO_DIR, exist_ok=True)

# ----------------------------------------------------------------
# Simulation IA — génère une "détection" réaliste
# (en prod, ces valeurs viennent de Frigate / YOLO / OpenVINO)
# ----------------------------------------------------------------
CAMERA_NAME = os.getenv("DEMO_CAMERA_NAME", "CAM-01 Entrée principale")
DETECTION_LABELS = [
    ("person",   "Personne",          ["entrée", "allée", "portail"]),
    ("person",   "Personne",          ["jardin", "terrasse"]),
    ("car",      "Véhicule",          ["allée", "parking"]),
    ("motorcycle","Deux-roues",       ["portail", "rue"]),
]

def simulate_ai_detection() -> dict:
    """Simule une détection IA (label, score, zone, bbox)."""
    label_en, label_fr, zones = random.choice(DETECTION_LABELS)
    return {
        "label_en": label_en,
        "label_fr": label_fr,
        "score": round(random.uniform(0.82, 0.98), 2),
        "zone": random.choice(zones),
        "bbox": [
            random.randint(40, 200),
            random.randint(40, 200),
            random.randint(220, 480),
            random.randint(220, 440),
        ],
        "event_id": f"evt_{int(time.time())}_{random.randint(1000, 9999)}",
    }


def build_alert_caption(detection: dict, camera: str = CAMERA_NAME) -> str:
    """Construit une légende WhatsApp standard exploitable par le responsable sécurité."""
    now = datetime.now()
    date_str = now.strftime("%d/%m/%Y")
    heure_str = now.strftime("%H:%M:%S")
    score_pct = int(detection["score"] * 100)
    x1, y1, x2, y2 = detection["bbox"]

    return (
        f"🚨 *ALERTE SÉCURITÉ — DÉTECTION IA*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📷 Caméra     : *{camera}*\n"
        f"🏷️  Détection  : *{detection['label_fr']}* (`{detection['label_en']}`)\n"
        f"🎯 Confiance  : *{score_pct}%*\n"
        f"📍 Zone       : {detection['zone']}\n"
        f"📐 Position   : [{x1},{y1}]→[{x2},{y2}]\n"
        f"🕐 Horodatage : {date_str} à {heure_str}\n"
        f"🆔 Event ID   : `{detection['event_id']}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ Action recommandée : vérifier le flux live et confirmer."
    )



# ----------------------------------------------------------------
# Upload public d'image — essaie plusieurs services en cascade
# (catbox.moe en priorité, fallback tmpfiles.org).
# Renvoie une URL publique utilisable par WapiWay.
# ----------------------------------------------------------------
def upload_image_public(filepath: str) -> str | None:
    """Upload une image sur un hébergeur public et retourne l'URL."""

    # --- Essai 1 : catbox.moe (gratuit, anonyme, fichiers permanents) ---
    try:
        with open(filepath, "rb") as f:
            resp = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": f},
                headers={"User-Agent": "demo-webcam-whatsapp/1.0"},
                timeout=30,
            )
        if resp.status_code == 200 and resp.text.startswith("http"):
            url = resp.text.strip()
            print(f"   📤 Image uploadée (catbox) : {url}")
            return url
        print(f"   ⚠️ catbox a refusé : {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"   ⚠️ Exception catbox : {e}")

    # --- Essai 2 : tmpfiles.org (fallback, fichiers gardés ~1h) ---
    try:
        with open(filepath, "rb") as f:
            resp = requests.post(
                "https://tmpfiles.org/api/v1/upload",
                files={"file": f},
                timeout=30,
            )
        if resp.status_code == 200:
            data = resp.json()
            raw_url = data.get("data", {}).get("url", "")
            # tmpfiles renvoie une page HTML, on convertit en lien direct image
            if raw_url:
                direct_url = raw_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
                print(f"   📤 Image uploadée (tmpfiles) : {direct_url}")
                return direct_url
        print(f"   ❌ tmpfiles a refusé : {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"   ❌ Exception tmpfiles : {e}")

    print("   ❌ Tous les hébergeurs ont échoué — fallback texte")
    return None


# ----------------------------------------------------------------
# Envoi d'un média (image) via WapiWay
# ----------------------------------------------------------------
def _send_media(phone: str, media_url: str, caption: str) -> bool:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WAPIWAY_API_KEY}",
    }
    payload = {
        "phone_number": phone,
        "type": "image",
        "media_url": media_url,
        "caption": caption[:4096],
    }
    if WAPIWAY_SESSION_ID:
        payload["session_id"] = WAPIWAY_SESSION_ID
    try:
        resp = requests.post(
            f"{WAPIWAY_BASE_URL}/messages/send-media",
            headers=headers, json=payload, timeout=15,
        )
        if resp.status_code in (200, 202):
            print(f"✅ Image+texte envoyés à {phone}")
            return True
        print(f"❌ Erreur média {phone}: {resp.status_code} {resp.text[:200]}")
        return False
    except Exception as e:
        print(f"❌ Exception média {phone}: {e}")
        return False


# ----------------------------------------------------------------
# Envoi d'un message texte simple via WapiWay (fallback)
# ----------------------------------------------------------------
def _send_text(phone: str, content: str) -> bool:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WAPIWAY_API_KEY}",
    }
    payload = {"phone_number": phone, "content": content[:4096]}
    if WAPIWAY_SESSION_ID:
        payload["session_id"] = WAPIWAY_SESSION_ID
    try:
        resp = requests.post(
            f"{WAPIWAY_BASE_URL}/messages/send-text",
            headers=headers, json=payload, timeout=10,
        )
        if resp.status_code in (200, 202):
            print(f"✅ Texte envoyé à {phone}")
            return True
        print(f"❌ Erreur texte {phone}: {resp.status_code} {resp.text[:200]}")
        return False
    except Exception as e:
        print(f"❌ Exception texte {phone}: {e}")
        return False


# ----------------------------------------------------------------
# Fonction principale : envoi alerte (avec image si fournie)
# ----------------------------------------------------------------
def send_whatsapp_alert(
    message: str | None = None,
    frame=None,
    detection: dict | None = None,
) -> bool:
    """
    Envoie une alerte WhatsApp à tous les numéros configurés.
    - Si `detection` est fournie : génère une légende standard IA.
    - Sinon : utilise `message` (ou un message par défaut).
    - Si `frame` est fournie : sauvegarde + upload + envoi en image WhatsApp.
    Retourne True si au moins un envoi a réussi.
    """
    global _last_alert_ts

    # Vérifs config
    if not WAPIWAY_API_KEY:
        print("❌ WAPIWAY_API_KEY manquante (créer un .env)")
        return False
    if not WAPIWAY_PHONE_NUMBERS:
        print("❌ WAPIWAY_PHONE_NUMBERS manquant (créer un .env)")
        return False

    # Cooldown anti-spam
    now = time.time()
    if (now - _last_alert_ts) < COOLDOWN_SECONDS:
        restant = int(COOLDOWN_SECONDS - (now - _last_alert_ts))
        print(f"⏳ Cooldown actif — réessaye dans {restant}s")
        return False

    # Légende : détection IA simulée OU message libre
    if detection is not None:
        contenu = build_alert_caption(detection)
    else:
        horodatage = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        contenu = f"{message or '🚨 Alerte'}\n🕐 {horodatage}"

    # 1) Si on a une frame → sauvegarde + upload public
    media_url = None
    if frame is not None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        snap_path = os.path.join(SNAPSHOT_DIR, f"alerte_{ts}.jpg")
        # Compression JPEG qualité 85 → image légère mais nette
        cv2.imwrite(snap_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        print(f"   💾 Frame sauvegardée : {snap_path}")
        media_url = upload_image_public(snap_path)

    # 2) Envoi à chaque destinataire
    # Si on a une URL publique → essai en vraie image WhatsApp (API alignée doc).
    # Si l'envoi média échoue → fallback texte avec le lien dans le contenu.
    succes = False
    for phone in WAPIWAY_PHONE_NUMBERS:
        envoye = False
        if media_url:
            envoye = _send_media(phone, media_url, contenu)
        if not envoye:
            contenu_fallback = (
                f"{contenu}\n\n📸 Photo : {media_url}" if media_url else contenu
            )
            envoye = _send_text(phone, contenu_fallback)
        if envoye:
            succes = True

    if succes:
        _last_alert_ts = now
    return succes


# ----------------------------------------------------------------
# Boucle principale : webcam + détection touche
# ----------------------------------------------------------------
def annoter_frame(frame, detection: dict):
    """Dessine bbox, label, score et bandeau caméra/horodatage sur la frame."""
    x1, y1, x2, y2 = detection["bbox"]
    fh, fw = frame.shape[:2]
    x1, x2 = min(x1, fw - 1), min(x2, fw - 1)
    y1, y2 = min(y1, fh - 1), min(y2, fh - 1)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
    etiquette = f"{detection['label_en']} {int(detection['score']*100)}%"
    (tw, th), _ = cv2.getTextSize(etiquette, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.rectangle(frame, (x1, max(0, y1 - th - 8)), (x1 + tw + 8, y1), (0, 0, 255), -1)
    cv2.putText(
        frame, etiquette, (x1 + 4, max(th, y1) - 4),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2,
    )
    bandeau = f"{CAMERA_NAME} | {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    cv2.rectangle(frame, (0, 0), (fw, 28), (0, 0, 0), -1)
    cv2.putText(
        frame, bandeau, (8, 20),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1,
    )
    return frame


def capturer_frame_silencieux():
    """
    Allume la webcam en arrière-plan (sans fenêtre), capture une frame
    nette après warmup, puis libère la webcam au bout de WEBCAM_OFF_DELAY.
    Retourne la frame ou None.
    """
    print(f"   📷 Activation webcam (silencieuse, {WEBCAM_OFF_DELAY}s)...")
    # macOS peut mettre 1-2s à relâcher la webcam entre deux ouvertures
    # → on retente plusieurs fois avec un petit délai
    cap = None
    for tentative in range(5):
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            break
        cap.release()
        time.sleep(0.5)
    if cap is None or not cap.isOpened():
        print("   ❌ Impossible d'ouvrir la webcam (occupée par une autre app ?).")
        return None
    try:
        # Warmup tolérant : on lit jusqu'à WEBCAM_WARMUP_FRAMES frames valides,
        # avec max 30 essais (capteur qui se réveille après libération macOS)
        frame = None
        valides = 0
        essais = 0
        while valides < WEBCAM_WARMUP_FRAMES and essais < 30:
            ret, f = cap.read()
            essais += 1
            if ret and f is not None:
                frame = f
                valides += 1
            else:
                time.sleep(0.1)
        if frame is None:
            print(f"   ❌ Aucune frame lue après {essais} essais.")
            return None
        # On garde la webcam active quelques secondes (réalisme + buffer)
        t_fin = time.time() + WEBCAM_OFF_DELAY
        while time.time() < t_fin:
            ret, f = cap.read()
            if ret and f is not None:
                frame = f  # on garde toujours la dernière frame valide
            time.sleep(0.1)
        return frame
    finally:
        cap.release()
        # Petit délai pour laisser macOS libérer le device proprement
        time.sleep(0.3)
        print("   📴 Webcam coupée.")


class _ClavierNonBloquant:
    """Lit les touches du terminal sans bloquer ni afficher (mode raw)."""
    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, *a):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

    def lire_touche(self, timeout=0.5) -> str | None:
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.read(1) if r else None


def declencher_alerte():
    """Capture silencieuse + analyse IA simulée + envoi WhatsApp."""
    detection = simulate_ai_detection()
    print(
        f"   🧠 IA → {detection['label_fr']} "
        f"({int(detection['score']*100)}%) zone={detection['zone']}"
    )
    frame = capturer_frame_silencieux()
    if frame is None:
        send_whatsapp_alert(detection=detection)  # texte seul si webcam KO
        return
    annoter_frame(frame, detection)
    send_whatsapp_alert(frame=frame, detection=detection)


def main():
    print("=" * 56)
    print("🛡️  SENTINEL — Démo locale (mode silencieux)")
    print("=" * 56)
    print(f"   📷 Caméra simulée : {CAMERA_NAME}")
    print(f"   📞 Destinataires  : {len(WAPIWAY_PHONE_NUMBERS)} numéro(s)")
    print(f"   ⏱️  Auto-extinction webcam : {WEBCAM_OFF_DELAY}s")
    print("-" * 56)
    print("   [A] = déclencher une alerte (capture + WhatsApp)")
    print("   [Q] = quitter")
    print("=" * 56)

    # Si stdin n'est pas un TTY (ex: lancé via cron) → mode démon, pas d'input
    if not sys.stdin.isatty():
        print("ℹ️ stdin non-TTY → mode démon (Ctrl+C pour arrêter)")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            print("👋 Arrêt.")
        return

    try:
        with _ClavierNonBloquant() as clavier:
            while True:
                touche = clavier.lire_touche(timeout=0.5)
                if touche is None:
                    continue
                if touche.lower() == "q":
                    print("🛑 Sortie demandée.")
                    break
                if touche.lower() == "a":
                    print("🔔 Alerte déclenchée → analyse IA + capture...")
                    declencher_alerte()
                    print("   ✅ Prêt pour la prochaine alerte ([A] / [Q])\n")
    except KeyboardInterrupt:
        print("\n🛑 Interrompu.")
    print("👋 Terminé.")


if __name__ == "__main__":
    main()
