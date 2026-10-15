// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { SceneMeasure } from "./api.ts";
import { rangeText, shareText, shotRows } from "./scene-measure.ts";

const combat: SceneMeasure = {
  scene_id: 2,
  number: 2,
  title: "Le duel",
  type: "combat",
  type_name: "Combat",
  tempo: "6 cases par planche",
  planned_pages: 1,
  expected: {
    panels_min: 6,
    panels_max: 6,
    replies_min: 2,
    replies_max: 4,
    silent_min: 2,
    narration_max: 0,
    motion_lines: "required",
    shots: [
      { class: "close_up", label: "gros plans", min: 0.5, max: 0.7 },
      { class: "wide", label: "plans larges / d'ensemble", min: 0, max: 0.17 },
    ],
    tight_max: 0.85,
  },
  pages: [{ page_id: 9, number: 3, panels: 6, replies: 3, silent: 2, narration: 0, warnings: [] }],
  shots: {
    total: 6,
    applied: 0,
    proposed: 6,
    proposed_counts: { close_up: 2, medium_close: 1, medium: 1, wide: 2, insert: 0 },
  },
  warnings: [],
};

test("bornes et parts en clair", () => {
  assert.equal(rangeText(6, 6), "6");
  assert.equal(rangeText(4, 5), "4 à 5");
  assert.equal(rangeText(undefined, 3), "—");
  assert.equal(shareText(0.5, 0.7), "50 à 70 %");
  assert.equal(shareText(0.5, 1), "au moins 50 %");
  assert.equal(shareText(0, 0.17), "au plus 17 %");
});

test("plans proposés face au profil, écarts repérés", () => {
  const { source, rows } = shotRows(combat);
  assert.equal(source, "proposés");
  assert.deepEqual(
    rows.map((r) => [r.cls, r.count, r.off]),
    [
      ["close_up", 2, true], // 2 sur 6 : moins de 50 %
      ["wide", 2, true], // 2 sur 6 : plus d'1 plan large
    ],
  );
  const applied = shotRows({
    ...combat,
    shots: { ...combat.shots, applied: 6, applied_counts: { close_up: 3, medium_close: 1, medium: 1, wide: 1, insert: 0 } },
  });
  assert.equal(applied.source, "appliqués");
  assert.deepEqual(applied.rows.map((r) => r.off), [false, false]);
  assert.equal(shotRows({ ...combat, shots: { total: 6, applied: 0, proposed: 0 } }).source, null);
});
