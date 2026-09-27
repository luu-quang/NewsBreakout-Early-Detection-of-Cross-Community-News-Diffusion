"""Fetch the latest off-VM backup (see ``deploy/backup_daily.sh``) and extract
it into ``data/raw/v2/``, for teammates without SSH access to the VM.

Three ways to run it, in order of convenience:

1. You have your own rclone remote pointed at the same Drive folder::

    python3 scripts/pull_snapshot.py --rclone-remote gdrive:newsbreakout-backups

2. You don't have rclone set up, but can open the Drive folder in a browser -
   run with no arguments for the manual-download instructions, then::

    python3 scripts/pull_snapshot.py --local-tarball /path/to/newsbreakout-v2-2026-09-27.tar.gz

The backup tarball is a full snapshot of ``data/raw/v2/`` at backup time (not
incremental), so extracting the latest one is always sufficient - no need to
merge multiple days.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEST_DIR = REPO_ROOT / "data" / "raw"
TARBALL_GLOB = "newsbreakout-v2-*.tar.gz"

MANUAL_INSTRUCTIONS = f"""
No --local-tarball given and no usable rclone remote found.

Manual steps:
  1. Open the shared Google Drive backup folder in your browser (ask
     whoever set up the VM for the link, if you don't have it).
  2. Download the newest file matching {TARBALL_GLOB!r} (sorted by the date
     in its name, e.g. newsbreakout-v2-2026-09-27.tar.gz - pick the latest).
  3. Re-run this script pointing at the downloaded file:

       python3 scripts/pull_snapshot.py --local-tarball /path/to/newsbreakout-v2-YYYY-MM-DD.tar.gz
"""


def _extract(tarball: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as tar:
        try:
            tar.extractall(dest_dir, filter="data")
        except TypeError:
            # Python < 3.12 has no `filter` kwarg; the tarball is our own
            # trusted backup format, not untrusted third-party input.
            tar.extractall(dest_dir)
    print(f"Extracted {tarball} -> {dest_dir}/v2/")


def _rclone_available() -> bool:
    return shutil.which("rclone") is not None


def _run_rclone(args: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(["rclone", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"rclone {' '.join(args)} failed (exit {result.returncode}):\n{result.stderr.strip()}\n\n"
            "Most likely cause: this machine's rclone has no remote by that name yet "
            "(the VM's rclone config is separate from yours - run `rclone config` here "
            "first, or check with `rclone listremotes`). Falling back to manual download "
            "is always an option - see the --local-tarball instructions below."
        )
    return result


def _latest_remote_tarball(remote: str) -> str | None:
    result = _run_rclone(["lsf", remote, "--include", TARBALL_GLOB])
    names = sorted(line.strip() for line in result.stdout.splitlines() if line.strip())
    return names[-1] if names else None


def pull_via_rclone(remote: str) -> Path:
    remote = remote.rstrip("/")
    latest = _latest_remote_tarball(remote)
    if latest is None:
        raise SystemExit(f"No {TARBALL_GLOB!r} file found on {remote} - has a backup ever run?")
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        _run_rclone(["copy", f"{remote}/{latest}", str(tmp)])
        tarball = tmp / latest
        _extract(tarball, DEST_DIR)
    return DEST_DIR / "v2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rclone-remote", default=None, help="e.g. gdrive:newsbreakout-backups")
    parser.add_argument("--local-tarball", type=Path, default=None, help="Already-downloaded backup tarball to extract.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.local_tarball is not None:
        if not args.local_tarball.is_file():
            raise SystemExit(f"No such file: {args.local_tarball}")
        _extract(args.local_tarball, DEST_DIR)
        return
    if args.rclone_remote and _rclone_available():
        pull_via_rclone(args.rclone_remote)
        return
    print(MANUAL_INSTRUCTIONS)
    sys.exit(1)


if __name__ == "__main__":
    main()
