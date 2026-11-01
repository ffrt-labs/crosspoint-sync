# Deploying kosync and the progress endpoint

`deploy/docker-compose.yml` runs two services on the home server:

| Service | Host port | Purpose |
|---|---|---|
| `kosync` (`koreader/kosync:v2.1.1`) | 17200, plain HTTP | Manual Sync Progress from the Xteink, and KOReader clients |
| `progress-endpoint` (built from `endpoint/`) | 17201, container port 8000 | Sleep-time events from the SD plugin ([API](api.md)) |

Everything here is a human step, run on the server. Run the commands from `deploy/`.

## Why these ports skip Caddy

homelab-edge's rule is that Caddy is the only container publishing a LAN port. This
stack deliberately departs from it. The Xteink talks to both services directly over
plain HTTP on the LAN, and Caddy's wildcard route only serves HTTPS on tailnet-only
names, which the device cannot reach. kosync stays on its plain listener for the same
reason, so its 7200 TLS port is not published. The exposure is limited another way:
sync-only credentials, a bind to one chosen address, and no public route.

## Choosing BIND_ADDR

`BIND_ADDR` is the host IP both ports publish on. Compose refuses to run if it is unset
or empty, so there is no accidental `0.0.0.0`.

**Docker-published ports bypass ufw.** Docker installs its own iptables rules, which
forward traffic to the container before ufw's rules see it. A `ufw deny 17200` does
nothing and `ufw status` will not show these ports. `BIND_ADDR` is the access control,
so never set it to `0.0.0.0`, and do not forward 17200 or 17201 on the router.

| Choice | Reachable from | Consequence |
|---|---|---|
| LAN IP | Devices on the LAN | The Xteink works. This is the one to use. |
| Tailscale/NetBird IP | Devices on the overlay | The Xteink does **not** work: it cannot join the overlay. |

There is one address, so to reach the services from the overlay as well, bind the LAN
IP and advertise the LAN as a subnet route (Tailscale) or network route (NetBird).

Use a reserved DHCP lease or a static IP. If the address is missing from the host when
Docker starts, the bind fails and the containers do not come up. This is the main risk
with an overlay IP, whose interface can appear after Docker at boot.

## Bring-up

1. Generate the API key and create the env file:

   ```bash
   cp .env.example .env
   chmod 600 .env
   openssl rand -hex 32
   ```

   Put the key in `PROGRESS_API_KEY` and the address in `BIND_ADDR`. The same key goes
   in the SD plugin's config. It is stored there in plaintext, so use it for nothing
   else.

2. Start the stack and wait for both services to report `healthy`:

   ```bash
   docker compose up -d --build
   docker compose ps
   ```

## Registering the sync-only user

kosync's image enables registration by default. The compose file turns it off, so open
it only for this step.

1. Set `KOSYNC_ENABLE_USER_REGISTRATION=true` in `.env`, then run
   `docker compose up -d kosync`.

2. Register. kosync expects the MD5 of the password as the key, not the password. These
   credentials cross the network over plain HTTP, so make them unique to sync:

   ```bash
   HOST=<BIND_ADDR>
   read -r -p 'Username: ' USERNAME
   read -r -s -p 'Password: ' PASSWORD; echo
   PASSWORD_MD5="$(printf '%s' "$PASSWORD" | openssl md5 | awk '{print $2}')"

   curl -i "http://$HOST:17200/users/create" \
     -H "Accept: application/vnd.koreader.v1+json" \
     -H "Content-Type: application/json" \
     --data "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD_MD5\"}"
   ```

   Expect `201`. A `402` with code 2002 means the user already exists. The username
   cannot contain `:`.

3. Set `KOSYNC_ENABLE_USER_REGISTRATION=false` in `.env`, then run
   `docker compose up -d kosync`. Repeating the `users/create` call should now fail with
   code 2005.

On the device, enter the plain password (CrossPoint computes the MD5 itself), set the
server URL to `http://<BIND_ADDR>:17200` and set Server Type to KoSync.

## Verifying

kosync rejects requests without its versioned `Accept` header, and `/users/auth` reads
the credentials from `x-auth-*` headers, so a bare `curl` does not work. In the shell
from the previous step:

```bash
curl -i "http://$HOST:17200/users/auth" \
  -H "Accept: application/vnd.koreader.v1+json" \
  -H "x-auth-user: $USERNAME" \
  -H "x-auth-key: $PASSWORD_MD5"
```

Expect `200` with `{"authorized":"OK"}`. `x-auth-key` is the MD5, not the password.

Then check the endpoint, and that nothing listens on the wrong address:

```bash
curl -i "http://$HOST:17201/healthz"     # 200 {"status":"ok"}
ss -tln | grep -E ':(7200|17200|17201)\b'  # only BIND_ADDR, and no 7200
```

From a device outside the LAN and overlay, neither port should answer.

### Persistence

Plain `down` keeps named volumes. Never add `-v`, which deletes them.

```bash
docker compose down && docker compose up -d
docker compose ps
```

Once `kosync` is healthy again, repeat the `/users/auth` call. It must still return
`200`, since the user lives only in Redis. To check the endpoint too, compare
`GET /v1/progress` before and after, with `Authorization: Bearer <key>`.

## Backups

`backup.sh` writes a local snapshot of both stores and keeps the newest N (default 7).
Both services must be running.

```bash
./backup.sh --keep 14 /srv/backups/crosspoint-sync
```

Each run creates `<target>/<UTC stamp>/` holding:

- `kosync-redis.tar`: the Redis data directory, archived after a `BGSAVE`. The image
  runs Redis with `appendonly yes`, which loads the AOF on start and ignores `dump.rdb`,
  so a restore needs the whole directory.
- `progress.sqlite3`: a copy from SQLite's backup API, so writes during the backup are
  safe. It passes `integrity_check` before it is accepted.

A failed run exits non-zero, leaves no partial snapshot and prunes nothing. Rotation only
touches directories named exactly like a stamp. If `tar` reports that a file changed
while being read, the run fails; run it again.

If the endpoint's database is not at `/data/progress.db`, set `PROGRESS_DB_PATH` to its
path inside the container.

**Off-box shipping is out of scope.** These snapshots sit on the same machine as the
data, so they protect against bad writes and mistakes but not disk loss. Schedule the
script and copy the target directory elsewhere yourself.

To restore, stop the stack and unpack into the volumes, replacing `<snapshot>` with the
absolute path of a snapshot directory:

```bash
docker compose down
docker run --rm -v crosspoint-sync_kosync_redis:/v -v <snapshot>:/b:ro debian:trixie-slim \
  sh -c 'rm -rf /v/* && tar -C /v -xf /b/kosync-redis.tar'
docker run --rm -v crosspoint-sync_progress_data:/v -v <snapshot>:/b:ro debian:trixie-slim \
  sh -c 'rm -f /v/progress.db* && cp /b/progress.sqlite3 /v/progress.db'
docker compose up -d
```

Rehearse this once before relying on it, then repeat the checks in
[Verifying](#verifying). Check that the container's user can write the restored
database file.
