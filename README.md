# Constantinople Station

A fleet of AI agents running small online shops, shown as a pixel-art space station. Two parts:

- **`dashboard/`** — the station map. One HTML file, no build step. Click a bay to open its terminal; ARCHIVE, LEDGER, CREW and BRIDGE tabs at the bottom. On its own it runs a simulated economy (amber *DEMO MODE* pill). Connected to the engine it renders real runs, sales and costs (*LIVE ENGINE* pill).
- **`constantinople/`** — the engine. Each bay is a YAML workflow; the orchestrator keeps them on schedule, every step and dollar is written to a SQLite ledger, and a server streams events to the map and takes bridge commands back.

## The Prime Mission

Every agent on board works toward one number: **$1,000,000,000,000 banked.** The route is ten waypoints, each ten times the last (First Light $1K → Ember Reach $10K → Meridian Gate $100K → Sable Crossing $1M → Bosphorus Deep $10M → The Verge $100M → Aurum Belt $1B → Cold Harbor $10B → Last Lantern $100B → Trillion Dawn $1T). The MISSION tab draws the ship's position on that route, with velocity (revenue per sol), ETA to the next waypoint and to Trillion Dawn, the velocity a ten-year arrival would need, and how many doublings remain. The Core reviews the mission every cycle and publishes one standing directive to the crew (`prompts/mission_review.md`); the doctrine every agent runs under carries the mission state. Set `MISSION_TARGET` in `.env` to change the destination.

## MOTHER

MOTHER is the overseer. The crew reports to her; she reports to you, the Creator (`CREATOR` in `.env`). She:

- reads every incident and triages it on her own authority (`prompts/mother_triage.md`): retry with backoff, hold a bay and lift it after review, send Research for a fresh brief when a design is too close to something existing, wake a standby bay, or escalate;
- decides approval gates herself when `AUTONOMY=full`: spend gates while today's spend stays under `DAILY_SPEND_CAP`, publish gates when doctrine checks pass. With `AUTONOMY=assist` (the default) every gate waits for you;
- sweeps every five minutes for stalled bays and raises incidents on them;
- reviews the mission every Core cycle and publishes the standing directive the whole crew works under.

Everything she does is an event with her name on it (`kind: mother`). `GET /mother` shows her recent decisions, today's spend against the cap, and anything she has escalated to you. Escalations sit in `/approvals` with gate `escalation`; clear them with `python -m constantinople approve <id>` once you've looked.

## Running 24/7

The engine is a single long-running process; two scripts keep it alive.

