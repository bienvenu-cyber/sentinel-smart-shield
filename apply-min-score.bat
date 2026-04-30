@echo off
REM =============================================================
REM apply-min-score.bat — Met a jour MIN_SCORE dans .env et
REM recree le conteneur alertes pour recharger les variables d'environnement.
REM
REM Usage  : apply-min-score.bat            (defaut : 0.70)
REM         apply-min-score.bat 0.65        (valeur personnalisee)
REM =============================================================

setlocal EnableDelayedExpansion

set "NEW_SCORE=%~1"
if "%NEW_SCORE%"=="" set "NEW_SCORE=0.70"

set "ENV_FILE=%~dp0.env"
if not exist "%ENV_FILE%" (
    echo [ERREUR] Fichier .env introuvable : %ENV_FILE%
    exit /b 1
)

echo.
echo ============================================================
echo  Mise a jour MIN_SCORE -^> %NEW_SCORE%
echo ============================================================

REM --- Sauvegarde du .env avant modification ---
copy /Y "%ENV_FILE%" "%ENV_FILE%.bak" >nul
echo [OK] Sauvegarde : %ENV_FILE%.bak

REM --- Remplacement de la ligne MIN_SCORE via PowerShell (regex) ---
powershell -NoProfile -Command ^
  "$path='%ENV_FILE%';" ^
  "$content = Get-Content $path -Raw;" ^
  "if ($content -match '(?m)^MIN_SCORE\s*=.*$') {" ^
  "  $new = $content -replace '(?m)^MIN_SCORE\s*=.*$', 'MIN_SCORE=%NEW_SCORE%';" ^
  "} else {" ^
  "  $new = $content.TrimEnd() + \"`r`nMIN_SCORE=%NEW_SCORE%`r`n\";" ^
  "}" ^
  "Set-Content -Path $path -Value $new -NoNewline;" ^
  "Write-Host '[OK] MIN_SCORE mis a jour dans .env'"

if errorlevel 1 (
    echo [ERREUR] Echec mise a jour .env
    exit /b 1
)

REM --- Re-creation du conteneur alertes ---
echo.
echo Re-creation du conteneur alertes pour recharger .env...
docker compose up -d --no-deps --force-recreate --no-build alertes
if errorlevel 1 (
    echo [ERREUR] Echec re-creation conteneur
    exit /b 1
)

REM --- Verification ---
echo.
echo ------------------------------------------------------------
echo  Verification (logs alertes - 15 dernieres lignes)
echo ------------------------------------------------------------
timeout /t 3 /nobreak >nul
echo Valeur injectee dans le conteneur :
docker exec alertes printenv MIN_SCORE
echo.
docker logs alertes --tail 30 | findstr /i "score min cooldown heures zones wapiway demarre"

echo.
echo [TERMINE] MIN_SCORE = %NEW_SCORE% applique et conteneur recree.
endlocal