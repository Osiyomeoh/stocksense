# StockSense: Before the Rain

**Which rural clinics will be cut off by floods before their malaria medicine runs out, and what should the LGA pharmacist move or buy today?**

> Not a clinical tool. StockSense drafts a plan; a pharmacist approves every action.

Open Agent Hackathon 2026 entry, Track 1. StockSense joins three kinds of source in one Zetaris semantic layer:

| Source | Kind | What it says | Real or synthetic |
|---|---|---|---|
| Clinic stock (Postgres on RDS) | database | courses of ACT on hand, daily use | SYNTHETIC (Kafin LGA scenario) |
| Road register | spreadsheet | each clinic's road and the river level that closes it | SYNTHETIC |
| GloFAS river discharge, Lokoja (Open-Meteo flood API) | web API | daily discharge, 2022 season | real (copied to Postgres, see below) |
| Rainfall, Lokoja (Open-Meteo archive) | web API | daily rain, 2022 season | real (copied to Postgres) |

No single source says which clinics will be cut off before their stock runs out. The join does.

## How a run works

```
Zetaris USL ──► Forecaster ──► Sentinels ──► Memory Keeper (H-MEM) ──► Planner ⇄ Critic (≤ 2 retries) ──► Evaluator ──► plan / HOLD
```

| Agent | Does | Code |
|---|---|---|
| DataAgent | Reads `clinic_risk` (the USL join) and the river series from Zetaris | `app/data.py` |
| Forecaster | Using river readings **up to `as_of` only**, flags each road that could reach its closure threshold within 30 days at the fastest daily rise of the last 7. A warning, not a date (see the backtest below). Confidence is the R² of the 7-day trend | `app/agents/forecaster.py` |
| Sentinels | One per clinic: flags below safety stock, missing reading, road closing | `app/agents/sentinels.py` |
| Planner | Transfers from clinics with spare stock first, then the cheapest whole purchase order | `app/agents/planner.py` |
| Critic | Checks donor safety, capacity, budget, and that a flagged road gets only next-day transfers. A rejection carries the constraint that fixes it back to the Planner | `app/agents/critic.py` |
| Evaluator | Re-queries Zetaris for every number a plan line rests on; any line it can't re-verify goes on **HOLD** | `app/agents/evaluator.py` |
| Coordinator | Writes the pharmacist's briefing from the verified plan, on Nemotron through Nightshift. Every number in the text must appear in the plan; if one doesn't, or Nightshift is down, it falls back to a fixed template and the trace says why | `app/agents/coordinator.py` |
| Memory Keeper | Before planning, reads the pharmacist's supplier notes from H-MEM. A note at confidence ≥ 0.70 becomes an `avoid_suppliers` constraint for the Planner; a lower one is shown for the pharmacist to confirm, not applied | `app/agents/memory_keeper.py` |

### Nemotron, through Nightshift

| Agent | Model | Via |
|---|---|---|
| Coordinator | `nvidia/nemotron-3.5-lightning-30b-a3b` (override with `COORDINATOR_MODEL`) | Nightshift, `http://127.0.0.1:8088/v1` |

The other agents are deterministic code: they decide, the model only words the decision. Each Coordinator call is a trace event whose `model` field names the model that answered. Nightshift receipt log: [FILL].

Every step writes one trace event (`logs/trace-<run_id>.jsonl`) with: timestamp, run_id, agent_name, action, input_summary, output_summary, target_agent, model, confidence, retry_count, status.

### Memory: H-MEM (Meterless)

A pharmacist's EDIT note changes the next plan. On the recorded 2022-08-08 snapshot:

1. With no notes, the order is 200 courses from S2, ₦500,000.
2. `python3 run.py --feedback "S2 was late again, use S3"` (or `POST /feedback {"note": ...}`, or the Remember box in the UI) stores an H-MEM memory: source `pharmacist`, confidence 0.80, tags `supplier, avoid, S2`.
3. The next run avoids S2, and the order becomes 500 courses from S3, ₦1,000,000. That is S3's minimum order, and it stays inside the ₦4,000,000 budget.
4. A contradicting note (`"S2 is fine now"`) sends H-MEM `feedback("wrong")`. Confidence drops 0.80 → 0.60, H-MEM tags the memory `review`, and the note now falls below the 0.70 gate. The order goes back to S2 and the UI asks the pharmacist to confirm the note.

