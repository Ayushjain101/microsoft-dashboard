#!/usr/bin/env bash
set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$APP_DIR/backend"
FRONTEND_DIR="$APP_DIR/frontend"
VENV_DIR="$BACKEND_DIR/.venv"

echo "==> Deploying from $APP_DIR"

# ── 1. System dependencies (first run only) ─────────────────────────────
install_system_deps() {
    echo "==> Installing system dependencies..."
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv python3-pip \
        postgresql redis-server caddy \
        nodejs npm \
        build-essential libpq-dev curl > /dev/null

    # Install Node 20 via NodeSource if not present
    if ! node --version 2>/dev/null | grep -q "v20\|v21\|v22"; then
        echo "==> Installing Node.js 20..."
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
        apt-get install -y -qq nodejs > /dev/null
    fi
}

# ── 2. PostgreSQL setup ─────────────────────────────────────────────────
setup_postgres() {
    echo "==> Setting up PostgreSQL..."
    systemctl enable --now postgresql

    # Create user and database if they don't exist
    sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='tenantadmin'" | grep -q 1 || \
        sudo -u postgres psql -c "CREATE USER tenantadmin WITH PASSWORD '${DB_PASSWORD:-dbpass}';"
    sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='tenants'" | grep -q 1 || \
        sudo -u postgres createdb -O tenantadmin tenants
    # Ensure password is current
    sudo -u postgres psql -c "ALTER USER tenantadmin WITH PASSWORD '${DB_PASSWORD:-dbpass}';" 2>/dev/null || true
}

# ── 3. Redis setup ──────────────────────────────────────────────────────
setup_redis() {
    echo "==> Setting up Redis..."
    # Set password if not already set
    if ! grep -q "^requirepass" /etc/redis/redis.conf 2>/dev/null; then
        echo "requirepass ${REDIS_PASSWORD:-redispass}" >> /etc/redis/redis.conf
    fi
    systemctl enable --now redis-server
    systemctl restart redis-server
}

# ── 4. Backend ──────────────────────────────────────────────────────────
deploy_backend() {
    echo "==> Deploying backend..."
    cd "$BACKEND_DIR"

    # Create/update venv
    if [ ! -d "$VENV_DIR" ]; then
        python3 -m venv "$VENV_DIR"
    fi
    "$VENV_DIR/bin/pip" install -q --upgrade pip
    "$VENV_DIR/bin/pip" install -q -r requirements.txt

    # Run migrations
    "$VENV_DIR/bin/alembic" upgrade head 2>/dev/null || echo "  (no migrations or already up to date)"
}

# ── 5. Frontend ─────────────────────────────────────────────────────────
deploy_frontend() {
    echo "==> Deploying frontend..."
    cd "$FRONTEND_DIR"
    npm install --silent
    npm run build
}

# ── 6. Systemd services ────────────────────────────────────────────────
install_services() {
    echo "==> Installing systemd services..."

    # Load .env for the service files
    ENV_FILE="$APP_DIR/.env"

    # --- API ---
    cat > /etc/systemd/system/tenant-api.service <<EOF
[Unit]
Description=Tenant Dashboard API
After=network.target postgresql.service redis-server.service
Requires=postgresql.service redis-server.service

[Service]
Type=simple
User=root
WorkingDirectory=$BACKEND_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_DIR/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    # --- Celery Worker ---
    cat > /etc/systemd/system/tenant-celery.service <<EOF
[Unit]
Description=Tenant Celery Worker
After=network.target postgresql.service redis-server.service
Requires=redis-server.service

[Service]
Type=simple
User=root
WorkingDirectory=$BACKEND_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_DIR/bin/celery -A app.tasks.celery_app worker -Q default,mailbox,monitor -c 4 --loglevel=info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    # --- Celery Beat ---
    cat > /etc/systemd/system/tenant-beat.service <<EOF
[Unit]
Description=Tenant Celery Beat
After=network.target redis-server.service
Requires=redis-server.service

[Service]
Type=simple
User=root
WorkingDirectory=$BACKEND_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_DIR/bin/celery -A app.tasks.celery_app beat --loglevel=info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    # --- Frontend ---
    cat > /etc/systemd/system/tenant-frontend.service <<EOF
[Unit]
Description=Tenant Dashboard Frontend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$FRONTEND_DIR
Environment=NODE_ENV=production
Environment=PORT=3000
ExecStart=$(which node) $FRONTEND_DIR/.next/standalone/server.js
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    # --- Caddy ---
    mkdir -p /etc/caddy
    cp "$APP_DIR/Caddyfile" /etc/caddy/Caddyfile

    systemctl daemon-reload
}

# ── 7. Start everything ────────────────────────────────────────────────
start_services() {
    echo "==> Starting services..."
    systemctl enable --now tenant-api tenant-celery tenant-beat tenant-frontend
    systemctl restart tenant-api tenant-celery tenant-beat tenant-frontend
    systemctl enable --now caddy
    systemctl reload caddy 2>/dev/null || systemctl restart caddy
    echo "==> All services started!"
}

# ── Main ────────────────────────────────────────────────────────────────
if [ ! -f "$APP_DIR/.env" ]; then
    echo "ERROR: .env file not found at $APP_DIR/.env"
    echo "Copy .env.example to .env and fill in values first."
    exit 1
fi

# Source .env for setup steps
set -a; source "$APP_DIR/.env"; set +a

# Check if this is first run (system deps needed)
if [ "${1:-}" = "--init" ]; then
    install_system_deps
    setup_postgres
    setup_redis
fi

deploy_backend
deploy_frontend
install_services
start_services

echo ""
echo "==> Deployment complete!"
echo "    API:      http://localhost:8000"
echo "    Frontend: http://localhost:3000"
echo "    Site:     https://decimastellarbolt.info"
echo ""
echo "    Logs: journalctl -u tenant-api -f"
echo "          journalctl -u tenant-frontend -f"
