# The box — provisioning and deploy

One small VPS runs every project as a self-contained Docker Compose stack
behind a single box-owned Caddy (this directory), all joined by one shared
Docker network. A new project lands as: its own compose file + one Caddyfile
stanza. Nothing here is box-specific — a rebuilt box replays this file.

## One-time host provisioning

```sh
# Docker Engine + compose plugin, per docs.docker.com/engine/install/debian
# (apt repo, not the distro package — the distro's lags majors behind).
sudo apt-get update && sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

# Run docker as the login user (re-log to take effect).
sudo usermod -aG docker $USER

# The one shared proxy network every project stack joins.
docker network create web
```

## Hardening — verify, then fix only what fails

A fresh provider image may already ship most of this (the 2026-08-08 box did:
ssh key-only, ufw active, unattended-upgrades wired). Verify the actual state
first; change only what a check refutes.

```sh
# ssh: key-only, no root login. sshd -T prints the *effective* config with
# /etc/ssh/sshd_config.d/ drop-ins resolved — grepping sshd_config alone can lie.
sudo sshd -T | grep -Ei '^(passwordauthentication|permitrootlogin|kbdinteractiveauthentication)'
# Want all three "no". If not, fix via a drop-in (never edit sshd_config itself),
# and keep the current session open while testing a fresh login:
#   printf 'PasswordAuthentication no\nPermitRootLogin no\nKbdInteractiveAuthentication no\n' \
#     | sudo tee /etc/ssh/sshd_config.d/50-hardening.conf && sudo systemctl reload ssh

# Firewall: default deny incoming, allow only ssh + web. Allow 22 BEFORE enable,
# while the session that would be locked out is still open.
sudo ufw allow 22/tcp comment 'ssh'
sudo ufw allow 80/tcp comment 'HTTP - Caddy'
sudo ufw allow 443/tcp comment 'HTTPS - Caddy'
sudo ufw enable

# Security patches auto-install; the timers must show a next-fire time.
sudo apt-get install -y unattended-upgrades
systemctl list-timers 'apt-daily*' --all
```

Known trap, respected structurally rather than fixed: **Docker-published ports
bypass ufw** — Docker's iptables rules sit ahead of ufw's chains, so a
published port is world-reachable no matter what ufw says. The 80/443 rules
above document intent; what actually guards the box is the compose convention
that only the box proxy ever publishes a port. Check the live surface with
`docker ps --format 'table {{.Names}}\t{{.Ports}}'`: only the Caddy container
may show `0.0.0.0->` arrows.

## Domain + TLS (Cloudflare, orange-cloud)

`steamlens.ardabasarici.dev` fronts the box through Cloudflare's proxy. The
DNS A record is **proxied and must stay proxied** — a grey-cloud save, even
briefly, puts the origin IP into passive-DNS archives permanently, and the
origin-hiding half of the proxy dies retroactively.

The visitor→Cloudflare leg rides Cloudflare's edge certificate; the
Cloudflare→origin leg runs SSL mode **Full (strict)** against a Cloudflare
Origin CA pair at `/srv/box-proxy/certs/` (dashboard → SSL/TLS → Origin
Server; covers the apex + `*.ardabasarici.dev`, 15-year validity). The pair
is trusted only by Cloudflare's edge — exactly its job — and is re-issuable
from the dashboard at any time, so the box-side files are the whole story:
never committed, nothing to back up.

Two Caddyfile pieces make the proxy honest (both explained in place there):
`trusted_proxies` lists Cloudflare's published ranges (cloudflare.com/ips —
refresh the list if Cloudflare ever announces a change) so a forwarded
identity is only believed when the peer really is Cloudflare, and the domain
stanza *replaces* `X-Forwarded-For` with the one verified visitor IP,
preserving the app's last-entry contract (`serve/gate.py`). The `:80`
bare-IP stanza is transitional — it retires at the edge-hardening step.

## Layout on the box

```
/srv/box-proxy/    ← this directory (compose.yaml + Caddyfile), box-owned
/srv/<project>/    ← one directory per project: its compose.yaml, .env, data/
```

`/srv/<project>/data/` is the bind-mounted state — it outlives every image
and container, and the nightly backup reads it from the host without
entering Docker. Owned by uid 1000 (the login user; images run as the same
uid by convention).

## Bring-up

```sh
# The proxy, once per box:
cd /srv/box-proxy && docker compose up -d

# A project (steamlens shown); images come from GHCR — the box never builds:
cd /srv/steamlens && docker compose pull && docker compose up -d
```

## Deploying a new version

CI builds and pushes `ghcr.io/arda-basarici/steam-lens:latest` on every green
push to main (the `image` job in `.github/workflows/ci.yml` — gated on the
check job, so a red commit never mints a `latest`). Rolling the box forward
is a pull —
rollback is pointing the compose file at the previous sha tag:

```sh
cd /srv/steamlens && docker compose pull && docker compose up -d
```

## Secrets (SOPS + age)

Secrets live encrypted *in the repo* as `deploy/box/secrets.enc.env`,
encrypted with SOPS (github.com/getsops/sops) to an age
(age-encryption.org) key. SOPS encrypts the values and leaves the keys
readable, so the file is safe to commit and a diff shows *which* secret
changed, never the plaintext. Decryption happens only on the admin
workstation — the box holds no age key, so a compromised box yields the one
plaintext `.env` it already runs, never the key to the secrets history.

