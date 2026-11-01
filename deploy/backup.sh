#!/usr/bin/env bash
# Consistent local snapshot of the kosync Redis data and the progress endpoint's
# SQLite database, with rotation. Off-box shipping is out of scope: see
# docs/deploy.md. Both services must be running.
#
#   backup.sh [--keep N] TARGET_DIR
#
# Each run writes TARGET_DIR/<UTC stamp>/{kosync-redis.tar,progress.sqlite3}, then
# keeps the newest N stamped directories (default 7). A failed run exits non-zero,
# leaves no snapshot behind and prunes nothing.
#
# Environment:
#   BACKUP_SAVE_TIMEOUT  seconds to wait for Redis to finish saving (default 60)
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH=/data/progress.db
SAVE_TIMEOUT="${BACKUP_SAVE_TIMEOUT:-60}"

# Runs inside the endpoint container, which has Python but no sqlite3 CLI. The
# backup API gives a consistent copy under live writes, including any WAL content.
# mode=ro stops a wrong path from creating an empty database that looks like success.
SQLITE_SNAPSHOT='
import pathlib, shutil, sqlite3, sys, tempfile, urllib.parse
source = sqlite3.connect("file:" + urllib.parse.quote(sys.argv[1]) + "?mode=ro", uri=True)
with tempfile.TemporaryDirectory() as tmp:
    copy_path = pathlib.Path(tmp) / "copy.sqlite3"
    copy = sqlite3.connect(copy_path)
    source.backup(copy)
    verdict = copy.execute("pragma integrity_check").fetchone()[0]
    copy.close()
    if verdict != "ok":
        sys.exit("integrity_check failed: " + verdict)
    with copy_path.open("rb") as stream:
        shutil.copyfileobj(stream, sys.stdout.buffer)
'

usage() {
	echo "usage: backup.sh [--keep N] TARGET_DIR" >&2
	exit 2
}

keep=7
target=""
while [ $# -gt 0 ]; do
	case "$1" in
	--keep)
		[ $# -ge 2 ] || { echo "--keep needs a value" >&2; usage; }
		keep="$2"
		shift 2
		;;
	-*) usage ;;
	*)
		[ -z "$target" ] || usage
		target="$1"
		shift
		;;
	esac
done
[ -n "$target" ] || usage
[[ "$keep" =~ ^[1-9][0-9]*$ ]] || { echo "--keep must be a positive integer" >&2; usage; }

compose() {
	docker compose --project-directory "$DEPLOY_DIR" -f "$DEPLOY_DIR/docker-compose.yml" "$@"
}

# The image's redis.conf has `appendonly yes`, so on start Redis loads the AOF and
# ignores dump.rdb. The archive therefore takes the whole data directory: BGSAVE
# refreshes dump.rdb as a portable copy, and the AOF is what a restore comes up from.
snapshot_redis() {
	local before deadline
	before="$(compose exec -T kosync redis-cli LASTSAVE)"
	# LASTSAVE has one-second resolution; a save in this same second would not move it.
	sleep 1
	compose exec -T kosync redis-cli BGSAVE SCHEDULE >/dev/null
	deadline=$((SECONDS + SAVE_TIMEOUT))
	until [ "$(compose exec -T kosync redis-cli LASTSAVE)" -gt "$before" ] 2>/dev/null; do
		if [ "$SECONDS" -ge "$deadline" ]; then
			echo "Redis did not finish saving within ${SAVE_TIMEOUT}s" >&2
			return 1
		fi
		sleep 1
	done
	compose exec -T kosync tar -C /var/lib/redis -cf - . >"$1/kosync-redis.tar"
}

snapshot_sqlite() {
	compose exec -T progress-endpoint python3 -c "$SQLITE_SNAPSHOT" "$DB_PATH" >"$1/progress.sqlite3"
}

# Only exact stamp directories are candidates: anything else in the target stays.
prune() {
	local entry stamps=()
	for entry in "$target"/*; do
		[[ "$(basename "$entry")" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] && [ -d "$entry" ] && stamps+=("$entry")
	done
	local excess=$((${#stamps[@]} - keep)) i
	for ((i = 0; i < excess; i++)); do
		rm -rf -- "${stamps[$i]}"
	done
}

mkdir -p "$target"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
snapshot="$target/$stamp"
partial="$(mktemp -d "$target/.partial-XXXXXX")"
trap 'rm -rf "$partial"' EXIT

snapshot_redis "$partial"
snapshot_sqlite "$partial"
chmod 755 "$partial"
mv -T "$partial" "$snapshot"
prune
echo "snapshot written: $snapshot"
