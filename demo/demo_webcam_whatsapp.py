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

from ui_console import (
    header, panel, divider, blank, hint,
    ok, fail, warn, info, step, ai, cam, video, send, save,
    Spinner, FG_CYAN, FG_PINK, FG_ORANGE, FG_PURPLE, FG_GREEN, FG_DIM, FG_MUTED, FG_TEXT, RESET, BOLD,
)

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
            with Spinner("Upload image vers catbox.moe…", indent=1):
                resp = requests.post(
                    "https://catbox.moe/user/api.php",
                    data={"reqtype": "fileupload"},
                    files={"fileToUpload": f},
                    headers={"User-Agent": "demo-webcam-whatsapp/1.0"},
                    timeout=30,
                )
        if resp.status_code == 200 and resp.text.startswith("http"):
            url = resp.text.strip()
            send(f"Image hébergée  {FG_DIM}{url}{RESET}", indent=1)
            return url
        warn(f"catbox refusé ({resp.status_code})", indent=1)
    except Exception as e:
        warn(f"catbox exception : {e}", indent=1)

    # --- Essai 2 : tmpfiles.org (fallback, fichiers gardés ~1h) ---
    try:
        with open(filepath, "rb") as f:
            with Spinner("Fallback upload vers tmpfiles.org…", indent=1):
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
                send(f"Image hébergée  {FG_DIM}{direct_url}{RESET}", indent=1)
                return direct_url
        fail(f"tmpfiles refusé ({resp.status_code})", indent=1)
    except Exception as e:
        fail(f"tmpfiles exception : {e}", indent=1)

    fail("Tous les hébergeurs ont échoué — fallback texte", indent=1)
    return None


# ----------------------------------------------------------------
# Upload public d'une vidéo (catbox supporte jusqu'à 200 Mo)
# ----------------------------------------------------------------
def upload_video_public(filepath: str) -> str | None:
    """Upload une vidéo sur catbox.moe et retourne l'URL publique."""
    try:
        size_mo = os.path.getsize(filepath) / (1024 * 1024)
        with open(filepath, "rb") as f:
            with Spinner(f"Upload vidéo ({size_mo:.1f} Mo) → catbox.moe…", color=FG_PINK, indent=1):
                resp = requests.post(
                    "https://catbox.moe/user/api.php",
                    data={"reqtype": "fileupload"},
                    files={"fileToUpload": f},
                    headers={"User-Agent": "demo-webcam-whatsapp/1.0"},
                    timeout=120,
                )
        if resp.status_code == 200 and resp.text.startswith("http"):
            url = resp.text.strip()
            send(f"Vidéo hébergée  {FG_DIM}{url}{RESET}", indent=1)
            return url
        fail(f"catbox refusé ({resp.status_code})", indent=1)
    except Exception as e:
        fail(f"Upload vidéo exception : {e}", indent=1)
    return None


# ----------------------------------------------------------------
# Envoi d'un média (image ou vidéo) via WapiWay
# ----------------------------------------------------------------
def _send_media(phone: str, media_url: str, caption: str, media_type: str = "image") -> bool:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WAPIWAY_API_KEY}",
    }
    payload = {
        "phone_number": phone,
        "type": media_type,
        "media_url": media_url,
        "caption": caption[:4096],
    }
    if WAPIWAY_SESSION_ID:
        payload["session_id"] = WAPIWAY_SESSION_ID
    try:
        with Spinner(f"Envoi {media_type} → +{phone}…", indent=1):
            resp = requests.post(
                f"{WAPIWAY_BASE_URL}/messages/send-media",
                headers=headers, json=payload, timeout=30,
            )
        if resp.status_code in (200, 202):
            ok(f"{media_type.capitalize()} + légende livrés  {FG_DIM}→ +{phone}{RESET}", indent=1)
            return True
        fail(f"WapiWay refusé +{phone} ({resp.status_code})", indent=1)
        return False
    except Exception as e:
        fail(f"WapiWay exception +{phone} : {e}", indent=1)
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
        with Spinner(f"Envoi texte → +{phone}…", indent=1):
            resp = requests.post(
                f"{WAPIWAY_BASE_URL}/messages/send-text",
                headers=headers, json=payload, timeout=10,
            )
        if resp.status_code in (200, 202):
            ok(f"Texte livré  {FG_DIM}→ +{phone}{RESET}", indent=1)
            return True
        fail(f"WapiWay texte refusé +{phone} ({resp.status_code})", indent=1)
        return False
    except Exception as e:
        fail(f"WapiWay texte exception +{phone} : {e}", indent=1)
        return False


