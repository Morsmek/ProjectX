#!/usr/bin/env bash
# Project Aegis — Local Deployment Script
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."

echo "╔══════════════════════════════════════════════╗"
echo "║         PROJECT AEGIS — LOCAL DEPLOY         ║"
echo "╚══════════════════════════════════════════════╝"

# 1. Generate keys if .env doesn't exist
if [[ ! -f "$ROOT/.env" ]]; then
    echo "[1/5] Generating cryptographic keys..."
    python3 "$SCRIPT_DIR/gen-keys.py"
else
    echo "[1/5] .env found, skipping key generation."
fi

# 2. Build images
echo "[2/5] Building Docker images..."
cd "$ROOT"
docker compose build --parallel

# 3. Start infrastructure first
echo "[3/5] Starting infrastructure (postgres, redis)..."
docker compose up -d postgres redis
sleep 5

# 4. Start core services
echo "[4/5] Starting core services..."
docker compose up -d blockchain hermes sdba oracle payment mesh vdi

# 5. Start frontend & modules
echo "[5/5] Starting modules and frontend..."
docker compose up -d munnin-note plinxx gateway frontend

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Aegis is running                            ║"
echo "║  Dashboard:  http://localhost:3000           ║"
echo "║  Gateway:    http://localhost:8080           ║"
echo "╚══════════════════════════════════════════════╝"
docker compose ps
