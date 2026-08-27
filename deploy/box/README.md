# Deploying steam-lens to the box

The box is operated from the **platform** repository
(github.com/arda-basarici/platform): host provisioning, the shared Caddy
proxy, the origin firewall, TLS, and the nightly backup all live there
(`box/README.md` for the host and proxy, `projects/steamlens/README.md` for
this tenant's stanza, backup, and restore drill). This directory holds what
the application itself owns: its deployment entrypoint (`deploy.sh`, the
only command the CI ssh key may run) and its application secrets
(`secrets.enc.env`).

## What moved, and where (2026-08-27)

Until 2026-08-27 this directory carried the whole box layer, because
steam-lens was the box's first tenant and the provision-as-code had to live
somewhere. When a second tenant arrived the layer was extracted into the
platform repository and cut over live; the copies here became a liability
(an edit to them would change nothing on the box while looking as if it
did), so they were removed. The git history before that date still shows
them, and the platform repository's DESIGN tells the extraction story.

| Was here | Lives now (platform repo) |
|---|---|
| `Caddyfile` (global config + the steamlens stanza) | `box/Caddyfile` + `projects/steamlens/sites.caddy` |
| `compose.yaml` (the proxy stack) | `box/compose.yaml` |
| `firewall.sh`, `box-firewall.service` | `box/` |
| `backup.sh`, `steamlens-backup.service`, `steamlens-backup.timer` | `projects/steamlens/` |
| `BACKUP_PING_URL` (was a line in `secrets.enc.env`) | `projects/steamlens/backup.enc.env` → `/etc/platform/steamlens/backup.env` on the box |
| the provisioning / hardening / firewall / TLS / backup runbook sections | `box/README.md`, `projects/steamlens/README.md` |

## Layout on the box

The host layout (`/srv/platform` for the checkout the proxy and firewall run
from, `/etc/platform` for machine-local material such as the Origin CA pair
and decrypted env files, `/srv/<project>` per tenant) is drawn in the
platform repository's `box/README.md`. The one fact the application owns:
`/srv/steamlens/data/` is the bind-mounted state. It outlives every image
and container, and the nightly backup reads it from the host without
entering Docker. Owned by uid 1000 (the login user; the image runs as the
same uid by convention).

## Deploying a new version

CI builds and pushes `ghcr.io/arda-basarici/steam-lens:latest` plus a sha
tag on every green push to main (the `image` job in
`.github/workflows/ci.yml` — gated on the check job, so a red commit never
mints a `latest`). The deploy then rides the pipeline: the `deploy` job
pauses at the `production` environment's required review, and approving it
ssh's into the box over a forced-command key that can run
`/srv/steamlens/deploy.sh` (this directory's `deploy.sh`) and nothing else.
The script refuses while an analysis job is live (re-run the job once it
settles), pulls the run's own sha — so a late approval ships exactly what
was reviewed, immune to `:latest` moving underneath — retags the box's
`latest` to mean "last approved deploy", recreates, and polls `/healthz`
through the visitor path before the job may go green.

One-time CD setup (replayed for a rebuilt box): install the script
(`scp deploy/box/deploy.sh steamlens:/srv/steamlens/deploy.sh` + `chmod +x`),
mint a dedicated keypair (`ssh-keygen -t ed25519 -N "" -C
steamlens-ci-deploy`), append
`restrict,command="/srv/steamlens/deploy.sh" <pubkey>` to the box user's
`~/.ssh/authorized_keys`, and fill the GitHub `production` environment:
a required reviewer plus secrets `DEPLOY_SSH_KEY` (the private key),
`DEPLOY_HOST_KEY` (the `ssh-keyscan -t ed25519 <origin-ip>` line), and
`DEPLOY_TARGET` (`<user>@<origin-ip>`). Delete the local pair after
pasting — the secret store holds the only copy, and re-minting is one
command. The box's address stays in secrets, never this repo.

Fallback (pipeline down, or a deliberately manual moment) — rollback is
pointing the compose file at the previous sha tag:

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
that has the alias, delete it after). A PowerShell pipe between native
commands (`wsl sops -d … | ssh …`) adds CRLF: strip it on the far side
(`tr -d ""` before the `cat >`) and verify with
`tr -cd "" < /srv/steamlens/.env | wc -c` → `0`. A stray `` at the end
of a value silently breaks its consumer (measured 2026-08-27: the box's
`.env` carried three).

Adding the box as its own decryptor (an age key on the box as a second
recipient) is a platform-level decision, recorded with the recipient policy
in the platform repository's `SECRETS.md`.
