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

# Dossier où on sauvegarde les snapshots avant upload
SNAPSHOT_DIR = "snapshots"
os.makedirs(SNAPSHOT_DIR, exist_ok=True)


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
    message: str = "🚨 Alerte test depuis la webcam Mac",
    frame=None,
) -> bool:
    """
    Envoie une alerte WhatsApp à tous les numéros configurés.
    - Si `frame` (image OpenCV/numpy) est fournie : sauvegarde locale,
      upload public, envoi en image avec légende.
    - Sinon : envoi texte seul.
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

    horodatage = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    contenu = f"{message}\n🕐 {horodatage}"

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
    succes = False
    for phone in WAPIWAY_PHONE_NUMBERS:
        if media_url:
            if _send_media(phone, media_url, contenu):
                succes = True
            else:
                # Fallback texte si l'envoi média échoue
                print(f"   ⚠️ Fallback texte pour {phone}")
                if _send_text(phone, contenu):
                    succes = True
        else:
            if _send_text(phone, contenu):
                succes = True

    if succes:
        _last_alert_ts = now
    return succes


# ----------------------------------------------------------------
# Boucle principale : webcam + détection touche
# ----------------------------------------------------------------
def main():
    print("📷 Ouverture de la webcam...")

    # 0 = webcam par défaut du Mac (FaceTime HD)
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ Impossible d'ouvrir la webcam.")
        print("   → Vérifie : Réglages Système > Confidentialité > Caméra")
        sys.exit(1)

    print("✅ Webcam ouverte.")
    print("   [A] = capturer + envoyer alerte WhatsApp avec photo")
    print("   [Q] = quitter")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("⚠️ Frame vide, on continue...")
            continue

        # On garde une copie BRUTE pour l'envoi (sans l'overlay vert)
        frame_clean = frame.copy()

        # Overlay texte d'aide en bas de la fenêtre (affichage seulement)
        h, w = frame.shape[:2]
        cv2.putText(
            frame,
            "[A] = alerte WhatsApp + photo  |  [Q] = quitter",
            (10, h - 15),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
        )

        cv2.imshow("Demo Webcam → WhatsApp (Mac)", frame)

        # waitKey(1) = 1ms — indispensable pour rafraîchir la fenêtre
        key = cv2.waitKey(1) & 0xFF

        if key == ord("q") or key == ord("Q"):
            print("🛑 Sortie demandée.")
            break

        if key == ord("a") or key == ord("A"):
            print("🔔 Touche A pressée → capture + envoi de l'alerte...")
            send_whatsapp_alert(
                message="🚨 *DETECTION SIMULEE*\n📷 Webcam Mac (demo locale)",
                frame=frame_clean,  # ← frame sans l'overlay vert
            )

    cap.release()
    cv2.destroyAllWindows()
    print("👋 Terminé.")


if __name__ == "__main__":
    main()