# ----------------------------------------------------------------
# Fonction principale : envoi alerte (avec image si fournie)
# ----------------------------------------------------------------
def send_whatsapp_alert(
    message: str | None = None,
    frame=None,
    detection: dict | None = None,
    video_path: str | None = None,
) -> bool:
    """
    Envoie une alerte WhatsApp à tous les numéros configurés.
    - Si `detection` est fournie : génère une légende standard IA.
    - Sinon : utilise `message` (ou un message par défaut).
    - Si `frame` est fournie : sauvegarde + upload + envoi en image WhatsApp.
    - Si `video_path` est fournie : upload + envoi en vidéo WhatsApp.
    Retourne True si au moins un envoi a réussi.
    """
    global _last_alert_ts

    # Vérifs config
    if not WAPIWAY_API_KEY:
        fail("WAPIWAY_API_KEY manquante — créer un .env")
        return False
    if not WAPIWAY_PHONE_NUMBERS:
        fail("WAPIWAY_PHONE_NUMBERS manquant — créer un .env")
        return False

    # Cooldown anti-spam
    now = time.time()
    if (now - _last_alert_ts) < COOLDOWN_SECONDS:
        restant = int(COOLDOWN_SECONDS - (now - _last_alert_ts))
        warn(f"Cooldown actif — réessaye dans {restant}s")
        return False

    # Légende : détection IA simulée OU message libre
    if detection is not None:
        contenu = build_alert_caption(detection)
    else:
        horodatage = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        contenu = f"{message or '🚨 Alerte'}\n🕐 {horodatage}"

    # 1) Préparer le média : vidéo (priorité) OU image
    media_url = None
    media_type = "image"
    if video_path is not None:
        media_type = "video"
        media_url = upload_video_public(video_path)
    elif frame is not None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        snap_path = os.path.join(SNAPSHOT_DIR, f"alerte_{ts}.jpg")
        # Compression JPEG qualité 85 → image légère mais nette
        cv2.imwrite(snap_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        save(f"Snapshot enregistré  {FG_DIM}{snap_path}{RESET}", indent=1)
        media_url = upload_image_public(snap_path)

    # 2) Envoi à chaque destinataire
    # Si on a une URL publique → essai en vraie image WhatsApp (API alignée doc).
    # Si l'envoi média échoue → fallback texte avec le lien dans le contenu.
    succes = False
    for phone in WAPIWAY_PHONE_NUMBERS:
        envoye = False
        if media_url:
            envoye = _send_media(phone, media_url, contenu, media_type=media_type)
        if not envoye:
            emoji_media = "🎥" if media_type == "video" else "📸"
            contenu_fallback = (
                f"{contenu}\n\n{emoji_media} Média : {media_url}" if media_url else contenu
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
    cam(f"Activation webcam silencieuse  {FG_DIM}({WEBCAM_OFF_DELAY}s){RESET}", indent=1)
    cap = None
    with Spinner("Ouverture du flux vidéo…", color=FG_ORANGE, indent=1):
        for tentative in range(5):
            cap = cv2.VideoCapture(0)
            if cap.isOpened():
                break
            cap.release()
            time.sleep(0.5)
    if cap is None or not cap.isOpened():
        fail("Webcam injoignable (occupée par une autre app ?)", indent=1)
        return None
    try:
        frame = None
        valides = 0
        essais = 0
        with Spinner("Warmup capteur…", color=FG_ORANGE, indent=1):
            while valides < WEBCAM_WARMUP_FRAMES and essais < 30:
                ret, f = cap.read()
                essais += 1
                if ret and f is not None:
                    frame = f
                    valides += 1
                else:
                    time.sleep(0.1)
        if frame is None:
            fail(f"Aucune frame valide après {essais} essais", indent=1)
            return None
        with Spinner("Capture en cours…", color=FG_ORANGE, indent=1):
            t_fin = time.time() + WEBCAM_OFF_DELAY
            while time.time() < t_fin:
                ret, f = cap.read()
                if ret and f is not None:
                    frame = f
                time.sleep(0.1)
        return frame
    finally:
        cap.release()
        time.sleep(0.3)
        info("Webcam libérée", indent=1)


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
    ai(
        f"Détection : {BOLD}{detection['label_fr']}{RESET}{FG_TEXT}  "
        f"{FG_GREEN}{int(detection['score']*100)}%{FG_TEXT}  "
        f"{FG_DIM}zone={detection['zone']}{RESET}",
        indent=1,
    )
    frame = capturer_frame_silencieux()
    if frame is None:
        send_whatsapp_alert(detection=detection)  # texte seul si webcam KO
        return
    annoter_frame(frame, detection)
    send_whatsapp_alert(frame=frame, detection=detection)


def enregistrer_video_silencieux(detection: dict) -> str | None:
    """
    Enregistre une courte vidéo (VIDEO_DURATION s) depuis la webcam,
    avec annotations IA en surimpression à chaque frame. Renvoie le chemin
    du fichier .mp4 créé, ou None si échec.
    """
    video(f"Enregistrement vidéo  {FG_DIM}{VIDEO_DURATION}s @ {VIDEO_FPS}fps{RESET}", indent=1)
    cap = None
    with Spinner("Ouverture du flux vidéo…", color=FG_PINK, indent=1):
        for tentative in range(5):
            cap = cv2.VideoCapture(0)
            if cap.isOpened():
                break
            cap.release()
            time.sleep(0.5)
    if cap is None or not cap.isOpened():
        fail("Webcam injoignable (occupée ?)", indent=1)
        return None

    try:
        # Warmup capteur
        with Spinner("Warmup capteur…", color=FG_PINK, indent=1):
            for _ in range(WEBCAM_WARMUP_FRAMES):
                cap.read()

        # Récupération résolution réelle
        ret, frame0 = cap.read()
        if not ret or frame0 is None:
            fail("Aucune frame de démarrage", indent=1)
            return None
        h, w = frame0.shape[:2]

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        video_path = os.path.join(VIDEO_DIR, f"alerte_{ts}.mp4")
        # mp4v = compatible WhatsApp et lisible partout
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(video_path, fourcc, VIDEO_FPS, (w, h))
        if not writer.isOpened():
            fail("Encodeur vidéo indisponible", indent=1)
            return None

        nb_frames_cible = VIDEO_DURATION * VIDEO_FPS
        ecrites = 0
        t_debut = time.time()
        with Spinner(f"REC  0.0 / {VIDEO_DURATION:.1f}s…", color=FG_PINK, indent=1) as sp:
            while ecrites < nb_frames_cible:
                ret, f = cap.read()
                if not ret or f is None:
                    time.sleep(0.02)
                    continue
                annoter_frame(f, detection)
                elapsed = time.time() - t_debut
                cv2.putText(
                    f, f"REC {elapsed:0.1f}s", (f.shape[1] - 130, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2,
                )
                writer.write(f)
                ecrites += 1
                sp.update(f"REC  {elapsed:0.1f} / {VIDEO_DURATION:.1f}s  ·  frame {ecrites}/{nb_frames_cible}")
        writer.release()
        save(f"Vidéo enregistrée  {FG_DIM}{video_path}  ·  {ecrites} frames{RESET}", indent=1)
        return video_path
    finally:
        cap.release()
        time.sleep(0.3)
        info("Webcam libérée", indent=1)


def declencher_alerte_video():
    """Enregistrement vidéo silencieux + analyse IA simulée + envoi WhatsApp."""
    detection = simulate_ai_detection()
    ai(
        f"Détection : {BOLD}{detection['label_fr']}{RESET}{FG_TEXT}  "
        f"{FG_GREEN}{int(detection['score']*100)}%{FG_TEXT}  "
        f"{FG_DIM}zone={detection['zone']}{RESET}",
        indent=1,
    )
    video_path = enregistrer_video_silencieux(detection)
    if video_path is None:
        send_whatsapp_alert(detection=detection)  # texte seul si webcam KO
        return
    send_whatsapp_alert(detection=detection, video_path=video_path)


def main():
    header("SENTINEL  ◆  AI Security Bridge", "Démo locale · webcam → WhatsApp")
    panel([
        ("Caméra",         CAMERA_NAME),
        ("Destinataires",  f"{len(WAPIWAY_PHONE_NUMBERS)} numéro(s)"),
        ("Auto-extinction", f"{WEBCAM_OFF_DELAY}s"),
        ("Vidéo",          f"{VIDEO_DURATION}s @ {VIDEO_FPS}fps"),
        ("Cooldown",       f"{COOLDOWN_SECONDS}s entre alertes"),
    ])
    blank()
    hint(f"[A] alerte photo   ·   [X] alerte vidéo   ·   [Q] quitter")
    divider()

    # Si stdin n'est pas un TTY (ex: lancé via cron) → mode démon, pas d'input
    if not sys.stdin.isatty():
        info("stdin non-TTY → mode démon (Ctrl+C pour arrêter)")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            info("Arrêt.")
        return

    try:
        with _ClavierNonBloquant() as clavier:
            while True:
                touche = clavier.lire_touche(timeout=0.5)
                if touche is None:
                    continue
                if touche.lower() == "q":
                    info("Sortie demandée.")
                    break
                if touche.lower() == "a":
                    blank()
                    step(f"{BOLD}Alerte PHOTO{RESET}{FG_TEXT}  ·  pipeline IA → capture → WhatsApp")
                    declencher_alerte()
                    ok("Prêt pour la prochaine alerte", indent=1)
                    divider()
                if touche.lower() == "x":
                    blank()
                    step(f"{BOLD}Alerte VIDÉO{RESET}{FG_TEXT}  ·  pipeline IA → enregistrement → WhatsApp")
                    declencher_alerte_video()
                    ok("Prêt pour la prochaine alerte", indent=1)
                    divider()
    except KeyboardInterrupt:
        blank()
        info("Interrompu.")
    info("Terminé.")


if __name__ == "__main__":
    main()
