#!/usr/bin/env bash

# CONFIGURATION
EXPECTED_VPN_IP="${EXPECTED_AIRVPN_DUTCH_IP:-213.152.162.114}"
QBIT_HOST="http://localhost:8090"
LOCK_FILE="/shared/torrent_disabled.lock"

echo "[Watchdog] Starting Native VPN Circuit Breaker..."

while true; do
  # Fetch current external IP routed natively through WireGuard (with 3 retries)
  CURRENT_IP=""
  for i in 1 2 3; do
    CURRENT_IP=$(curl -s --max-time 10 https://api.ipify.org 2>/dev/null)
    if [ -n "$CURRENT_IP" ]; then
      break
    fi
    sleep 3
  done

  # Check if proxy is active AND returning the exact AirVPN IP
  if [ -n "$CURRENT_IP" ] && [ "$CURRENT_IP" == "$EXPECTED_VPN_IP" ]; then
    if [ -f "$LOCK_FILE" ]; then
      echo "[Watchdog] VPN Connection Restored ($CURRENT_IP). Resuming torrents..."
      curl -s -X POST "${QBIT_HOST}/api/v2/torrents/resume" -d "hashes=all"
      rm -f "$LOCK_FILE"
    fi
  else
    echo "[Watchdog] CRITICAL FAIL: VPN Unreachable or IP mismatch! Current IP: '${CURRENT_IP}'. Tripping breaker!"
    
    # 1. Pause all active qBittorrent downloads
    curl -s -X POST "${QBIT_HOST}/api/v2/torrents/pause" -d "hashes=all"
    
    # 2. Write lockfile to block incoming Telegram commands
    if [ ! -f "$LOCK_FILE" ]; then
      touch "$LOCK_FILE"
    fi
  fi

  sleep 30
done
