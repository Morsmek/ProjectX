#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# Project Aegis — VPS Bootstrap Script
# Tested on: Ubuntu 22.04 / Debian 12
# Run as root: curl -sSL <url>/vps-bootstrap.sh | bash
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

REPO="https://github.com/Morsmek/ProjectX.git"
BRANCH="claude/project-aegis-erp-3Q2AV"
INSTALL_DIR="/opt/aegis"

echo "╔══════════════════════════════════════════════════╗"
echo "║     Project Aegis — VPS Bootstrap               ║"
echo "╚══════════════════════════════════════════════════╝"

# ── 1. System update ────────────────────────────────────────────────────
echo "[1/8] Updating system packages…"
apt-get update -qq && apt-get upgrade -y -qq

# ── 2. Install Docker ────────────────────────────────────────────────────
echo "[2/8] Installing Docker…"
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
else
  echo "  Docker already installed."
fi

# ── 3. Install cloudflared ───────────────────────────────────────────────
echo "[3/8] Installing cloudflared…"
if ! command -v cloudflared &>/dev/null; then
  curl -L --output /tmp/cloudflared.deb \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb"
  dpkg -i /tmp/cloudflared.deb
  rm /tmp/cloudflared.deb
else
  echo "  cloudflared already installed."
fi

# ── 4. Clone repo ────────────────────────────────────────────────────────
echo "[4/8] Cloning Project Aegis repository…"
if [ -d "$INSTALL_DIR" ]; then
  cd "$INSTALL_DIR" && git pull origin "$BRANCH"
else
  git clone --branch "$BRANCH" "$REPO" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# ── 5. Generate secrets ──────────────────────────────────────────────────
echo "[5/8] Generating cryptographic keys…"
python3 scripts/gen-keys.py

# ── 6. Firewall: block all inbound except SSH ────────────────────────────
echo "[6/8] Configuring firewall…"
if command -v ufw &>/dev/null; then
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow 22/tcp comment "SSH"
  ufw --force enable
  echo "  UFW enabled — only SSH inbound. Cloudflare Tunnel handles all other traffic."
fi

# ── 7. Install systemd service ────────────────────────────────────────────
echo "[7/8] Installing systemd service…"
cat > /etc/systemd/system/aegis.service <<'SYSTEMD'
[Unit]
Description=Project Aegis ERP Stack
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/aegis
ExecStart=/usr/bin/docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.yml -f docker-compose.prod.yml down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
SYSTEMD

systemctl daemon-reload
systemctl enable aegis

# ── 8. Start stack ────────────────────────────────────────────────────────
echo "[8/8] Starting Aegis stack…"
echo ""
echo "  ⚠  Before starting, add your CLOUDFLARE_TUNNEL_TOKEN to .env"
echo "     then run:  systemctl start aegis"
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  Bootstrap complete.                            ║"
echo "║                                                 ║"
echo "║  Next steps:                                    ║"
echo "║  1. Edit /opt/aegis/.env                        ║"
echo "║     Add: CLOUDFLARE_TUNNEL_TOKEN=<your token>  ║"
echo "║  2. systemctl start aegis                       ║"
echo "║  3. Watch: journalctl -u aegis -f               ║"
echo "╚══════════════════════════════════════════════════╝"