Notes are parsed with rules, not a model: each clause naming a known supplier and a word like "late", "avoid" or "don't" is remembered; a clause with "fine", "reliable" or "back" marks that supplier's notes wrong. Every recall is a `MemoryKeeper` trace event with the memory's confidence.

How it runs: `memory/hmem_cli.ts` is a small Node sidecar over the unmodified H-MEM reference implementation in `vendor/hmem/` (Apache-2.0, see `vendor/hmem/NOTICE`). It needs Node ≥ 23.6 and no npm install. State is in `data/memory/` (`state.json`, plus the trust ledger `ledger.jsonl`), set with `HMEM_DIR`. If Node is missing, the run goes on without memory and the trace says so. Test: `tests/test_memory_changes_decision.py` runs the real engine.

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

Errors come back as `{"error": {"type", "message"}}`: `bad_input` / `bad_json` (400), `no_snapshot` (404), `zetaris_unavailable` / `nightshift_unavailable` / `hmem_unavailable` (502), `sample_cache_miss` (503).

## Setup (Zetaris side)

`killtests/k2` built the first version; `infra/` is the current state: `python3 -I infra/seed_pg.py` loads the 2022-08-08 SYNTHETIC stock snapshot and the river and rain copies into RDS Postgres, and `python3 -I infra/apply_zetaris.py` registers them and re-activates the `clinic_risk` USL view for any snapshot date. The view's `first_closure_date` column uses the whole season (hindsight); no agent reads it.

## Examples

`examples/input_examples/` and matching `examples/output_examples/`; regenerate with `python3 examples/make_outputs.py`.

| Input | Shows |
|---|---|
| `01-plan-2022-07-04.json` | a full plan: 4 transfers, 1 purchase, P6 on HOLD (no stock reading) |
| `02-no-snapshot.json` | a date with no stock snapshot: structured 404, no guessing |
| `03-bad-date.json` | bad input: structured 400 |
| `04-plan-2022-08-08-rising-river.json` | rising river: the Critic rejects an 8-day purchase to P3 (road flagged), the retry covers P3 and P5 by next-day transfers; ₦521,900 |

## Can the road forecast be trusted?

Not as a date. `python3 eval/backtest_forecaster.py` replays the Forecaster on every day of the real 2022 GloFAS season at Lokoja, using only readings up to that day (road thresholds are SYNTHETIC):

| Road | Actually closed | First warning | Days in the last 30 not flagged | Days the forecast date was too late |
|---|---|---|---|---|
| P3 | 2022-08-28 | 2022-07-29, 30 days ahead | 9 | 5 of 21 |
| P5 | 2022-08-14 | 2022-07-23, 22 days ahead | 9 | 13 of 21 |
| P7 | 2022-09-12 | 2022-08-13, 30 days ahead | 12 | 6 of 18 |

The river's August surge outruns any extrapolation from the week before. So a forecast closure is only a **warning**: once a road is flagged, the Critic accepts only next-day transfers to that clinic, never a 7-day purchase, and a road already shut gets nothing. A shortfall is reported, not hidden.

## What the USL did for us

[FILL: measured, not estimated: lines we didn't write, the completeness check that flags P6, what Zetaris should improve. Findings so far: the SQL editor splits at every `;` including inside string literals; `DROP LIGHTNING TABLE` is a syntax error on build 2.4.3.1; Zetaris re-fetches a REST table on every query, about 3 minutes each, so `infra/seed_pg.py` copies the same Open-Meteo responses into Postgres: a live run went from 4–6 minutes to under about a minute.]

## Built before and during the event

Before Oct 22: planning docs, the synthetic Kafin LGA scenario numbers, a DHIS2 demo download (not used in the app). Everything in this repo's code was written during the event. Third-party: Open-Meteo / GloFAS data [FILL: licence terms], patterns from zetaris/getting-started (Apache-2.0), the H-MEM reference implementation from meterless/meterless (Apache-2.0, vendored unmodified in `vendor/hmem/`).
