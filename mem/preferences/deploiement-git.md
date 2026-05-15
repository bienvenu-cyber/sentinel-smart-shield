---
name: Déploiement via git uniquement
description: Toujours utiliser git clone / git pull pour récupérer ou mettre à jour le projet sur la machine de prod. Ne jamais proposer le téléchargement ZIP GitHub.
type: preference
---
Git est installé sur la machine Windows de prod (MAGASIN-TG).
Toujours proposer `git clone` (initial) puis `git pull` (mises à jour).
**Ne jamais** suggérer "Download ZIP" depuis GitHub, même en fallback.
**Why:** L'utilisateur a explicitement demandé de ne plus jamais proposer le ZIP.
