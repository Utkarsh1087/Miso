@echo off
title Project Riko Desktop Companion
echo Starting Riko Desktop Window...
start "" msedge --app=http://127.0.0.1:8080 --window-size=460,700 2>nul || start "" chrome --app=http://127.0.0.1:8080 --window-size=460,700
