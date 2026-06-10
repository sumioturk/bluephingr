"""updater.py — Auto-update phingr from GitHub repo.

Periodically checks the remote branch for new commits and pulls
if there are changes. Optionally restarts services after update.

Usage:
    python3 rpi/updater.py
    python3 rpi/updater.py --interval 60 --branch master --restart

Can also run as a systemd service (phingr-updater.service).
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import time

log = logging.getLogger("phingr.updater")

DEFAULT_REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_BRANCH = "master"
DEFAULT_INTERVAL = 300  # 5 minutes
SERVICES_TO_RESTART = ["phingr-web.service"]


def git_run(cmd: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        f"git {cmd}", shell=True, cwd=cwd,
        capture_output=True, text=True, timeout=30,
    )


def get_local_hash(repo_dir: str, branch: str) -> str:
    r = git_run(f"rev-parse {branch}", repo_dir)
    return r.stdout.strip()


def get_remote_hash(repo_dir: str, branch: str) -> str:
    git_run("fetch origin", repo_dir)
    r = git_run(f"rev-parse origin/{branch}", repo_dir)
    return r.stdout.strip()


def pull(repo_dir: str, branch: str) -> str:
    """Pull latest changes. Returns new commit hash."""
    r = git_run(f"pull origin {branch}", repo_dir)
    if r.returncode != 0:
        # If local changes conflict, reset to remote
        log.warning("pull failed, resetting to origin/%s", branch)
        git_run(f"reset --hard origin/{branch}", repo_dir)
    return get_local_hash(repo_dir, branch)


def get_commit_log(repo_dir: str, old_hash: str, new_hash: str) -> str:
    r = git_run(f"log --oneline {old_hash}..{new_hash}", repo_dir)
    return r.stdout.strip()


def restart_services() -> None:
    for svc in SERVICES_TO_RESTART:
        log.info("restarting %s", svc)
        subprocess.run(["sudo", "systemctl", "restart", svc],
                       capture_output=True, timeout=30)


def check_and_update(repo_dir: str, branch: str, restart: bool) -> bool:
    """Check for updates and pull if available. Returns True if updated."""
    try:
        local = get_local_hash(repo_dir, branch)
        remote = get_remote_hash(repo_dir, branch)

        if local == remote:
            log.debug("up to date (%s)", local[:8])
            return False

        log.info("update available: %s -> %s", local[:8], remote[:8])
        old_hash = local
        new_hash = pull(repo_dir, branch)
        changes = get_commit_log(repo_dir, old_hash, new_hash)
        log.info("updated:\n%s", changes)

        if restart:
            restart_services()

        return True

    except Exception as e:
        log.error("update check failed: %s", e)
        return False


def run_loop(repo_dir: str, branch: str, interval: int, restart: bool) -> None:
    log.info("watching %s (branch: %s, interval: %ds, restart: %s)",
             repo_dir, branch, interval, restart)

    while True:
        check_and_update(repo_dir, branch, restart)
        time.sleep(interval)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser(description="phingr auto-updater")
    parser.add_argument("--repo-dir", default=DEFAULT_REPO_DIR,
                        help=f"Git repo path (default: {DEFAULT_REPO_DIR})")
    parser.add_argument("--branch", default=DEFAULT_BRANCH,
                        help=f"Branch to track (default: {DEFAULT_BRANCH})")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"Check interval in seconds (default: {DEFAULT_INTERVAL})")
    parser.add_argument("--restart", action="store_true",
                        help="Restart phingr services after update")
    parser.add_argument("--once", action="store_true",
                        help="Check once and exit")
    args = parser.parse_args()

    if args.once:
        updated = check_and_update(args.repo_dir, args.branch, args.restart)
        raise SystemExit(0 if updated else 1)

    run_loop(args.repo_dir, args.branch, args.interval, args.restart)


if __name__ == "__main__":
    main()
