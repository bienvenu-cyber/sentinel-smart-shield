# 📋 Guide de Déploiement Complet

## Étape 1 — Préparer le serveur

```bash
# Ubuntu/Debian
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose-plugin curl git
sudo systemctl enable docker
sudo usermod -aG docker $USER
# Se reconnecter pour appliquer le groupe docker
```

## Étape 2 — Récupérer le projet

```bash
git clone <repo-url> ~/surveillance
cd ~/surveillance
cp .env.example .env
```

## Étape 3 — Configurer le .env

```bash
nano .env
```

Remplir :
- `FRIGATE_RTSP_USER` / `FRIGATE_RTSP_PASSWORD` : identifiants de vos caméras
- `WAPIWAY_API_KEY` : votre clé API WapiWay (depuis https://app.wapiway.tech)
- `WAPIWAY_PHONE_NUMBERS` : numéros WhatsApp sans `+`, séparés par `,`

## Étape 4 — Configurer Cloudflare Tunnel

### Via le dashboard (recommandé)

1. Aller sur https://one.dash.cloudflare.com
2. **Networks → Tunnels → Create a tunnel**
3. Choisir **Cloudflared**
4. Nommer le tunnel : `frigate-surveillance`
5. Copier le **token** (commence par `eyJ...`)
6. Configurer la **route publique** :
   - Subdomain : `frigate`
   - Domain : `votredomaine.com`
   - Service : `http://frigate:5000`
7. Coller le token dans `.env` :
   ```
   CLOUDFLARE_TUNNEL_TOKEN=eyJ...
   FRIGATE_PUBLIC_URL=https://frigate.votredomaine.com
   ```

### Via le script

```bash
chmod +x setup-tunnel.sh
./setup-tunnel.sh
```

## Étape 5 — Adapter les caméras

Éditer `config/frigate.yml` :
- Modifier les adresses IP des caméras (`192.168.1.10`, `.11`, `.12`)
- Ajuster la résolution si nécessaire
- Adapter les zones de détection

Pour trouver vos caméras sur le réseau :
```bash
nmap -sP 192.168.1.0/24
```

## Étape 6 — Lancer le système

```bash
docker compose up -d
```

Vérifier que tout tourne :
```bash
docker compose ps
docker compose logs -f alertes
```

Accéder à l'interface Frigate : http://IP_SERVEUR:5000

## Étape 7 — Tester les alertes

Passez devant une caméra. Vous devriez recevoir un message WhatsApp avec :
- Le nom de la caméra
- Le type de détection (personne/voiture)
- Le score de confiance
- Un snapshot de l'événement

## Étape 8 — Healthcheck quotidien

```bash
chmod +x healthcheck.sh
./healthcheck.sh   # Test immédiat

# Automatiser à 8h chaque matin
(crontab -l 2>/dev/null; echo "0 8 * * * $(pwd)/healthcheck.sh >> /var/log/healthcheck.log 2>&1") | crontab -
```

## 🔧 Dépannage

| Problème | Solution |
|----------|----------|
| Frigate ne démarre pas | Vérifier les URLs RTSP : `ffprobe rtsp://user:pass@IP/stream` |
| Pas d'alertes WhatsApp | Vérifier `docker compose logs alertes` — clé API WapiWay valide ? |
| Snapshot non reçu | Vérifier que `FRIGATE_PUBLIC_URL` est accessible depuis internet |
| Tunnel déconnecté | Vérifier `docker compose logs cloudflared` — token valide ? |
| Trop d'alertes | Augmenter `MIN_SCORE` ou `COOLDOWN_SECONDS` dans `.env` |

## 🔄 Mise à jour

```bash
cd ~/surveillance
git pull
docker compose pull
docker compose up -d --build
```
