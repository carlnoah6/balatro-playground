#!/bin/bash
# Start Balatro with Xvfb (headless display) + lovely-injector (mod loading)
# No VNC needed - screenshots via scrot, AI control via TCP 12345

set -e

export DISPLAY=:99
RESOLUTION="1280x720x24"

echo "[*] Starting Xvfb on $DISPLAY ($RESOLUTION)..."
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
Xvfb :99 -screen 0 "$RESOLUTION" -ac +extension GLX +render -noreset &
XVFB_PID=$!
sleep 1

# Verify Xvfb is running
if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "[!] Xvfb failed to start"
    exit 1
fi
echo "[*] Xvfb running (PID: $XVFB_PID)"

# Check game directory
if [ ! -d "/opt/balatro-game" ] || [ -z "$(ls -A /opt/balatro-game 2>/dev/null)" ]; then
    echo "[!] No game files in /opt/balatro-game"
    echo "[!] Mount Balatro game directory or extract from Balatro.exe"
    echo "[*] Keeping container alive for debugging..."
    # Keep Xvfb running so we can test display + scrot
    wait $XVFB_PID
    exit 1
fi

echo "[*] Starting Balatro with lovely-injector..."
# lovely-injector uses LD_PRELOAD to hook into LÖVE and load mods
LD_PRELOAD=/usr/local/lib/liblovely.so love /opt/balatro-game &
GAME_PID=$!

echo "[*] Balatro PID: $GAME_PID"
echo "[*] AI TCP port: 12345"
echo "[*] Screenshots: scrot /opt/balatro-screenshots/shot.png"

# Auto-start AI agent if AUTO_AGENT=1
if [ "${AUTO_AGENT:-0}" = "1" ]; then
    echo "[*] Waiting 10s for game to initialize..."
    sleep 10
    echo "[*] Starting AI agent..."
    python3 /opt/balatro-ai/ai-agent.py &
    AGENT_PID=$!
    echo "[*] AI Agent PID: $AGENT_PID"
fi

# Wait for game process
wait $GAME_PID
