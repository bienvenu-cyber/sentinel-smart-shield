"""
cam-watcher : surveille la disponibilité réseau des caméras et
active/désactive automatiquement leur capture dans Frigate via MQTT.

Principe :
- ping ICMP de chaque caméra toutes les CHECK_INTERVAL secondes
- une caméra est considérée ONLINE après UP_THRESHOLD pings OK consécutifs
- elle est considérée OFFLINE après DOWN_THRESHOLD pings KO consécutifs
  (évite les faux positifs en cas de micro-coupure WiFi)
- on publie sur frigate/<cam>/enabled/set la valeur ON ou OFF
  (topic standard Frigate ≥ 0.14)

Configuration via variables d'environnement (cf. docker-compose.yml) :
    MQTT_HOST, MQTT_PORT
    WATCHED_CAMERAS  ex: "rotissage_cam2=192.168.10.206,autre_cam=192.168.10.207"
    CHECK_INTERVAL   (défaut 60 s)
    UP_THRESHOLD     (défaut 2)
    DOWN_THRESHOLD   (défaut 3)
"""
import os
import subprocess
import time
import logging
import paho.mqtt.client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [cam-watcher] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))
UP_THRESHOLD = int(os.getenv("UP_THRESHOLD", "2"))
DOWN_THRESHOLD = int(os.getenv("DOWN_THRESHOLD", "3"))


def parse_cameras() -> dict[str, str]:
    """Parse WATCHED_CAMERAS au format 'cam1=ip1,cam2=ip2'."""
    raw = os.getenv("WATCHED_CAMERAS", "").strip()
    cams: dict[str, str] = {}
    if not raw:
        return cams
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        name, ip = entry.split("=", 1)
        name, ip = name.strip(), ip.strip()
        if name and ip:
            cams[name] = ip
    return cams


def ping(ip: str) -> bool:
    """Retourne True si la caméra répond au ping (1 paquet, timeout 2 s)."""
    try:
        r = subprocess.run(
            ["ping", "-c", "1", "-W", "2", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return r.returncode == 0
    except Exception as e:
        log.warning("Ping %s a échoué : %s", ip, e)
        return False


def main() -> None:
    cams = parse_cameras()
    if not cams:
        log.error("Aucune caméra à surveiller (WATCHED_CAMERAS vide). Arrêt.")
        return

    log.info("Surveillance de %d caméra(s) : %s", len(cams), cams)
    log.info(
        "Intervalle=%ss, seuil ONLINE=%d pings OK, seuil OFFLINE=%d pings KO",
        CHECK_INTERVAL, UP_THRESHOLD, DOWN_THRESHOLD,
    )

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="cam-watcher")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()

    # État de chaque cam : None = inconnu, True = activée (ON), False = désactivée (OFF)
    state: dict[str, bool | None] = {name: None for name in cams}
    up_count: dict[str, int] = {name: 0 for name in cams}
    down_count: dict[str, int] = {name: 0 for name in cams}

    # Au démarrage : on force tout en OFF pour partir d'un état connu
    # (cohérent avec "enabled: False" dans frigate.yml).
    for name in cams:
        client.publish(f"frigate/{name}/enabled/set", "OFF", retain=False)
        log.info("Init : %s → OFF (en attente du premier ping OK)", name)

    while True:
        for name, ip in cams.items():
            alive = ping(ip)
            if alive:
                up_count[name] += 1
                down_count[name] = 0
                if state[name] is not True and up_count[name] >= UP_THRESHOLD:
                    log.info("✅ %s (%s) ONLINE → activation Frigate", name, ip)
                    client.publish(f"frigate/{name}/enabled/set", "ON", retain=False)
                    state[name] = True
            else:
                down_count[name] += 1
                up_count[name] = 0
                if state[name] is not False and down_count[name] >= DOWN_THRESHOLD:
                    log.warning("❌ %s (%s) OFFLINE → désactivation Frigate", name, ip)
                    client.publish(f"frigate/{name}/enabled/set", "OFF", retain=False)
                    state[name] = False

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Arrêt demandé.")