**Windows** — from the `engine` folder in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1
```

That registers a scheduled task that starts the station when you log in, restarts it within a minute if it stops, and runs it hidden in the background. The dashboard is at http://127.0.0.1:8787 whenever the PC is on. Stop it with `Stop-ScheduledTask -TaskName "Constantinople Station"`, remove it with the `Unregister-ScheduledTask` line printed by the installer. To watch it in a window instead, run `.\start-station.ps1`.

**Mac/Linux** — `./start-station.sh` restarts on crash; for boot-time start wrap it in a launchd plist (Mac) or a systemd unit (Linux).

**On a server (recommended)** — one line on a fresh Ubuntu machine, as root:

```bash
curl -fsSL https://raw.githubusercontent.com/REPO_OWNER/constantinople-station/main/deploy.sh | bash
```

It asks four questions (station name, your name, Mother's autonomy, daily cap), installs everything under `/opt/constantinople`, locks the firewall to SSH + Tailscale, and registers a `constantinople` service that restarts on crash and on reboot. Afterwards: `bash /opt/constantinople/station.sh status|logs|approvals|approve N|env`, and `bash /opt/constantinople/update.sh` to pull new code.

**Truly 365** means the machine stays on. A laptop that sleeps is not a ship. The cheapest always-on option is a small Linux VPS ($5–10/month): copy the `engine` folder there, `pip install -r requirements.txt`, run it under systemd, and open the dashboard through an SSH tunnel (`ssh -L 8787:127.0.0.1:8787 user@host`) so it is never exposed to the internet.

For unattended running set `AUTONOMY=full` and a `DAILY_SPEND_CAP` you are comfortable losing on a bad day. Mother will handle everything inside those limits and park the rest in escalations for when you check in.

## Where the money comes from (and where it doesn't)

In dry run, `tools/etsy.poll_receipts` and `tools/fiverr.poll_inbox` **invent** sales and orders so the whole ship can be exercised. The dashboard marks these figures SIMULATED. A real dollar enters the ledger in exactly three ways: Etsy's receipts API (needs `ETSY_ACCESS_TOKEN`, `DRY_RUN=false`), an order posted to `/inbound/order` that the Studio delivers, or a sale you post to `/inbound/sale`. Nothing else can create revenue. If the number on the HUD is not backed by one of those, it is not real.

## Make it yours

`STATION_NAME` and `CALLSIGN` in `.env` name the ship on the HUD, the boot screen and every mission log line. The BRIDGE tab's setup checklist reads the engine and shows which integrations are configured, so you can see exactly what is left to plug in.

## Run it in two minutes

```bash
cd engine
python3 -m venv .venv && source .venv/bin/activate     # optional
pip install -r requirements.txt
cp .env.example .env            # defaults: DRY_RUN=true, nothing spends money
python -m constantinople serve         # http://127.0.0.1:8787
```

Open http://127.0.0.1:8787 — the dashboard served from the engine auto-connects to the live stream. In another terminal:

```bash
python -m constantinople order --niche "true crime" --qty 3 --amount 105    # hand the Thumbnail Studio an order
python -m constantinople message "Does the mug ship to Canada?"             # hand the Comms Deck a message
python -m constantinople approvals                                          # what is waiting on you
python -m constantinople approve 1                                          # let it spend / publish
python -m constantinople tail                                               # watch the event stream in the terminal
python -m constantinople once etsy                                          # run one bay in the foreground
```

Set `SPEED=50` in `.env` to watch everything happen fast while you test. `SPEED=1` is the real schedule.

## How a bay works

`bays/02_etsy.yaml`:

```yaml
id: etsy
name: ETSY PRODUCTION BAY
agents: [FORGE, MINT, PRESS]
cadence_seconds: 5400            # a listing every 90 minutes
steps:
  - {id: trend_scan,    name: Trend scan,    kind: agent, agent: FORGE, prompt: etsy_trend.md}
  - {id: design_draft,  name: Design draft,  kind: tool,  tool: images.generate, args: {prompt_from: trend_scan.design_prompt, n: 4}}
  - {id: mockup_build,  name: Mockup build,  kind: tool,  tool: printify.create_product, gate: approve_spend}
  - {id: listing_draft, name: Listing draft, kind: agent, agent: MINT, prompt: etsy_listing.md}
  - {id: pub_sync,      name: Pub sync,      kind: tool,  tool: printify.publish, gate: approve_publish, emit: publish}
  - {id: ledger,        name: Ledger,        kind: noop}
