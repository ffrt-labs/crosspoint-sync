HOME PROGRESS SYNC

When the device sleeps after reading, it sends a summary of the session to your
home server: document hash, start and end progress, duration, and times. The
book path is not sent. Plain LAN only.

INSTALL

Copy to the SD card, in /plugins/home-sync/:
- device.json
- README.md
- config.json, made from config.example.json

In config.json, set:
- server: http://<lan-ip>:<port>, with no trailing slash
- key: the sync-only key from the home server

Config limit: flat JSON, 2 KB.

DEVICE SETUP

1. Settings > Connectivity > Plugins: Enabled.
2. Connect to the home Wi-Fi. The sleep sync joins only the last connected
   network, and needs its saved password.
3. Make sure the device clock is set. Without a trusted time no session is
   recorded.
4. Restart the device. Subscriptions load only at boot, so restart after
   installing the plugin or editing device.json. Editing config.json needs no
   restart.
5. Home > Plugins: check that Home progress sync is listed, with reader.session
   as the event it receives.

USE

Read for at least 10 seconds, turning pages forward. A page counts after 2
seconds on screen. Then sleep the device. It joins Wi-Fi for up to 10 seconds,
sends the session, and shows "Progress synced". Sleep is never blocked: below
20% battery, or if the server is unreachable, it sleeps and retries later.

Sessions wait in events.jsonl in this folder and leave it once delivered. Any
Wi-Fi connection sends them too, including File Transfer, up to 4 per drain.
Reader menu > Sync Progress also connects and sends them. To inspect the queue,
take the SD card to a computer.

"Progress synced" means the server answered, not that it kept the session. A
malformed session is logged by the server and discarded.

LIMITS

Book path limit: 220 bytes. That is the full path on the card. A longer path
can overflow the 512 byte event line, and that session is dropped with no
message on screen. Accented letters take 2 or more bytes, and a double quote
or backslash takes 2. Short paths have a few more bytes of margin.

The queue holds 4 KB, about a dozen sessions. Past that it is emptied and
restarts, so older unsent sessions are lost.

If sync stops, check config.json. A wrong key gets a 401, and a wrong server
gets no answer. Either way sessions stay queued, in order, until it is fixed.

KEY ROTATION

The key is plaintext on the SD card. Use a dedicated sync-only key, and never
expose the server to the internet: certificates are not verified.

To rotate:
1. Change the key on the home server.
2. Put the new key in config.json. No restart needed.
3. Sleep the device, and check that sessions arrive.

Queued sessions are kept in between, and are sent with the new key.

If the card is lost, change the key on the server right away.
