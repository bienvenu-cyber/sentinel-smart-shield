#!/usr/bin/env python3
"""
================================================================
 demo_webcam_whatsapp.py
================================================================
Démo locale : ouvre la webcam du Mac avec OpenCV, affiche le flux,
et envoie une alerte WhatsApp via l'API WapiWay quand on appuie
sur la touche 'A' (simule une détection d'IA).

Usage :
    python demo_webcam_whatsapp.py

Touches :
    A  → envoie une alerte WhatsApp
    Q  → quitte le programme

Prérequis :
    pip install opencv-python requests python-dotenv
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


# ----------------------------------------------------------------
# Fonction d'envoi WhatsApp via WapiWay
# ----------------------------------------------------------------
def send_whatsapp_alert(message: str = "🚨 Alerte test depuis la webcam Mac") -> bool:
    """
    Envoie une alerte WhatsApp à tous les numéros configurés.
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

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WAPIWAY_API_KEY}",
    }

    horodatage = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    contenu = f"{message}\n🕐 {horodatage}"

    succes = False
    for phone in WAPIWAY_PHONE_NUMBERS:
        payload = {"phone_number": phone, "content": contenu[:4096]}
        if WAPIWAY_SESSION_ID:
            payload["session_id"] = WAPIWAY_SESSION_ID

        try:
            resp = requests.post(
                f"{WAPIWAY_BASE_URL}/messages/send-text",
                headers=headers,
                json=payload,
                timeout=10,
            )
            if resp.status_code in (200, 202):
                print(f"✅ Alerte envoyée à {phone}")
                succes = True
            else:
                print(f"❌ Erreur {phone}: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"❌ Exception {phone}: {e}")

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
    print("   [A] = envoyer alerte WhatsApp")
    print("   [Q] = quitter")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("⚠️ Frame vide, on continue...")
            continue

        # Overlay texte d'aide en bas de la fenêtre
        h, w = frame.shape[:2]
        cv2.putText(
            frame,
            "Appuyer sur [A] = alerte WhatsApp | [Q] = quitter",
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
            print("🔔 Touche A pressée → envoi de l'alerte...")
            send_whatsapp_alert(
                "🚨 *DETECTION SIMULEE*\n📷 Webcam Mac (demo locale)"
            )

    cap.release()
    cv2.destroyAllWindows()
    print("👋 Terminé.")


if __name__ == "__main__":
    main()