```

- **`kind: agent`** runs a prompt from `prompts/` against the model as a named crew member and expects JSON back. Token usage is costed with `PRICES` in `config.py`. No API key → canned output.
- **`kind: tool`** calls a function in `constantinople/tools/`. Each tool runs for real when its keys are set and `DRY_RUN=false`, otherwise returns realistic fakes.
- **`gate:`** pauses the run until someone approves (`/approvals`, or the CLI). Anything that spends or publishes should have one. `AUTO_APPROVE=true` skips them.
- **`share:`** publishes a step's result to every other bay (Research shares its brief this way; Production reads it as `research.brief`).
- **`fanout:`** hands items in a result to another bay as new runs (the inbox polls do this with orders and messages).
- **`trigger: event`** bays (Studio, Comms) run when something is queued for them instead of on a timer.
- **`emit:` / `transfer_to:`** raise extra events the map animates: a pod launch, a crew member walking a brief to another bay.

Step results accumulate in `ctx` under the step id, so later steps reference earlier ones with dotted paths (`design_draft.files`).

## The bays

| Bay | Trigger | What it does | Real integration to add |
|---|---|---|---|
| Mother · Core | continuous | triage, approvals within cap, stalled-bay sweeps, mission review + directive | model key (otherwise canned decisions) |
| Research Lab | hourly | samples what is selling, ranks movers, writes a brief | a marketplace search client in `tools/research.py` |
| Etsy Production | every 90 min | brief → 4 design variants → mockups → listing copy → publish | image provider (`tools/images.py`), Printify key |
| Thumbnail Studio | per order | brief → prompt → 6 renders → score → package finals | orders in via `POST /inbound/order` (Zapier/Make email parser), delivery upload |
| Comms Deck | per message | classify → draft reply → send, under 90 s | messages in via `POST /inbound/message` or `tools/etsy.poll_messages` |
| Treasury | every 15 min | pulls receipts, records sales, reconciles spend | Etsy OAuth token (`transactions_r`) |
| Launch Bay | every 2 h | caption → schedule → post → metrics | a scheduler API in `tools/publish.py` |
| Sound Lab, Prototype Cell | standby | wake from the dashboard when there is work | audio / coding agents |

## Hooking up the real thing

1. **Model** — set `ANTHROPIC_API_KEY`. Agent steps start returning real JSON. Costs are written per step.
2. **Images** — set `IMAGE_PROVIDER` and `IMAGE_API_KEY`; `tools/images.py` has an OpenAI-style call to adapt.
3. **Printify** — API key + shop id; look up your product's `blueprint_id`, `print_provider_id` and variant ids once and put them in `tools/printify.py`.
4. **Etsy** — register an app, complete OAuth, set `ETSY_ACCESS_TOKEN` and `ETSY_SHOP_ID`. Treasury then records real receipts.
5. **Fiverr** — there is no public order API. Pipe order emails through Zapier/Make into `POST /inbound/order`, or poll a mailbox in `tools/fiverr.poll_inbox`.
6. Flip `DRY_RUN=false`. Keep `AUTO_APPROVE=false` until you trust it; approve from the CLI.

## Event schema

Everything the engine writes is one of these; the dashboard understands the same shape, so anything that emits this JSON can drive the map.

```json
{"ts":"2026-10-17T06:12:03Z","bay":"etsy","kind":"step","step":2,"agent":"FORGE","msg":"Design draft: 4 variants rendered","amount":0.03}
```

`kind`: `snapshot` (full state) · `step` · `complete` (+`output.title`) · `sale` · `order` · `message` · `reply` · `incident` · `trend` · `publish` · `cost` · `status` (+`status`) · `transfer` (+`to`) · `poll`.

## HTTP

```
GET  /events                         SSE; first message is a snapshot, then the last 40 events, then live
GET  /state · /archive · /artifacts · /approvals
POST /approvals/{id}/approve|reject
POST /bays/{id}/hold|boost|wake|standby|run
POST /inbound/order · /inbound/message · /inbound/sale
GET  /                               the dashboard
```

The published copy of the dashboard on claude.ai runs in a sandbox that cannot reach `localhost`, so use the copy the engine serves (or host `dashboard/index.html` next to the engine) for live mode.

## Scaling it

- **More shops** — copy `02_etsy.yaml`, change `id`, `name` and the shop keys the tools read; add a matching bay to `BAYS` in the dashboard.
- **Per-bay P&L as the control loop** — `treasury.reconcile` already computes margin; add a rule that sets a bay to `hold` when trailing margin goes negative and `boost` when it clears a target.
- **Many stations** — the engine is one process per station. Run one per niche/account with its own `.env` and `DB_PATH`, and put a small index page in front.
- **Durability** — for real volume swap the asyncio loop for Temporal or a queue (Redis/BullMQ), keep the YAML and the ledger as they are.

## Read before you turn it on for real

- Etsy and Fiverr both restrict automated accounts and have disclosure rules for AI-assisted goods and services. Read the current policies; the station's doctrine (`prompts/doctrine.md`) keeps disclosure on and the similarity rule in place, but policy compliance is yours.
- Research finds what sells; Production must make something new from it. Copying listing art, text, characters or brands is the fastest way to lose the shop.
- Every spend is logged. Watch `LEDGER` for a day in dry run before trusting any margin number: marketplace fees, print costs and refunds all come off the top.
