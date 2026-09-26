#!/usr/bin/env bash
# Daily off-VM backup of the v2 raw corpus (data/raw/v2/: payloads, sightings,
# feed_state, heartbeat) via rclone. This is the actual collected data - the
# whole point of the continuous collector - not just config, so losing it to
# a VM failure would lose real project data.
#
# One-time prerequisite (interactive, run once as the newsbreakout user):
#   sudo -u newsbreakout rclone config
# Then set RCLONE_REMOTE in /etc/newsbreakout/backup.env, e.g.:
#   RCLONE_REMOTE=gdrive:newsbreakout-backups
set -euo pipefail

REPO_DIR="/opt/newsbreakout"
BACKUP_SRC="${REPO_DIR}/data/raw/v2"
DATE_TAG="$(date -u +%Y-%m-%d)"
TMP_TARBALL="/tmp/newsbreakout-v2-${DATE_TAG}.tar.gz"

if [ -z "${RCLONE_REMOTE:-}" ]; then
  echo "RCLONE_REMOTE not set (see /etc/newsbreakout/backup.env) - skipping backup" >&2
  exit 0
fi

if [ ! -d "${BACKUP_SRC}" ]; then
  echo "Nothing to back up yet: ${BACKUP_SRC} does not exist" >&2
  exit 0
fi

trap 'rm -f "${TMP_TARBALL}"' EXIT

tar czf "${TMP_TARBALL}" -C "${REPO_DIR}/data/raw" v2
rclone copy "${TMP_TARBALL}" "${RCLONE_REMOTE}"
echo "Backed up ${BACKUP_SRC} to ${RCLONE_REMOTE} (${DATE_TAG})"
