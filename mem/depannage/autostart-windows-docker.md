---
name: Démarrage auto Windows (Docker Desktop)
description: Déploiement actuel sur Windows Docker Desktop — activer le démarrage auto au login pour relancer la stack
type: feature
---
# Démarrage automatique — Windows (Docker Desktop)

> ⚠️ Le déploiement actuel tourne sur **Windows + Docker Desktop**, PAS sur le mini-PC Linux/systemd.
> Donc `install-autostart.sh` / `sentinel.service` ne s'appliquent pas ici.

## Activer le redémarrage auto au boot
1. Docker Desktop → ⚙️ **Settings → General**
2. Cocher **"Start Docker Desktop when you sign in"** → Apply & Restart.
3. Combiné à `restart: always` (déjà dans `docker-compose.yml`), toute la stack
   (frigate, mosquitto, alertes, cam-watcher) redémarre seule après reboot/login.

## Équivalent PowerShell
```powershell
$settings = "$env:APPDATA\Docker\settings-store.json"
if (!(Test-Path $settings)) { $settings = "$env:APPDATA\Docker\settings.json" }
$json = Get-Content $settings -Raw | ConvertFrom-Json
$json.autoStart = $true
$json | ConvertTo-Json -Depth 20 | Set-Content $settings
Restart-Service com.docker.service -ErrorAction SilentlyContinue
```

## Vérifier après reboot
```powershell
docker ps --format "table {{.Names}}\t{{.Status}}"
```
→ frigate / mosquitto / alertes / cam-watcher doivent être **Up**.

> ⚠️ Le PC doit rester allumé (veille désactivée) pour la surveillance 24/7.