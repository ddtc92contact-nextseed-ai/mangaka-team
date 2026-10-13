// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { formatGap, formatPct, gapTone, judgeKeyAction, rateLabel } from "./journal.ts";

const REASONS = [{ id: "style-pas-manga" }, { id: "visage-rate" }, { id: "autre" }];

test("raccourcis du jugement : G garde, X rejette, chiffres = raison", () => {
  assert.deepEqual(judgeKeyAction("g", REASONS), { verdict: "validated", reason: null });
  assert.deepEqual(judgeKeyAction("G", REASONS), { verdict: "validated", reason: null });
  assert.deepEqual(judgeKeyAction("x", REASONS), { verdict: "rejected", reason: null });
  assert.deepEqual(judgeKeyAction("2", REASONS), { verdict: "rejected", reason: "visage-rate" });
  assert.equal(judgeKeyAction("4", REASONS), null); // pas de 4e raison
  assert.equal(judgeKeyAction("b", REASONS), null); // B / M : annotation du banc QC
  assert.equal(judgeKeyAction("0", REASONS), null);
});

test("écart à la cible en points", () => {
  assert.equal(formatGap(8.34), "+8,3 pts");
  assert.equal(formatGap(-1.2), "−1,2 pt");
  assert.equal(formatGap(0.01), "= cible");
  assert.equal(formatGap(null), "");
  assert.equal(gapTone(2), "near");
  assert.equal(gapTone(-7), "mid");
  assert.equal(gapTone(25), "far");
  assert.equal(gapTone(undefined), null);
});

test("pourcentages et taux de validation", () => {
  assert.equal(formatPct(21.7), "21,7 %");
  assert.equal(formatPct(null), "—");
  assert.equal(rateLabel(66.7, 2, 3), "66,7 % (2/3)");
  assert.equal(rateLabel(null, 0, 0), "—");
});
