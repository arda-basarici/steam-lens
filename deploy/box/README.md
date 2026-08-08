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
