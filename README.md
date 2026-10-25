# StockSense: Before the Rain

**Which rural clinics will be cut off by floods before their malaria medicine runs out, and what should the LGA pharmacist move or buy today?**

> Not a clinical tool. StockSense drafts a plan; a pharmacist approves every action.

Open Agent Hackathon 2026 entry, Track 1. StockSense joins three kinds of source in one Zetaris semantic layer:

| Source | Kind | What it says | Real or synthetic |
|---|---|---|---|
| Clinic stock (Postgres on RDS) | database | courses of ACT on hand, daily use | SYNTHETIC (Kafin LGA scenario) |
| Road register | spreadsheet | each clinic's road and the river level that closes it | SYNTHETIC |
| GloFAS river discharge, Lokoja (Open-Meteo flood API) | web API | daily discharge, 2022 season | real |
| Rainfall, Lokoja (Open-Meteo archive) | web API | daily rain, 2022 season | real |

No single source says which clinics will be cut off before their stock runs out. The join does.

## How a run works

```
Zetaris USL ──► Forecaster ──► Sentinels ──► Planner ⇄ Critic (≤ 2 retries) ──► Evaluator ──► plan / HOLD
```

| Agent | Does | Code |
|---|---|---|
| DataAgent | Reads `clinic_risk` (the USL join) and the river series from Zetaris | `app/data.py` |
| Forecaster | Fits a 7-day trend to river readings **up to `as_of` only** and estimates when each road's threshold is reached within 30 days. Confidence is the trend's R² | `app/agents/forecaster.py` |
| Sentinels | One per clinic: flags below safety stock, missing reading, road closing | `app/agents/sentinels.py` |
| Planner | Transfers from clinics with spare stock first, then the cheapest whole purchase order | `app/agents/planner.py` |
| Critic | Checks donor safety, capacity, budget, and that each delivery arrives before the road closes. A rejection carries the constraint that fixes it back to the Planner | `app/agents/critic.py` |
| Evaluator | Re-queries Zetaris for every number a plan line rests on; any line it can't re-verify goes on **HOLD** | `app/agents/evaluator.py` |
| Coordinator | [FILL: Nightshift / Nemotron, not built yet] | |
| Memory | [FILL: H-MEM, not built yet] | |

Every step writes one trace event (`logs/trace-<run_id>.jsonl`) with: timestamp, run_id, agent_name, action, input_summary, output_summary, target_agent, model, confidence, retry_count, status.

## Run it

Offline, from recorded Zetaris responses (no cluster needed):

```bash
cp .env.example .env          # SAMPLE_MODE=true by default
python3 run.py '{"as_of": "2022-07-04"}'
python3 run.py --serve        # POST /run on 0.0.0.0:8080
docker build -t stocksense . && docker run -p 8080:8080 stocksense
```

Live against Zetaris: set `SAMPLE_MODE=false`, `ZETARIS_REST_URL` and `ZETARIS_API_KEY` in `.env`. A live run also records responses for offline replay.

Tests: `python3 -m unittest discover -s tests -t .`

Errors come back as `{"error": {"type", "message"}}`: `bad_input` / `bad_json` (400), `no_snapshot` (404), `zetaris_unavailable` / `nightshift_unavailable` (502), `sample_cache_miss` (503).

## Examples

`examples/input_examples/` and matching `examples/output_examples/`; regenerate with `python3 examples/make_outputs.py`.

| Input | Shows |
|---|---|
| `01-plan-2022-07-04.json` | a full plan: 4 transfers, 1 purchase, P6 on HOLD (no stock reading) |
| `02-no-snapshot.json` | a date with no stock snapshot: structured 404, no guessing |
| `03-bad-date.json` | bad input: structured 400 |

## What the USL did for us

[FILL: measured, not estimated: lines we didn't write, the completeness check that flags P6, what Zetaris should improve. Findings so far: the SQL editor splits at every `;` including inside string literals; `DROP LIGHTNING TABLE` is a syntax error on build 2.4.3.1; a REST-table query takes about 3 minutes per run.]

## Built before and during the event

Before Oct 22: planning docs, the synthetic Kafin LGA scenario numbers, a DHIS2 demo download (not used in the app). Everything in this repo's code was written during the event. Third-party: Open-Meteo / GloFAS data [FILL: licence terms], patterns from zetaris/getting-started (Apache-2.0).
