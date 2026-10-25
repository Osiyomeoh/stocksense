// One H-MEM operation per call: reads {"op", ...} JSON on stdin, writes the
// result as JSON on stdout. State lives in HMEM_DIR (state.json + ledger.jsonl).
// Runs on plain Node >= 23.6: node --experimental-transform-types memory/hmem_cli.ts

import { HMEM } from "../vendor/hmem/index.ts";

const dir = process.env.HMEM_DIR;
if (!dir) throw new Error("HMEM_DIR is not set");
const h = new HMEM({ actor: "stocksense", persistDir: dir });

const chunks: Buffer[] = [];
for await (const c of process.stdin) chunks.push(c as Buffer);
const req = JSON.parse(Buffer.concat(chunks).toString("utf-8"));

const slim = (m: any) => ({ id: m.id, content: m.content, tags: m.tags, confidence: m.confidence, source: m.source });

let out: unknown;
switch (req.op) {
  case "add":
    out = slim(h.add({ ...req.memory, provenance: { learnedAt: Date.now(), ...req.memory.provenance } }));
    break;
  case "list":
    out = h.store.all().filter((m) => (req.tags ?? []).every((t: string) => m.tags.includes(t))).map(slim);
    break;
  case "feedback":
    h.feedback(req.id, req.kind);
    out = slim(h.store.get(req.id));
    break;
  case "history":
    out = h.ledger.history(req.id);
    break;
  default:
    throw new Error(`unknown op ${req.op}`);
}
process.stdout.write(JSON.stringify(out));
