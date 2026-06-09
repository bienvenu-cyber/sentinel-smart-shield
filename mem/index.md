# Project Memory

## Core
No Frontend/React. Headless local AI surveillance on Linux mini-PC.
All comments and documentation (README, DEPLOY, etc.) MUST be in French.
Docker services use `restart: always`. Remote maintenance via SSH/Tailscale.
Déploiement projet : toujours `git clone` / `git pull`. Jamais de ZIP GitHub.

## Memories
- [Contexte du Projet](mem://projet/contexte-et-portee) — Système de surveillance IA local sans interface, déployé sur Linux.
- [Stack Technique](mem://technologie/stack-technique) — Docker Compose, Frigate, Mosquitto, Python 3.11, TPU/OpenVINO.
- [Alertes WhatsApp](mem://features/logique-alertes-whatsapp) — Règles métier d'alerte, cooldowns et intégration API WapiWay.
- [Monitoring Système](mem://features/monitoring-systeme) — Script healthcheck.sh et rapports quotidiens WhatsApp.
- [Exposition Publique](mem://technologie/exposition-publique) — Cloudflare Tunnel pour exposer les snapshots Frigate.
- [Caméras V380](mem://materiel/cameras-v380) — Contraintes d'accès flux et bridge Python P2P pour caméras V380.
- [Déploiement git](mem://preferences/deploiement-git) — Toujours git clone / git pull, jamais ZIP GitHub.
- [Dépannage Frigate](mem://depannage/frigate-boucle-restart) — Boucle "Container Restarting" (WiFi/ffmpeg → sous-flux 640×360), conflit git pull sur frigate.yml, image noire & erreurs transitoires normales.
- [Autostart Windows](mem://depannage/autostart-windows-docker) — Déploiement actuel sur Windows Docker Desktop ; activer "Start when you sign in" + restart:always pour relance auto.
