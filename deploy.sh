#!/bin/bash
set -e

export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a

echo "=== 1. Updating System Packages ==="
apt-get update
apt-get -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" upgrade

echo "=== 2. Installing Dependencies (Python, PostgreSQL, Nginx, Git) ==="
apt-get install -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" python3-pip python3-venv git postgresql postgresql-contrib nginx curl ufw

echo "=== 3. Configuring PostgreSQL Database ==="
sudo -u postgres psql -c "CREATE USER botuser WITH PASSWORD 'perfume_secret_73752';" || true
sudo -u postgres psql -c "CREATE DATABASE perfume_bot OWNER botuser;" || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE perfume_bot TO botuser;" || true

echo "=== 4. Setting up Project Repository ==="
cd /root
if [ -d "GramCRM" ]; then
    cd GramCRM
    git pull origin main
elif [ -d "Instagram-Perfume-Assistant" ]; then
    cd Instagram-Perfume-Assistant
    git pull origin main
else
    git clone https://github.com/MHTAHERII/GramCRM.git
    cd GramCRM
fi

echo "=== 5. Setting up Python Virtual Environment ==="
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
./venv/bin/pip install psycopg2-binary requests uvicorn[standard] fastapi sqlalchemy pydantic python-dotenv itsdangerous psutil python-multipart websockets

echo "=== 6. Creating Production Environment Config (.env) ==="
if [ ! -f .env ]; then
cat << 'EOF' > .env
DATABASE_URL=postgresql://botuser:perfume_secret_73752@localhost:5432/perfume_bot
IG_POLL_INTERVAL=5
ADMIN_PASSWORD=admin123
ADMIN_SESSION_SECRET=perfume-super-secret-key-2026-production

# Zernio API & Platform
ENABLE_IG_WORKER=true
ZERNIO_API_KEY=sk_c1ab016dc6831fe85b1ab845842361059c4d2cf007385d2107696d557174256c
ZERNIO_PROFILE_ID=6ab54273f7f577b65b90aaca
ZERNIO_ACCOUNT_ID=6ab54a588d284ffb213d4274

# Meta Webhook Tokens
META_VERIFY_TOKEN=perfume_bot_verify_token_2026
EOF
    echo ".env created successfully."
else
    echo "Existing .env found. Keeping your current configuration."
fi

# Determine cloned directory
if [ -d "/root/GramCRM" ]; then
    APP_DIR="/root/GramCRM"
else
    APP_DIR="/root/Instagram-Perfume-Assistant"
fi

echo "=== 7. Setting up 24/7 Systemd Service ==="
cat << EOF > /etc/systemd/system/gramcrm.service
[Unit]
Description=GramCRM - Instagram Sales Automation & CRM
After=network.target postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable gramcrm
systemctl restart gramcrm

echo "=== 8. Configuring Nginx Reverse Proxy (Port 80 -> 8000) ==="
cat << 'EOF' > /etc/nginx/sites-available/gramcrm
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    client_max_body_size 25M;

    location /ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

ln -sf /etc/nginx/sites-available/gramcrm /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx

echo "=== 9. Configuring Firewall ==="
ufw allow 22/tcp || true
ufw allow 80/tcp || true
ufw allow 443/tcp || true
ufw --force enable || true

SERVER_IPV4=$(curl -4 -s --max-time 4 https://api.ipify.org || curl -4 -s --max-time 4 https://ifconfig.me || hostname -I | awk '{print $1}')
SERVER_IPV6=$(curl -6 -s --max-time 4 https://api64.ipify.org || curl -6 -s --max-time 4 https://ifconfig.me || true)

echo ""
echo "=========================================================="
echo "  🎉 GramCRM INSTALLED & RUNNING 24/7! 🚀"
echo "=========================================================="
if [ -n "$SERVER_IPV4" ]; then
echo "  🌐 IPv4 Panel:    http://${SERVER_IPV4}/panel"
echo "  🔗 IPv4 Webhook:  http://${SERVER_IPV4}/webhook/zernio"
fi
if [ -n "$SERVER_IPV6" ] && [ "$SERVER_IPV6" != "$SERVER_IPV4" ]; then
echo "  🌐 IPv6 Panel:    http://[${SERVER_IPV6}]/panel"
echo "  🔗 IPv6 Webhook:  http://[${SERVER_IPV6}]/webhook/zernio"
fi
echo "=========================================================="
