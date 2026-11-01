#!/usr/bin/env bash
# Tests for deploy/backup.sh, driven through its command line with a stub
# `docker` on PATH. No daemon is touched. The stub answers the same in-container
# commands a real stack would, running the SQLite snapshot with the host's
# python3 against a real database. Run: bash deploy/tests/test_backup.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP="$HERE/../backup.sh"
failures=0

setup() {
	SANDBOX="$(mktemp -d)"
	TARGET="$SANDBOX/target"
	FAKE_REDIS="$SANDBOX/redis"
	FAKE_DATA="$SANDBOX/data"
	CALLS="$SANDBOX/calls.log"
	mkdir -p "$SANDBOX/bin" "$FAKE_REDIS/appendonlydir" "$FAKE_DATA"
	printf 'rdb' >"$FAKE_REDIS/dump.rdb"
	printf 'aof' >"$FAKE_REDIS/appendonlydir/appendonly.aof.1.incr.aof"
	python3 - "$FAKE_DATA/progress.db" <<'PY'
import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.execute("pragma journal_mode=wal")
db.execute("create table sessions (id text)")
db.execute("insert into sessions values ('3fa9c21b-7')")
db.commit()
PY
	cat >"$SANDBOX/bin/docker" <<'STUB'
#!/usr/bin/env bash
# Records each call, then plays the part of `docker compose ... exec -T <svc> <cmd>`.
printf '%s\n' "$*" >>"$CALLS"
while [ $# -gt 0 ] && [ "$1" != exec ]; do shift; done
shift # exec
[ "$1" = -T ] && shift
svc="$1"; shift
case "$svc:$1" in
kosync:redis-cli)
	case "$2 ${3:-}" in
	"LASTSAVE ")
		count=$(cat "$SANDBOX/lastsave" 2>/dev/null || echo 100)
		[ -n "${STUB_LASTSAVE_STUCK:-}" ] || echo $((count + 1)) >"$SANDBOX/lastsave"
		echo "$count" ;;
	"BGSAVE SCHEDULE") echo "Background saving started" ;;
	*) echo "unexpected redis command: $*" >&2; exit 9 ;;
	esac ;;
kosync:tar)
	[ -z "${STUB_TAR_FAILS:-}" ] || { echo "tar broke" >&2; exit 2; }
	tar -C "$FAKE_REDIS" -cf - . ;;
progress-endpoint:python3)
	[ -z "${STUB_SQLITE_FAILS:-}" ] || { echo "no container" >&2; exit 1; }
	python3 -c "$3" "${4/\/data/$FAKE_DATA}" ;;
*) echo "unexpected call: $svc $*" >&2; exit 9 ;;
esac
STUB
	chmod +x "$SANDBOX/bin/docker"
	export SANDBOX CALLS FAKE_REDIS FAKE_DATA
	export PATH="$SANDBOX/bin:$ORIGINAL_PATH"
	unset STUB_LASTSAVE_STUCK STUB_TAR_FAILS STUB_SQLITE_FAILS BACKUP_SAVE_TIMEOUT PROGRESS_DB_PATH
}
ORIGINAL_PATH="$PATH"

run() { OUTPUT="$(bash "$BACKUP" "$@" 2>&1)"; STATUS=$?; }

fail() { echo "  FAIL: $1"; [ -n "${OUTPUT:-}" ] && echo "    output: $OUTPUT"; CASE_FAILED=1; }
assert_status() { [ "$STATUS" -eq "$1" ] || fail "expected exit $1, got $STATUS"; }
assert_output() { [[ "$OUTPUT" == *"$1"* ]] || fail "expected output to mention: $1"; }
# Lists hidden entries too, so a leftover partial directory counts.
snapshots() { find "$TARGET" -mindepth 1 -maxdepth 1 -printf '%f\n' 2>/dev/null | sort; }

check() {
	local name="$1"
	CASE_FAILED=0
	OUTPUT=""
	setup
	echo "- $name"
	"$name"
	[ "$CASE_FAILED" -eq 0 ] || failures=$((failures + 1))
	rm -rf "$SANDBOX"
}

no_target_prints_usage() {
	run
	assert_status 2
	assert_output "usage:"
}

extra_argument_is_rejected() {
	run "$TARGET" surplus
	assert_status 2
	assert_output "usage:"
}

unknown_option_is_rejected() {
	run --nope "$TARGET"
	assert_status 2
	assert_output "usage:"
}

keep_must_be_a_positive_integer() {
	for bad in 0 -1 x ""; do
		run --keep "$bad" "$TARGET"
		assert_status 2
		assert_output "--keep"
	done
	run "$TARGET" --keep
	assert_status 2
	[ ! -s "$CALLS" ] || fail "docker was called despite bad arguments"
}

