# 🆘 NOTE DE REDÉMARRAGE — Surveillance (à garder près du PC)

> À suivre **dans l'ordre**. Pas besoin de connaissances techniques.

## 1. Le PC est-il allumé ?
- ❌ Éteint → **appuie sur le bouton** pour l'allumer, attends 2 min, puis va à l'étape 2.
- ✅ Allumé → étape 2.

## 2. Ouvrir Docker Desktop
- Cherche l'icône **🐳 Docker Desktop** (barre des tâches en bas à droite, ou menu Démarrer).
- Double-clique dessus. Attends que l'icône devienne **verte / "Running"** (~1 à 2 min).

👉 Dans 90% des cas, ça suffit : tout redémarre tout seul. Va vérifier à l'étape 4.

## 3. Si ça ne repart pas tout seul
Ouvre **PowerShell** (menu Démarrer → tape `powershell`) et colle ces 2 lignes,
une par une, en appuyant sur Entrée :

```powershell
cd "C:\Users\TOLARO GLOBAL\sentinel-smart-shield"
docker compose up -d
```

Attends 1 min.

## 4. Vérifier que tout tourne
Dans PowerShell, colle :

```powershell
docker ps --format "table {{.Names}}\t{{.Status}}"
```

✅ Tu dois voir ces 4 lignes en **Up** :
- `frigate`
- `mosquitto`
- `alertes`
- `cam-watcher`

## 5. Vérifier l'image de la caméra
Ouvre un navigateur (Chrome / Edge) et va sur :

```
http://127.0.0.1:5000
```

Tu dois voir la caméra `rotissage_cam1` avec la date/heure à jour.

---

## ❗ Si ça ne marche toujours pas
1. **Redémarre le PC** complètement (Démarrer → Redémarrer), attends 3 min.
2. Refais les étapes 2 et 4.
3. Toujours bloqué → préviens le responsable technique avec une **photo de l'écran**
   (le résultat de l'étape 4 surtout).

## ⚠️ À NE PAS FAIRE
- ❌ Ne pas éteindre le PC (sauf demande explicite).
- ❌ Ne pas fermer Docker Desktop.
- ❌ Ne rien désinstaller, ne rien supprimer.
- ❌ Ne pas taper d'autres commandes que celles de cette note.