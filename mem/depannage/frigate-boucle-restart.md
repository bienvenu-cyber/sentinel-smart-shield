---
name: Dépannage boucle "Container frigate Restarting" + conflit git pull
description: Frigate crash en boucle (ffmpeg/WiFi faible) et conflit git pull sur config/frigate.yml — symptômes et solutions
type: feature
---
# Dépannage Frigate — boucle restart & conflit git pull

## Symptôme 1 : "Container frigate Restarting" en boucle (plusieurs minutes)
- **Cause** : config caméra trop lourde pour le WiFi faible (flux principal 1080p `Channels/101`) → ffmpeg crash / "corrupt decoded frame" / segments jetés → Frigate redémarre sans cesse.
- **Solution appliquée** : basculer **TOUT sur le sous-flux basse résolution 640×360** (EZVIZ canal `102`, variable `*_PATH_SUB`) avec les rôles `[detect, record]` dans `config/frigate.yml`.
- Le bloc 1080p (deux entrées séparées detect/record) reste commenté, prêt à réactiver une fois le WiFi renforcé.
- Aussi : retirer le suivi `truck` (non pertinent, source de bruit). `objects.track` = person, car, motorcycle uniquement.

## Symptôme 2 : `git pull` refuse de merger
- Message : `error: Your local changes to the following files would be overwritten by merge: config/frigate.yml ... Aborting`
- **Solution** : `git stash` → `git pull` → NE PAS faire `git stash pop` (cela réintroduirait l'ancienne config supprimée, ex: suivi `truck`).
- Warning LF/CRLF sous Windows = bénin.

## Symptôme 3 : "Caméra inaccessible / image non disponible" ou image noire
- **Pas un bug** : c'est la basse résolution (640×360) + scène sombre (pas d'IR). Le flux marche.
- Vérif OK si logs montrent `GET /api/rotissage_cam1/latest.webp ... 200` et live `/live/jsmpeg/... 101`.
- Snapshot pleine déf pour vérifier la scène : `http://127.0.0.1:5000/api/rotissage_cam1/latest.jpg?h=720`

## Erreurs transitoires NORMALES (ne pas s'inquiéter)
- `connect() failed ... 5001/auth` au démarrage → service auth démarre après nginx, disparaît en quelques secondes.
- `400 0` répétés → sondes healthcheck Docker, pas des erreurs.
- `Did not detect hwaccel` / `CPU detectors are not recommended` → avertissements CPU, fonctionne quand même (TPU Coral idéal plus tard).

## Commandes utiles
```powershell
docker ps --format "table {{.Names}}\t{{.Status}}"     # doit montrer "Up X (healthy)"
docker logs frigate --tail 120
docker compose stop frigate ; docker compose up -d frigate
docker logs frigate --tail 40 | findstr /i "ffmpeg crash error rotissage"
```
