#!/bin/bash
# ================================================================
# phingr-web deploy script
# ================================================================
# Sets up the phingr product website on a fresh Ubuntu 25.04 VPS.
# Clones the repo, installs deps, configures nginx + SSL + systemd.
#
# Usage:
#   sudo bash deploy.sh YOUR_DOMAIN
#
# Prerequisites:
#   - Ubuntu 25.04 on Sakura VPS
#   - Domain DNS A record pointing to this server's IP
#   - Run as root or with sudo
# ================================================================

set -euo pipefail

DOMAIN="${1:?Usage: sudo bash deploy.sh YOUR_DOMAIN}"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: Run as root or with sudo"
  exit 1
fi

APP_DIR="/opt/phingr-web"
REPO="https://github.com/sumioturk/phingr-web.git"

echo ""
echo "========================================"
echo " phingr-web deploy"
echo " domain: ${DOMAIN}"
echo " target: Ubuntu 25.04"
echo "========================================"
echo ""

# ================================================================
# 1. System packages
# ================================================================
echo "[1/8] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
  nginx \
  certbot \
  python3-certbot-nginx \
  python3-venv \
  python3-pip \
  git \
  ufw

# ================================================================
# 2. Firewall
# ================================================================
echo "[2/8] Configuring firewall..."
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# ================================================================
# 3. Clone or update repo
# ================================================================
echo "[3/8] Fetching application..."
if [ -d "${APP_DIR}/.git" ]; then
  cd "${APP_DIR}"
  git fetch origin
  git reset --hard origin/main
else
  rm -rf "${APP_DIR}"
  git clone --depth=1 "${REPO}" "${APP_DIR}"
fi

# ================================================================
# 4. Python environment
# ================================================================
echo "[4/8] Setting up Python environment..."
python3 -m venv "${APP_DIR}/venv"
"${APP_DIR}/venv/bin/pip" install -q --upgrade pip
"${APP_DIR}/venv/bin/pip" install -q -r "${APP_DIR}/requirements.txt"

# ================================================================
# 5. Environment file
# ================================================================
echo "[5/8] Configuring environment..."
if [ ! -f "${APP_DIR}/.env" ]; then
  cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
  sed -i "s|SITE_URL=https://yourdomain.com|SITE_URL=https://${DOMAIN}|" "${APP_DIR}/.env"
  chmod 600 "${APP_DIR}/.env"
  echo "    .env created — edit with your Stripe keys later."
else
  echo "    .env exists, skipping."
fi

chown -R www-data:www-data "${APP_DIR}"

# ================================================================
# 6. nginx
# ================================================================
echo "[6/8] Configuring nginx..."

# Rate limiting
if ! grep -q "limit_req_zone" /etc/nginx/nginx.conf; then
  sed -i '/http {/a \    limit_req_zone $binary_remote_addr zone=api:10m rate=10r\/s;' /etc/nginx/nginx.conf
fi

# Temporary HTTP-only config for certbot verification
cat > /etc/nginx/sites-available/phingr-web <<TMPNGINX
server {
    listen 80;
    server_name ${DOMAIN};
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
TMPNGINX

ln -sf /etc/nginx/sites-available/phingr-web /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# ================================================================
# 7. SSL certificate
# ================================================================
echo "[7/8] Obtaining SSL certificate..."
certbot --nginx -d "${DOMAIN}" \
  --non-interactive --agree-tos --redirect \
  --email "admin@${DOMAIN}"

# Install hardened config
cat > /etc/nginx/sites-available/phingr-web <<NGINXEOF
server {
    listen 80;
    server_name ${DOMAIN};
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;

    # TLS
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security headers
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # API rate limiting
    location /api/ {
        limit_req zone=api burst=20 nodelay;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINXEOF

nginx -t && systemctl reload nginx

# ================================================================
# 8. systemd service
# ================================================================
echo "[8/8] Setting up systemd service..."
cat > /etc/systemd/system/phingr-web.service <<SVCEOF
[Unit]
Description=phingr website
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

# Security
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${APP_DIR}
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectControlGroups=true

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable --now phingr-web

# ================================================================
# Done
# ================================================================
echo ""
echo "========================================"
echo " deploy complete"
echo "========================================"
echo ""
echo " site:  https://${DOMAIN}"
echo " repo:  ${REPO}"
echo " app:   ${APP_DIR}"
echo ""
echo " next steps:"
echo ""
echo " 1. edit stripe keys:"
echo "    sudo nano ${APP_DIR}/.env"
echo ""
echo " 2. restart after editing:"
echo "    sudo systemctl restart phingr-web"
echo ""
echo " 3. add stripe webhook:"
echo "    url:    https://${DOMAIN}/api/webhook"
echo "    events: checkout.session.completed"
echo "            customer.subscription.deleted"
echo "            invoice.payment_failed"
echo ""
echo " commands:"
echo "    sudo systemctl status phingr-web"
echo "    sudo journalctl -u phingr-web -f"
echo "    sudo certbot renew --dry-run"
echo ""
echo " to update the site:"
echo "    cd ${APP_DIR} && sudo git pull && sudo systemctl restart phingr-web"
echo ""
echo "========================================"
echo " our philosophy"
echo "========================================"
echo ""
echo " we believe in human honesty."
echo ""
echo " there is no license server. no activation key."
echo " no DRM. no usage tracking. no protection"
echo " mechanism of any kind. the software runs without"
echo " restriction whether you have a subscription or not."
echo ""
echo " subscription is voluntary. if you use phingr and"
echo " it brings value to your work, we trust you to"
echo " subscribe. that's it."
echo ""
echo " no enforcement. no nagging. no crippled features."
echo " the full product is the full product."
echo ""
