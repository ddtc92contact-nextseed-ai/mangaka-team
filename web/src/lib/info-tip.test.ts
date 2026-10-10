// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { HELP } from "./help.ts";
import { TIP_CLOSED, TIP_MARGIN, placeTip, tipButtonAria, tipReducer, type TipEvent, type TipState } from "./info-tip.ts";

const run = (...events: TipEvent[]): TipState => events.reduce(tipReducer, TIP_CLOSED);

test("s'ouvre au survol, se ferme quand la souris s'en va", () => {
  assert.deepEqual(run("hover"), { open: true, pinned: false });
  assert.deepEqual(run("hover", "leave"), TIP_CLOSED);
});

test("s'ouvre au focus clavier, se ferme à la perte du focus", () => {
  assert.equal(run("focus").open, true);
  assert.equal(run("focus", "blur").open, false);
});

test("au doigt : un tap ouvre et épingle, un second tap referme", () => {
  assert.deepEqual(run("tap"), { open: true, pinned: true });
  assert.equal(run("tap", "leave").open, true, "épinglée : reste ouverte sans survol");
  assert.equal(run("tap", "tap").open, false);
});

test("clic souris après survol et focus : la bulle reste ouverte", () => {
  assert.deepEqual(run("hover", "focus", "tap"), { open: true, pinned: true });
  assert.equal(run("hover", "focus", "tap", "leave").open, true);
});

test("Échap et clic à l'extérieur ferment, même épinglée", () => {
  assert.deepEqual(run("tap", "escape"), TIP_CLOSED);
  assert.deepEqual(run("hover", "escape"), TIP_CLOSED);
  assert.deepEqual(run("tap", "outside"), TIP_CLOSED);
});

test("câblage ARIA : le bouton est décrit par la bulle", () => {
  const aria = tipButtonAria("tip-7", false, "Genre");
  assert.equal(aria["aria-describedby"], "tip-7");
  assert.equal(aria["aria-label"], "Aide : Genre");
  assert.equal(aria["aria-expanded"], false);
  assert.equal(tipButtonAria("tip-7", true, "Genre")["aria-expanded"], true);
});

const SIZE = { width: 288, height: 80 };

test("placement : sous le bouton, centrée, à 1440 px", () => {
  const p = placeTip({ top: 100, left: 700, width: 20, height: 20 }, SIZE, { width: 1440, height: 900 });
  assert.equal(p.side, "below");
  assert.equal(p.left, 710 - 144);
  assert.ok(p.top > 120);
});

test("placement : jamais coupée sur les bords d'un écran de 390 px", () => {
  const viewport = { width: 390, height: 844 };
  for (const left of [0, 4, 180, 360, 380]) {
    const p = placeTip({ top: 200, left, width: 20, height: 20 }, SIZE, viewport);
    assert.ok(p.left >= TIP_MARGIN, `gauche ${p.left}`);
    assert.ok(p.left + SIZE.width <= viewport.width - TIP_MARGIN, `droite ${p.left + SIZE.width}`);
  }
});

test("placement : au-dessus quand il n'y a plus la place en bas", () => {
  const p = placeTip({ top: 800, left: 100, width: 20, height: 20 }, SIZE, { width: 390, height: 844 });
  assert.equal(p.side, "above");
  assert.equal(p.top + SIZE.height, 800 - 6);
});

test("textes d'aide : une ou deux phrases en français, non vides", () => {
  for (const [id, text] of Object.entries(HELP)) {
    assert.ok(text.trim().length > 10, id);
    assert.ok(text.length <= 400, `${id} trop long (${text.length})`);
  }
});
