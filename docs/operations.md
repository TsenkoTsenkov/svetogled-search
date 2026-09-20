# Operations

Everything about running svetogled-arhiv.com in production: where it lives, how
to reach it, what watches it, and what to do when it breaks.

> This project shares a machine with two others. The machine-wide picture is in
> **[the box index](https://github.com/TsenkoTsenkov/box-ops)** — start there if
> the problem might not be this app.

---

## Where it runs

An on-prem **MacBook Air M1** (16 GB, fanless, 24/7). Not a server, not a VM, not
EC2.

```
~/svetogled-server/
├── app/          ← the LIVE checkout. CI `git reset --hard`s it to the pushed SHA.
├── venv/         python venv (meilisearch client)
├── bin/          pinned meilisearch 1.6.2 binary
├── meili-data/   the search index
├── logs/
└── dumps/
```

**Edit `~/Documents/svetogled-search`, never `~/svetogled-server/app`** — CI
resets the latter hard on every deploy and your changes vanish without a trace.

### Processes

| LaunchAgent | Port | What |
|---|---|---|
| `com.svetogled.app` | 4100 | `search_app.py` |
| `com.svetogled.meilisearch` | 7700 (localhost) | the search index |
| `com.svetogled.monitor` | — | health check every 5 min |

All in the **user** domain, so no sudo:

```bash
launchctl kickstart -k "gui/$(id -u)/com.svetogled.app"
launchctl kickstart -k "gui/$(id -u)/com.svetogled.meilisearch"
```

### How requests actually arrive

```
visitor → Cloudflare edge → tunnel (outbound from the box) → Caddy :443 → :4100
```

1. **DNS**: `svetogled-arhiv.com` is on **Cloudflare** (zone
   `470b02489efec88dbaf6fde9e6f01fc7`). The domain is registered with Amazon
   Registrar in the `tsenko` AWS account, with nameservers pointed at Cloudflare.
2. **Tunnel**: `com.cloudvideo.stream-tunnel`
   (`~/.cloudflared/cvideoo-stream.yml`) — shared with CloudVideo. The apex and
   `www` are both routed; `www` redirects to the apex.
3. **Caddy**: the host Caddy belongs to **cloudvideo-server** and owns `:80`/`:443`
   for the whole machine. It imports `~/caddy-tenants/*.caddy`; our vhost is
   `~/caddy-tenants/svetogled.caddy`, installed and reloaded by `mac/deploy-mac.sh`.

**There are no open ports.** The box dials out to Cloudflare. That is what has
kept this site up through four house-network changes in a month.

> Because Caddy is shared, a CloudVideo deploy that breaks Caddy takes this site
> down too, and vice versa. The monitor's TLS check exists to catch exactly that.

---

## Access

| What | How |
|---|---|
| **Shell** | `ssh tsenko@tsenkos-macbook-air` over Tailscale (install Tailscale, sign in as `tseni.tsenkov@gmail.com`) |
| **Restart a service, no shell** | <https://ops.culconnect.org> — lists `com.svetogled.*` among the rest |
| **Meilisearch** | `http://127.0.0.1:7700` — localhost-bound; reach it over the tailnet or an SSH tunnel. Master key is in `start.sh`. |
| **The site** | <https://svetogled-arhiv.com> |

```bash
# Is the index healthy and populated?
curl -s http://127.0.0.1:7700/health
curl -s -H "Authorization: Bearer <master key>" \
     http://127.0.0.1:7700/indexes/episodes/stats

# Is the app itself up, bypassing Cloudflare and Caddy?
curl -sI http://127.0.0.1:4100/

# Does Caddy hold the cert and the route? (works without hairpin NAT)
curl -sI --resolve svetogled-arhiv.com:443:127.0.0.1 https://svetogled-arhiv.com/
```

---

## Monitoring and alerts

### `~/.svetogled/monitor.sh` — every 5 minutes

LaunchAgent `com.svetogled.monitor`, log `~/.svetogled/monitor.log`, state in
`~/.svetogled/state`.

| # | Check | Self-heals |
|---|---|---|
| 1 | Meilisearch `:7700/health` and the app `:4100` | `launchctl kickstart` |
| 2 | TLS/ingress via `--resolve …:443:127.0.0.1` | no |
| 3 | Route 53 A record vs. the current public IP | UPSERTs the record |
| 4 | Public `https://svetogled-arhiv.com/` | no |
| 5 | Self-hosted runner online | `launchctl kickstart` |
| 6 | New failed CI/CD runs | alerts once per run |

> ⚠️ **Check 3 is obsolete.** The domain moved to Cloudflare on 2026-09-20 and
> the site no longer depends on the public IP at all — it arrives through the
> tunnel. The Route 53 zone still exists but nothing resolves it, so this check
> maintains a record nobody reads and could send a misleading "DDNS updated"
> alert. Safe to delete along with `~/.svetogled/aws.env`.

### Where alerts go

**Telegram, and only Telegram.** The monitor reuses CulConnect's shared
dispatcher (`~/.culconnect/alert.sh`) and its channel config
(`~/.culconnect/monitor.env`). Email, Pushover, ntfy and healthchecks.io are all
coded and all unconfigured. `~/.svetogled/monitor.env` can override per-project
values.

### Alert-suppression trap, inherited from the shared design

The gate is `if prev_state = OK or prev_day ≠ today`. A single permanently-failing
check pins the monitor in `PROBLEM` and silently reduces **every** alert to one a
day. If things go quiet, check `cat ~/.svetogled/state` first.

### From outside the house

`deploy.yml`'s `health` job probes the public URL from `ubuntu-latest` after every
deploy. That is the only genuinely external check — the box cannot reach its own
public address (no hairpin NAT), so a local `curl` proves nothing about
reachability.

### AWS — what does *not* exist

`terraform/` describes an EC2 instance, an EIP, Route 53 records, an SNS topic,
CloudWatch alarms (`instance_down`, `high_memory`, `health_check`) and a Route 53
health check. **None of it is applied.** That is the retired EC2 deployment, kept
for reference. There is no EC2 instance, no alarm and no health check in either
AWS account. Do not go looking for a CloudWatch dashboard for this app — there
isn't one, and the on-box monitor replaced it deliberately.

---

## Deploying

Automatic on push to `main` when the paths filter matches (`transcripts/**`,
`search_app.py`, `theme_scoring.py`, `index.html`, `themes.json`, `static/**`,
`index_to_meili.py`, `mac/**`), or `workflow_dispatch`.

```
test (ubuntu-latest)  →  deploy (self-hosted, this box)  →  health (ubuntu-latest)
```

Manual, on the box:

```bash
cd ~/svetogled-server/app && git fetch origin main && git reset --hard origin/main
bash mac/deploy-mac.sh
```

`deploy-mac.sh` is idempotent: venv → pinned Meilisearch binary → LaunchAgents
(rewritten only when the rendered plist actually changes) → **reindex
Meilisearch `--fresh`** → refresh `~/caddy-tenants/svetogled.caddy` and reload
the shared Caddy → restart the app.

The reindex is a full rebuild, so **a deploy briefly empties search** while it
runs. The site stays up; only search results are missing for a few seconds.

### The runner

`actions.runner.TsenkoTsenkov-svetogled-search.svetogled-macmini`, checkout at
`~/actions-runner-svetogled`. One runner, so deploys serialise —
`concurrency: group: deploy, cancel-in-progress: false`.

---

## When it breaks

Run `~/ops/bin/box-status` first — it shows all three stacks at once.

| Symptom | Likely cause | Fix |
|---|---|---|
| Site 502 | the app died | `launchctl kickstart -k "gui/$(id -u)/com.svetogled.app"` |
| Site loads, search returns nothing | Meilisearch down or index empty | kickstart meilisearch, then `python index_to_meili.py` in the venv |
| Site unreachable, other sites too | shared Caddy, or the tunnel | check `com.cloudvideo.caddy` and `com.cloudvideo.stream-tunnel` |
| TLS error | Caddy tenant file missing after a CloudVideo deploy | rerun `bash mac/deploy-mac.sh` |
| **Only the box** can't reach the site | stale DNS resolver on the box | `networksetup -setdnsservers "Wi-Fi" empty`, then `dig +short svetogled-arhiv.com @8.8.8.8` |
| Weekly transcripts didn't update | expired `YOUTUBE_COOKIES` secret | check the Actions run; refresh the secret |
| Deploy stuck | the single runner is busy or offline | `gh run list`, then kickstart the runner agent |

**Genuine external probe** (~5 s, no API key):

```bash
curl -H 'Accept: application/json' \
  'https://check-host.net/check-http?host=https://svetogled-arhiv.com&max_nodes=6'
# then poll https://check-host.net/check-result/<request_id>
```

## Backups

Worth knowing what is and is not recoverable:

- **Transcripts are in git.** They are the actual content and they are safe.
- **The Meilisearch index is derived** — rebuilt `--fresh` on every deploy, so
  losing `meili-data/` costs nothing.
- **`~/.svetogled/monitor.env`** and the Telegram credentials it inherits are
  **not** in git.
