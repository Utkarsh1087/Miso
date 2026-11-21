@echo off
set ELECTRON_RUN_AS_NODE=
title Riko Desktop Pet and Voice Companion
echo ============================================================
echo   Starting Project Riko (Transparent Pet and Voice Engine)
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/2] Starting Riko AI Brain and Local Server...
start "Riko AI Backend" cmd /k "python main.py --hands-free"

echo [2/2] Waiting 2 seconds for server initialization...
timeout /t 2 /nobreak >nul

echo [3/3] Launching Floating Transparent Desktop Pet...
npx electron electron_pet.js