snapshot_holds_redis_data_and_a_readable_database() {
	run "$TARGET"
	assert_status 0
	local snap
	snap="$TARGET/$(snapshots | head -1)"
	[[ "$(basename "$snap")" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || fail "snapshot name is not a UTC stamp: $snap"
	tar -tf "$snap/kosync-redis.tar" | grep -q 'dump.rdb' || fail "redis archive lacks dump.rdb"
	tar -tf "$snap/kosync-redis.tar" | grep -q 'appendonlydir/' || fail "redis archive lacks the AOF, the only thing Redis loads with appendonly on"
	[ "$(python3 -c 'import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute("select id from sessions").fetchone()[0])' "$snap/progress.sqlite3")" = 3fa9c21b-7 ] \
		|| fail "sqlite snapshot does not hold the committed row"
}

redis_is_saved_before_it_is_archived() {
	run "$TARGET"
	local save tar
	save="$(grep -n 'BGSAVE' "$CALLS" | cut -d: -f1)"
	tar="$(grep -n ' tar ' "$CALLS" | cut -d: -f1)"
	[ -n "$save" ] && [ -n "$tar" ] && [ "$save" -lt "$tar" ] || fail "BGSAVE must precede tar"
	[ "$(grep -c LASTSAVE "$CALLS")" -ge 2 ] || fail "must wait for LASTSAVE to advance"
}

commands_run_against_this_stack_without_a_tty() {
	(cd / && bash "$BACKUP" "$TARGET" >/dev/null 2>&1)
	grep -q -- "compose --project-directory $(cd "$HERE/.." && pwd) -f $(cd "$HERE/.." && pwd)/docker-compose.yml exec -T kosync" "$CALLS" \
		|| fail "compose must be pinned to deploy/ whatever the cwd"
}

db_path_can_be_overridden() {
	mv "$FAKE_DATA/progress.db" "$FAKE_DATA/other.sqlite3"
	PROGRESS_DB_PATH=/data/other.sqlite3 run "$TARGET"
	assert_status 0
}

missing_database_fails_rather_than_creating_an_empty_one() {
	rm "$FAKE_DATA"/progress.db*
	run "$TARGET"
	assert_status 1
	[ ! -e "$FAKE_DATA/progress.db" ] || fail "the backup created a database"
}

rotation_keeps_the_newest_snapshots() {
	mkdir -p "$TARGET"/2026010{1,2,3}T000000Z
	run --keep 2 "$TARGET"
	assert_status 0
	[ "$(snapshots | wc -l)" -eq 2 ] || fail "expected 2 snapshots, have: $(snapshots | tr '\n' ' ')"
	[ -d "$TARGET/20260103T000000Z" ] || fail "the newest older snapshot should survive"
	[ ! -d "$TARGET/20260101T000000Z" ] || fail "the oldest snapshot should be gone"
}

rotation_defaults_to_seven() {
	mkdir -p "$TARGET"/2026010{1..9}T000000Z
	run "$TARGET"
	assert_status 0
	[ "$(snapshots | wc -l)" -eq 7 ] || fail "expected 7 snapshots"
}

rotation_leaves_everything_else_alone() {
	mkdir -p "$TARGET/20260101T000000Z" "$TARGET/keep-me"
	touch "$TARGET/20260101T000000Z.note"
	run --keep 1 "$TARGET"
	assert_status 0
	[ -d "$TARGET/keep-me" ] && [ -e "$TARGET/20260101T000000Z.note" ] || fail "rotation touched files it does not own"
	[ ! -d "$TARGET/20260101T000000Z" ] || fail "the old snapshot should be gone"
}

assert_failed_run_changed_nothing() {
	[ "$STATUS" -ne 0 ] || fail "expected a non-zero exit"
	[ "$(snapshots | tr '\n' ' ')" = "20260101T000000Z " ] || fail "failed run left: $(snapshots | tr '\n' ' ')"
}

failed_redis_archive_keeps_old_snapshots_and_no_partial() {
	mkdir -p "$TARGET/20260101T000000Z"
	STUB_TAR_FAILS=1 run --keep 1 "$TARGET"
	assert_failed_run_changed_nothing
}

failed_sqlite_copy_keeps_old_snapshots_and_no_partial() {
	mkdir -p "$TARGET/20260101T000000Z"
	STUB_SQLITE_FAILS=1 run --keep 1 "$TARGET"
	assert_failed_run_changed_nothing
}

stuck_redis_save_times_out() {
	mkdir -p "$TARGET/20260101T000000Z"
	STUB_LASTSAVE_STUCK=1 BACKUP_SAVE_TIMEOUT=1 run --keep 1 "$TARGET"
	assert_failed_run_changed_nothing
	assert_output "did not finish saving"
}

check no_target_prints_usage
check extra_argument_is_rejected
check unknown_option_is_rejected
check keep_must_be_a_positive_integer
check snapshot_holds_redis_data_and_a_readable_database
check redis_is_saved_before_it_is_archived
check commands_run_against_this_stack_without_a_tty
check db_path_can_be_overridden
check missing_database_fails_rather_than_creating_an_empty_one
check rotation_keeps_the_newest_snapshots
check rotation_defaults_to_seven
check rotation_leaves_everything_else_alone
check failed_redis_archive_keeps_old_snapshots_and_no_partial
check failed_sqlite_copy_keeps_old_snapshots_and_no_partial
check stuck_redis_save_times_out

if [ "$failures" -ne 0 ]; then
	echo "$failures test(s) failed"
	exit 1
fi
echo "all passed"
