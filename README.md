# 🔒 Système de Vidéosurveillance Intelligent

Surveillance en temps réel avec détection d'objets (IA) et alertes WhatsApp automatiques.

## 🏗️ Architecture

```
Caméras IP (RTSP)
     │
     ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│   Frigate   │────▶│  Mosquitto   │────▶│  WapiWay Bridge │
│   (NVR+IA)  │     │   (MQTT)     │     │  (Python)       │
└──────┬──────┘     └──────────────┘     └────────┬────────┘
       │                                          │
       ▼                                          ▼
┌──────────────┐                        ┌─────────────────┐
│  Cloudflare  │                        │   WapiWay API   │
│   Tunnel     │───── URL publique ────▶│   (WhatsApp)    │
└──────────────┘                        └─────────────────┘
```

## 📦 Services

| Service | Description | Port |
|---------|-------------|------|
| **Frigate** | NVR avec détection IA | 5000 |
| **Mosquitto** | Broker MQTT | 1883 |
| **Alertes** | Bridge MQTT → WhatsApp (WapiWay) | — |
| **Cloudflared** | Tunnel sécurisé vers Frigate | — |

## 🚀 Installation rapide

### Prérequis
- Ubuntu/Debian avec Docker et Docker Compose
- Caméras IP avec flux RTSP
- Compte [WapiWay](https://wapiway.tech) avec clé API
- Compte [Cloudflare](https://dash.cloudflare.com) gratuit + un domaine

### 1. Cloner et configurer

```bash
git clone <repo-url> surveillance
cd surveillance
cp .env.example .env
nano .env
```

### 2. Configurer le tunnel Cloudflare

```bash
chmod +x setup-tunnel.sh
./setup-tunnel.sh
```

### 3. Démarrer

```bash
docker compose up -d
```

### 4. Vérifier

```bash
docker compose ps
chmod +x healthcheck.sh
./healthcheck.sh
```

## 📁 Structure

```
├── docker-compose.yml
├── .env.example
├── config/
│   ├── frigate.yml
│   └── mosquitto.conf
├── alertes/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── wapiway_bridge.py
├── healthcheck.sh
├── setup-tunnel.sh
└── DEPLOY.md
```

## ⚙️ Variables d'environnement

| Variable | Description |
|----------|-------------|
| `WAPIWAY_API_KEY` | Clé API WapiWay (`sk_live_...`) |
| `WAPIWAY_PHONE_NUMBERS` | Numéros sans `+`, séparés par `,` |
| `CLOUDFLARE_TUNNEL_TOKEN` | Token du tunnel Cloudflare |
| `FRIGATE_PUBLIC_URL` | URL publique Frigate via le tunnel |
| `MIN_SCORE` | Score minimum de détection (0.75) |
| `COOLDOWN_SECONDS` | Anti-spam par caméra (60s) |

## 📖 Déploiement détaillé

Voir [DEPLOY.md](DEPLOY.md)
