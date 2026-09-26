#!/usr/bin/env bash
# Idempotent setup for the NewsBreakout continuous collector on Ubuntu 24.04.
# Safe to re-run: every step checks current state before changing anything.
#
# Usage: sudo bash deploy/setup.sh [git-ref]
#   git-ref defaults to the DEPLOY_TAG below (a tag, e.g. collector-v2.0 - not
#   a branch, so the VM always runs an exact, reviewed commit).
#
# What this does NOT do:
#   - write /etc/newsbreakout/collector.env (the secret HEALTHCHECKS_PING_URL) -
#     that is a manual, one-time step (see deploy/README.md), never committed.
#   - enable the systemd timer - that is a separate, deliberate step after the
#     first manual verification run (see deploy/README.md).
#   - configure rclone - `rclone config` is interactive; run it once yourself
#     as the newsbreakout user (see deploy/README.md).

set -euo pipefail

REPO_URL="https://github.com/luu-quang/NewsBreakout-Early-Detection-of-Cross-Community-News-Diffusion.git"
DEPLOY_TAG="${1:-collector-v2.0}"
REPO_DIR="/opt/newsbreakout"
SERVICE_USER="newsbreakout"
CONFIG_DIR="/etc/newsbreakout"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash deploy/setup.sh" >&2
  exit 1
fi

echo "==> apt dependencies"
apt-get update -qq
apt-get install -y --no-install-recommends \
  git python3 python3-venv python3-pip chrony rclone logrotate ca-certificates

echo "==> chrony (NTP) - accurate clocks matter for first_seen_at/last_seen_at"
systemctl enable --now chrony >/dev/null

echo "==> timezone: UTC (idempotent regardless of current setting)"
timedatectl set-timezone UTC

echo "==> service user: ${SERVICE_USER}"
if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --shell /usr/sbin/nologin --home-dir "${REPO_DIR}" "${SERVICE_USER}"
fi
mkdir -p "${REPO_DIR}"
chown "${SERVICE_USER}:${SERVICE_USER}" "${REPO_DIR}"

echo "==> repository at ${REPO_DIR}, pinned to tag ${DEPLOY_TAG}"
if [ -d "${REPO_DIR}/.git" ]; then
  sudo -u "${SERVICE_USER}" git -C "${REPO_DIR}" fetch --tags origin
else
  sudo -u "${SERVICE_USER}" git clone "${REPO_URL}" "${REPO_DIR}"
  sudo -u "${SERVICE_USER}" git -C "${REPO_DIR}" fetch --tags origin
fi
# Detached HEAD at an exact tag - never a branch, so the VM's code never
# drifts without a deliberate re-deploy (re-run this script with a new tag).
sudo -u "${SERVICE_USER}" git -C "${REPO_DIR}" checkout "${DEPLOY_TAG}"

echo "==> Python virtualenv + dependencies"
if [ ! -d "${REPO_DIR}/.venv" ]; then
  sudo -u "${SERVICE_USER}" python3 -m venv "${REPO_DIR}/.venv"
fi
sudo -u "${SERVICE_USER}" "${REPO_DIR}/.venv/bin/pip" install -q --upgrade pip
sudo -u "${SERVICE_USER}" "${REPO_DIR}/.venv/bin/pip" install -q -r "${REPO_DIR}/requirements.txt"

echo "==> config directory ${CONFIG_DIR} (for the secret env file - you create the file itself)"
mkdir -p "${CONFIG_DIR}"
chown "${SERVICE_USER}:${SERVICE_USER}" "${CONFIG_DIR}"
chmod 700 "${CONFIG_DIR}"

echo "==> systemd units"
install -m 644 "${REPO_DIR}/deploy/collector-runner.service" /etc/systemd/system/collector-runner.service
install -m 644 "${REPO_DIR}/deploy/collector-runner.timer" /etc/systemd/system/collector-runner.timer
install -m 644 "${REPO_DIR}/deploy/backup-daily.service" /etc/systemd/system/backup-daily.service
install -m 644 "${REPO_DIR}/deploy/backup-daily.timer" /etc/systemd/system/backup-daily.timer
mkdir -p /var/log/newsbreakout
chown "${SERVICE_USER}:${SERVICE_USER}" /var/log/newsbreakout
install -m 644 "${REPO_DIR}/deploy/newsbreakout-logrotate" /etc/logrotate.d/newsbreakout
systemctl daemon-reload

echo
echo "==> Setup done. Deployed tag: ${DEPLOY_TAG}"
echo "Next (manual, see deploy/README.md):"
echo "  1. Create ${CONFIG_DIR}/collector.env (chmod 600) with HEALTHCHECKS_PING_URL=..."
echo "  2. sudo -u ${SERVICE_USER} rclone config   # one-time, interactive, for backups"
echo "  3. Run the collector by hand ONCE and inspect its output before enabling the timer:"
echo "     sudo -u ${SERVICE_USER} ${REPO_DIR}/.venv/bin/python3 ${REPO_DIR}/scripts/run_collectors.py --fetch-timeout 20 --child-timeout 120"
echo "  4. Only after that looks right: sudo systemctl enable --now collector-runner.timer"
