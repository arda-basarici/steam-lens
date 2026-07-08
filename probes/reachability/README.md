---
title: steam-lens M0 reachability probe
emoji: "\U0001F4E1"
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# steam-lens — datacenter reachability probe (smoke-test milestone, M0)

Answers the milestone's fatal unknown: does Steam's store API answer normally from
a datacenter IP? The probe runs a histogram fetch plus a sequential cursor walk
against `appreviews` and reports per-request status, latency, and the egress IP.
Compare against the residential baseline produced by running `app.py` locally.

Ran via the `M0 reachability probe` GitHub Actions workflow (Azure datacenter IPs).
The original vehicle — this folder as a Docker HF Space, whose config the YAML
header above and the Dockerfile still describe — was repriced behind HF PRO on
2026-07-09 before it ever launched (see REPORT_NOTES); kept because the deployment
milestone (M3) may still land on HF-with-PRO.

Probe, not product — disposable by design once the milestone verdict is recorded.
