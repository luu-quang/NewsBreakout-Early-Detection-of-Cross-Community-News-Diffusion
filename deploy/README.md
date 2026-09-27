# Deploying the continuous collector (Azure VM, Ubuntu 24.04)

Technical reference for the exact commands. This is not the non-technical
Vietnamese runbook mentioned in `docs/HANDOFF_2026-09-26.md` ("Tài liệu" ->
`docs/COLLECTOR_RUNBOOK.md`) - that's still open, separate from this.

Everything here assumes the VM already exists and you can SSH into it.
Commands prefixed `you@vm$` run on the VM over SSH; nothing here is run from
this sandbox - it has no access to the VM.

## 1. Get the code onto the VM and set everything up

```bash
you@vm$ git clone https://github.com/luu-quang/NewsBreakout-Early-Detection-of-Cross-Community-News-Diffusion.git /tmp/nb-bootstrap
you@vm$ cd /tmp/nb-bootstrap
you@vm$ git checkout collector-v2.0   # or whatever tag you're deploying
you@vm$ sudo bash deploy/setup.sh collector-v2.0
```

`setup.sh` is idempotent - re-running it (e.g. to deploy a newer tag later) is
safe. It installs system packages, enables chrony, sets the timezone to UTC,
creates a dedicated `newsbreakout` system user, clones the real repo to
`/opt/newsbreakout` pinned to the given tag (detached HEAD, not a branch),
builds the venv, and installs the systemd units + logrotate config - but does
**not** enable the timer yet, and does **not** create the two secret env
files (next steps).

You can delete `/tmp/nb-bootstrap` afterward; it was only used to fetch
`deploy/*` before the real clone exists.

## 2. Healthchecks.io ping URL (secret, not committed)

Create a check at healthchecks.io yourself (free tier is fine), then:

```bash
you@vm$ sudo install -m 600 -o newsbreakout -g newsbreakout /dev/null /etc/newsbreakout/collector.env
you@vm$ sudo -u newsbreakout tee /etc/newsbreakout/collector.env >/dev/null <<'EOF'
HEALTHCHECKS_PING_URL=https://hc-ping.com/YOUR-UUID-HERE
EOF
you@vm$ sudo chmod 600 /etc/newsbreakout/collector.env
```

(See `deploy/collector.env.example` for the exact format.)

## 3. Backup destination (rclone, one-time interactive setup)

```bash
you@vm$ sudo -u newsbreakout rclone config
```

Follow the prompts to add a remote (Google Drive, S3, Azure Blob, whatever
you prefer) - this is interactive and I cannot do it for you. Note the remote
name you chose, then:

```bash
you@vm$ sudo install -m 600 -o newsbreakout -g newsbreakout /dev/null /etc/newsbreakout/backup.env
you@vm$ sudo -u newsbreakout tee /etc/newsbreakout/backup.env >/dev/null <<'EOF'
RCLONE_REMOTE=your-remote-name:newsbreakout-backups
EOF
you@vm$ sudo chmod 600 /etc/newsbreakout/backup.env
```

## 4. Manual verification run - do this BEFORE enabling the timer

```bash
you@vm$ sudo -u newsbreakout /opt/newsbreakout/.venv/bin/python3 /opt/newsbreakout/scripts/run_collectors.py --fetch-timeout 20 --child-timeout 120
```

Paste me the full output - the JSON heartbeat record at the end
(`overall_ok`, per-child `ok`/`duration_seconds`/counts/`error`). Note this
only shows aggregate per-branch counts: `runner.py` captures each collector's
stdout internally (`subprocess.run(..., capture_output=True)`) so it never
reaches your terminal - a feed that fetches successfully but silently
returns 0 entries (found live once: a CDN gzip-compressing the response
without being asked, which `feedparser` can't parse as XML) won't show up
here at all.

If `overall_ok` is false, or a feed you just added doesn't seem to be
contributing anything to `new_payloads`/`entries_seen`, run that one
collector directly instead (bypasses the runner, so its own
`[rss] fetching <id>: <url>` / `[rss] fetch failed for <id>: <error>` /
`[rss] parse failed for <id>: <error>` lines print straight to your
terminal):

```bash
you@vm$ sudo -u newsbreakout /opt/newsbreakout/.venv/bin/python3 /opt/newsbreakout/team_work/phases/phase1_collection_cleaning/vietnamese_team/code/collect_vn.py --continuous --collector-host $(hostname) --fetch-timeout 20
you@vm$ sudo -u newsbreakout /opt/newsbreakout/.venv/bin/python3 /opt/newsbreakout/team_work/phases/phase1_collection_cleaning/international_team/code/collect_intl.py --continuous --collector-host $(hostname) --fetch-timeout 20
```

If a specific feed is blocked or fails from the VM's network but worked from
here earlier, that's exactly what this step is for - tell me which one and
I'll help figure out why (blocked outbound IP range, DNS, TLS, gzip/encoding
mismatch, etc.).

## 5. Enable the timers

Only after step 4 looks right:

```bash
you@vm$ sudo systemctl enable --now collector-runner.timer
you@vm$ sudo systemctl enable --now backup-daily.timer
you@vm$ systemctl list-timers | grep newsbreakout
```

## Checking on it later

```bash
you@vm$ systemctl status collector-runner.timer collector-runner.service
you@vm$ tail -50 /var/log/newsbreakout/collector.log
you@vm$ tail -20 /var/log/newsbreakout/backup.log
you@vm$ cat /opt/newsbreakout/data/raw/v2/heartbeat/$(hostname)-$(date -u +%Y-%m).jsonl | tail -5
```

Per-feed detail (which feed is failing, gone quiet, or getting a suspicious
zero-entry response) doesn't show in the aggregate heartbeat tail above -
`runner.py` records it separately as `per_feed`/`feed_issues` (see
`src/collect_v2/feed_diagnostics.py`, `src/collect_v2/runner.py`). Print the
last 6 runs' per-feed table:

```bash
you@vm$ sudo -u newsbreakout /opt/newsbreakout/.venv/bin/python3 /opt/newsbreakout/scripts/show_feed_health.py --last 6
```

## Re-deploying a newer tag later

```bash
you@vm$ sudo systemctl stop collector-runner.timer
you@vm$ sudo bash /opt/newsbreakout/deploy/setup.sh <new-tag>
you@vm$ sudo systemctl start collector-runner.timer
```

Stopping the timer first just avoids a run starting mid-checkout; `setup.sh`
itself doesn't touch `data/raw/`.
