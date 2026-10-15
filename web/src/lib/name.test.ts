import assert from "node:assert/strict";
import test from "node:test";
import { nameCounts, nextKey, spreadLabel, spreads, turnPage, visualOrder } from "./name.ts";

test("double pages : page 1 seule sur sa belle page, puis 2–3, 4–5, dernière page paire seule", () => {
  assert.deepEqual(spreads([]), []);
  assert.deepEqual(spreads([1]), [[null, 1]]);
  assert.deepEqual(spreads([1, 2, 3]), [[null, 1], [2, 3]]);
  assert.deepEqual(spreads([1, 2, 3, 4]), [[null, 1], [2, 3], [4, null]]);
});

test("sens de lecture : en manga la première page lue est à droite", () => {
  assert.deepEqual(visualOrder([2, 3], "ltr"), [2, 3]);
  assert.deepEqual(visualOrder([2, 3], "rtl"), [3, 2]);
  assert.deepEqual(visualOrder([null, 1], "rtl"), [1, null]); // page 1 à gauche du blanc en manga
  assert.equal(nextKey("rtl"), "ArrowLeft");
  assert.equal(nextKey("ltr"), "ArrowRight");
});

test("tourne : la dernière page lue de la double page", () => {
  assert.equal(turnPage([2, 3]), 3);
  assert.equal(turnPage([4, null]), 4);
  assert.equal(turnPage([null, 1]), 1);
  assert.equal(spreadLabel([{ number: 2 }, { number: 3 }]), "Pages 2–3");
  assert.equal(spreadLabel([null, { number: 1 }]), "Page 1");
});

test("compteur de la name : pages avec cases et palier croquis seulement", () => {
  const counts = nameCounts([
    { name_state: "validated", panels: [{}] },
    { name_state: "stale", panels: [{}] },
    { name_state: "pending", panels: [{}] },
    { name_state: null, panels: [] },
  ] as never);
  assert.deepEqual(counts, { validated: 1, stale: 1, total: 3 });
});
