#!/bin/sh
# The pipeline's deploy hand — the ONLY thing the CI deploy key may run.
# Installed at /srv/steamlens/deploy.sh; the key's authorized_keys entry is
# `restrict,command="/srv/steamlens/deploy.sh"`, so the key gets no shell,
# no forwarding, and no other command, ever. Approval already happened in
# GitHub (the `production` environment gate) by the time this runs.
#
# Refuses while an analysis job is live: a deploy recreates the app
# container, which would cut a visitor's minutes-long, money-spending job
# mid-run. The refusal names the job in the Actions log; re-run the deploy
# job once it finishes.

set -eu

IMAGE=ghcr.io/arda-basarici/steam-lens
DB="file:/srv/steamlens/data/serve.db?mode=ro"

# The forced command ignores what the client asked to run, but sshd hands it
# over verbatim — the pipeline sends "deploy <short-sha>" and the sha is
# validated to a bare hex tag before use. Deploying the pipeline's own sha
# rather than :latest closes the approval-lag race: approve tonight and you
# ship what you approved, not whatever a later push re-pointed latest at.
case "${SSH_ORIGINAL_COMMAND:-}" in
    "deploy "*) sha=${SSH_ORIGINAL_COMMAND#deploy } ;;
    *) echo "REFUSED: expected 'deploy <short-sha>'"; exit 1 ;;
esac
echo "$sha" | grep -Eq '^[0-9a-f]{7,40}$' \
    || { echo "REFUSED: '$sha' is not a sha tag"; exit 1; }

# finished_at IS NULL marks a live job — or a process-death orphan, which
# stays NULL forever (the schema documents this), so only rows younger than
# 30 minutes count; real jobs settle in single-digit minutes. The strftime
# shape mirrors the store's utc_isoformat text ('T' separator, +00:00), so
# string order is time order against the stored column.
live=$(sqlite3 "$DB" \
    "SELECT requested_name || ' (app ' || app_id || '), running since ' || started_at
     FROM jobs
     WHERE finished_at IS NULL
       AND started_at > strftime('%Y-%m-%dT%H:%M:%f000+00:00','now','-30 minutes')")

if [ -n "$live" ]; then
    echo "REFUSED: a live analysis would be cut by this deploy:"
    echo "  $live"
    echo "Re-run the deploy job once it finishes (jobs run a few minutes)."
    exit 1
fi

cd /srv/steamlens
docker pull --quiet "$IMAGE:$sha"
# The box's :latest means "last approved deploy" — retagged locally so the
# compose file (which tracks latest) starts exactly the approved image.
docker tag "$IMAGE:$sha" "$IMAGE:latest"
docker compose up -d

# Not done until the app answers from inside the new container — through
# Caddy on the published 443, the same path visitors ride (--resolve pins
# SNI to loopback; -k because the Origin CA pair is trusted only by
# Cloudflare's edge, which is its one job).
attempts=0
until health=$(curl -skf --max-time 5 \
        --resolve steamlens.ardabasarici.dev:443:127.0.0.1 \
        https://steamlens.ardabasarici.dev/healthz); do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge 10 ]; then
        echo "DEPLOY FAILED: healthz never answered after up -d"
        echo "Rollback: point compose.yaml at the previous sha tag (README runbook)."
        exit 1
    fi
    sleep 3
done
echo "healthz: $health"
echo "deployed: $(docker image inspect -f '{{index .RepoDigests 0}}' "$IMAGE:$sha")"
