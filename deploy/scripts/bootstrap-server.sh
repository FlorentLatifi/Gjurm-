#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 VPS for GJURMË. Run as root, pinned to a reviewed commit
# (never pipe a moving branch into a root shell):
#   curl -fsSLO https://raw.githubusercontent.com/FlorentLatifi/Gjurm-/<commit-sha>/deploy/scripts/bootstrap-server.sh
#   less bootstrap-server.sh && bash bootstrap-server.sh
# Then: copy deploy/.env.example to /opt/gjurme/.env, fill it in (chmod 600), add the deploy key.
set -euo pipefail
DEPLOY_USER=${DEPLOY_USER:-deploy}
APP_DIR=/opt/gjurme

# Oracle Cloud (OCI) platform images ship their own iptables rules, including the rules that keep
# the iSCSI boot volume reachable; Oracle warns that enabling UFW there can stop the instance from
# booting. Detect them and edit those rules instead of using UFW.
OCI_RULES=/etc/iptables/rules.v4
if [[ -f "$OCI_RULES" ]] && grep -q '169.254.0.2' "$OCI_RULES"; then IS_OCI=1; else IS_OCI=0; fi

apt-get update -y
apt-get install -y ca-certificates curl unattended-upgrades fail2ban
[[ "$IS_OCI" == 1 ]] || apt-get install -y ufw
# Docker Engine from Docker's official repository
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Deploy user for CI (key-only SSH). Membership of the docker group is root-equivalent on this
# host; that is accepted for a single-purpose server (docs/SECURITY.md#accepted-risks).
id -u "$DEPLOY_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$DEPLOY_USER"
usermod -aG docker "$DEPLOY_USER"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 750 "$APP_DIR" "$APP_DIR/backups" "$APP_DIR/backup" "$APP_DIR/rclone"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 700 "/home/$DEPLOY_USER/.ssh"

# Firewall: SSH + HTTP(S) only. Postgres and the API are never published.
# On OCI the cloud-side Security List must ALSO allow 80/443 (docs/DEPLOYMENT.md#oracle-cloud).
oci_allow() { # insert an ACCEPT rule before the first INPUT REJECT of an iptables-save file
  local file="$1" rule="$2"
  grep -qxF -- "$rule" "$file" && return 0
  awk -v r="$rule" '!done && /^-A INPUT -j REJECT/ { print r; done = 1 } { print }' "$file" > "$file.tmp"
  grep -qxF -- "$rule" "$file.tmp" || { echo "no INPUT REJECT rule in $file; open ports by hand" >&2; exit 1; }
  cat "$file.tmp" > "$file" && rm -f "$file.tmp"
}
if [[ "$IS_OCI" == 1 ]]; then
  cp -n "$OCI_RULES" "$OCI_RULES.pre-gjurme"
  oci_allow "$OCI_RULES" "-A INPUT -p tcp -m state --state NEW -m tcp --dport 80 -j ACCEPT"
  oci_allow "$OCI_RULES" "-A INPUT -p tcp -m state --state NEW -m tcp --dport 443 -j ACCEPT"
  oci_allow "$OCI_RULES" "-A INPUT -p udp -m udp --dport 443 -j ACCEPT"
  iptables-restore --test < "$OCI_RULES" && iptables-restore < "$OCI_RULES"
  # Docker's own chains are recreated by the Docker restart at the end of this script.
else
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow OpenSSH
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw allow 443/udp
  ufw --force enable
fi

# SSH hardening: keys only
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl reload ssh || systemctl reload sshd || true

# Swap: container memory limits add up to ~2.3 GB, so a 2 GB server needs headroom for spikes
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl -w vm.swappiness=10 && echo 'vm.swappiness=10' > /etc/sysctl.d/99-gjurme.conf
fi

# Automatic security updates; Docker log rotation defaults
dpkg-reconfigure -f noninteractive unattended-upgrades
cat > /etc/docker/daemon.json <<'JSON'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "5" } }
JSON
systemctl restart docker

echo "Server ready. Next: put docker-compose.prod.yml, deploy.sh, backup/ and .env in $APP_DIR,"
echo "add the CI public key to /home/$DEPLOY_USER/.ssh/authorized_keys, then run a deploy."