Workstation prerequisites: `age` and `sops` installed, the private key at
`~/.config/sops/age/keys.txt` (**backed up off-machine** — losing it makes the
encrypted file unrecoverable), and the recipients declared in `.sops.yaml` at
the repo root.

Edit a secret (rotate the key, add a variable) — opens the decrypted values in
`$EDITOR`, re-encrypts on save:

```sh
sops deploy/box/secrets.enc.env
```

Push the current secrets to the box (after an edit, or to provision a fresh
box) — decrypt on the workstation, write the box's `.env`, restart:

```sh
sops -d deploy/box/secrets.enc.env | \
  ssh steamlens 'cat > /srv/steamlens/.env && chmod 600 /srv/steamlens/.env \
    && cd /srv/steamlens && docker compose up -d'
```

The `steamlens` alias lives in the workstation's `~/.ssh/config`. If `sops`
and `ssh` sit in different environments (e.g. `sops` in WSL, the ssh alias in
Windows), either add the alias to the sops environment, or bridge with a temp
file on a shared path (`sops -d … > /mnt/c/…/env.tmp`, `scp` it from the side
that has the alias, delete it after).

Add the box as its own decryptor (optional, later): generate an age key on the
box, add its public key as a second `age:` recipient in `.sops.yaml`, run
`sops updatekeys deploy/box/secrets.enc.env`, and the box decrypts at deploy
without the workstation in the loop.

## Backups (nightly, to Google Drive)

The app's whole durable state is one SQLite file — `/srv/steamlens/data/serve.db`
(response archive, ledger, journals, reports). `backup.sh` snapshots it with
`sqlite3 .backup`, integrity-checks the snapshot before shipping, gzips, uploads
to Drive, and prunes to 7 dailies + 4 Sunday weeklies. A systemd timer
(`steamlens-backup.timer`, 03:30 box-local, `Persistent=true`) drives it; on
success
the script pings a healthchecks.io check, so the alert channel is *silence* —
script failure, dead timer, and dead box all raise the same email. Secrets are
deliberately not backed up: `.env` regenerates from the SOPS file in the repo,
so a compromised Drive account holds review data, never keys.

### One-time setup

```sh
# 1. On the box: the two tools the script calls.
sudo apt-get install -y sqlite3 rclone

# 2. On the box, as the login user: the Drive remote. Name it `gdrive`
#    (backup.sh addresses it by that name), pick storage type `drive`, and set
#    scope `drive.file` — the token can then only touch files rclone itself
#    created; a compromised box can burn the backups, never read the Drive.
#    Skip client_id/secret (rclone's built-in is fine at this volume, and a
#    self-made "testing"-mode OAuth app expires its token every 7 days).
#    The box is headless: answer "n" to auto config, run the printed
#    `rclone authorize "drive" ...` line on the workstation, paste the token.
rclone config

# 3. Create a check at healthchecks.io (period 1 day, grace ~2 h), then put
#    its ping URL into the secrets file and push (see Secrets above):
#    sops deploy/box/secrets.enc.env   → add BACKUP_PING_URL=https://hc-ping.com/<uuid>

# 4. From the workstation: install script + units, enable the timer.
scp deploy/box/backup.sh steamlens:/srv/steamlens/backup.sh
scp deploy/box/steamlens-backup.{service,timer} steamlens:/tmp/
ssh steamlens 'chmod +x /srv/steamlens/backup.sh \
  && sudo mv /tmp/steamlens-backup.service /tmp/steamlens-backup.timer /etc/systemd/system/ \
  && sudo systemctl daemon-reload && sudo systemctl enable --now steamlens-backup.timer'

# 5. First run, by hand, watching the journal:
ssh steamlens 'sudo systemctl start steamlens-backup.service \
  && journalctl -u steamlens-backup.service -n 20 --no-pager'
```

Setup is not done until a restore has been verified — a backup never restored
is a hope. Pull the fresh backup back and compare it against the live db:

```sh
ssh steamlens
rclone copyto "gdrive:steamlens-backups/daily/serve-$(date +%F).db.gz" /tmp/restore.db.gz
gunzip /tmp/restore.db.gz
sqlite3 /tmp/restore.db "PRAGMA integrity_check;"          # → ok
sqlite3 /tmp/restore.db "SELECT count(*) FROM classify_cache;"
sqlite3 "file:/srv/steamlens/data/serve.db?mode=ro" \
  "SELECT count(*) FROM classify_cache;"                   # → same count (± writes since 03:30)
rm /tmp/restore.db
```

### Restoring for real (disaster runbook)

```sh
cd /srv/steamlens && docker compose down
rclone lsl gdrive:steamlens-backups/daily                  # pick the newest good one
rclone copyto gdrive:steamlens-backups/daily/serve-<date>.db.gz /tmp/restore.db.gz
gunzip /tmp/restore.db.gz && sqlite3 /tmp/restore.db "PRAGMA integrity_check;"
mv data/serve.db data/serve.db.broken                      # keep the evidence
rm -f data/serve.db-wal data/serve.db-shm                  # stale WAL sidecars poison a restored db
mv /tmp/restore.db data/serve.db
docker compose up -d && curl -s http://localhost:80/healthz
```
