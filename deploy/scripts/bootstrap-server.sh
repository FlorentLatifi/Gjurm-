#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 VPS for GJURMË. Run as root:
#   curl -fsSL https://raw.githubusercontent.com/FlorentLatifi/Gjurm-/main/deploy/scripts/bootstrap-server.sh | bash
# Then: copy deploy/.env.example to /opt/gjurme/.env, fill it in (chmod 600), add the deploy key.
set -euo pipefail
DEPLOY_USER=${DEPLOY_USER:-deploy}
APP_DIR=/opt/gjurme

apt-get update -y
apt-get install -y ca-certificates curl ufw unattended-upgrades fail2ban
# Docker Engine from Docker's official repository
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Unprivileged deploy user (CI connects as this user; it can only drive docker in APP_DIR)
id -u "$DEPLOY_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$DEPLOY_USER"
usermod -aG docker "$DEPLOY_USER"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 750 "$APP_DIR" "$APP_DIR/backups" "$APP_DIR/backup" "$APP_DIR/rclone"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 700 "/home/$DEPLOY_USER/.ssh"

# Firewall: SSH + HTTP(S) only. Postgres and the API are never published.
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

# SSH hardening: keys only
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl reload ssh || systemctl reload sshd || true

# Automatic security updates; Docker log rotation defaults
dpkg-reconfigure -f noninteractive unattended-upgrades
cat > /etc/docker/daemon.json <<'JSON'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "5" } }
JSON
systemctl restart docker

echo "Server ready. Next: put docker-compose.prod.yml, deploy.sh, backup/ and .env in $APP_DIR,"
echo "add the CI public key to /home/$DEPLOY_USER/.ssh/authorized_keys, then run a deploy."
