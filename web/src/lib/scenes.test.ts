// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { ChapterSceneItem } from "./api.ts";
import {
  fromDraft,
  mergeWithNext,
  moveScene,
  newScene,
  pageSpans,
  peakWarningsFor,
  toDraft,
  toggleCast,
  totalPages,
  totalStatus,
} from "./scenes.ts";

const scenes: ChapterSceneItem[] = [
  { id: 1, position: 0, title: "Arrivée", summary: "Aiko arrive.", type: "calme", pages: 2, location_id: null, location_name: null, characters: [{ id: 5, name: "Aiko" }], page_numbers: [] },
  { id: 2, position: 1, title: "", summary: "Le rônin frappe.", type: "combat", pages: 4, location_id: 7, location_name: "Ruelle", characters: [{ id: 6, name: "Rônin" }, { id: 5, name: "Aiko" }], page_numbers: [] },
  { id: 3, position: 2, title: "Fuite", summary: "Elle le poursuit.", type: "poursuite", pages: 3, location_id: null, location_name: null, characters: [], page_numbers: [] },
];

test("brouillon ↔ envoi au moteur", () => {
  const draft = toDraft(scenes);
  assert.equal(draft[1].key, "scene-2");
  const added = [...draft, { ...newScene("revelation", 2), summary: "  Le secret.  " }];
  const sent = fromDraft(added);
  assert.deepEqual(sent[0], {
    id: 1,
    title: "Arrivée",
    summary: "Aiko arrive.",
    type: "calme",
    pages: 2,
    location_id: null,
    characters: [5],
  });
  assert.deepEqual(sent[3].characters, []);
  assert.equal("id" in sent[3], false);
  assert.equal(sent[3].summary, "Le secret.");
});

test("fusion : la première garde son id et son type, les pages s'additionnent", () => {
  const merged = mergeWithNext(toDraft(scenes), 0);
  assert.equal(merged.length, 2);
  assert.deepEqual(
    { id: merged[0].id, type: merged[0].type, pages: merged[0].pages, title: merged[0].title, location: merged[0].location_id },
    { id: 1, type: "calme", pages: 6, title: "Arrivée", location: 7 },
  );
  assert.equal(merged[0].summary, "Aiko arrive. Le rônin frappe.");
  assert.deepEqual(merged[0].characters, [5, 6]); // distributions réunies, sans doublon
  assert.equal(mergeWithNext(merged, 1), merged); // la dernière n'a pas de suivante
});

test("ordre, pages de chaque scène et total face à la cible", () => {
  const moved = moveScene(toDraft(scenes), 2, -1);
  assert.deepEqual(moved.map((s) => s.id), [1, 3, 2]);
  assert.equal(moveScene(moved, 0, -1), moved);
  assert.deepEqual(pageSpans(scenes), ["p. 1-2", "p. 3-6", "p. 7-9"]);
  assert.equal(totalPages(scenes), 9);
  assert.equal(totalStatus(9, 9).state, "ok");
  assert.match(totalStatus(12, 9).message, /^3 pages de trop/);
  assert.match(totalStatus(8, 9).message, /^Il manque 1 page :/);
});

test("distribution : ajouter, retirer ; avertissements du pic d'une scène", () => {
  assert.deepEqual(toggleCast([5], 6), [5, 6]);
  assert.deepEqual(toggleCast([5, 6], 5), [6]);
  const warnings = [
    { scene_id: 3, message: "pic final sur une scène calme" },
    { scene_id: 1, message: "premier pic" },
  ];
  assert.deepEqual(peakWarningsFor(warnings, 3), ["pic final sur une scène calme"]);
  assert.deepEqual(peakWarningsFor(warnings, 2), []);
  assert.deepEqual(peakWarningsFor(warnings, undefined), []);
});
