// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { ChapterStage } from "./api.ts";
import {
  blockedReason,
  blockingMessage,
  blockingStages,
  decisionLabel,
  hrefPath,
  stageHref,
  stageLinkLabel,
  withPage,
} from "./stages.ts";

function stage(over: Partial<ChapterStage>): ChapterStage {
  return {
    key: "direction",
    label: "Direction artistique appliquée",
    complete: false,
    forced: false,
    passed: false,
    total: 5,
    faults: 5,
    summary: "5 pages en attente sur 5",
    examples: [],
    fix: "Applique-la",
    screen: "direction",
    blocks: ["générer"],
    decision: null,
    ...over,
  };
}

test("étapes qui bloquent une action", () => {
  const direction = stage({});
  const approved = stage({
    key: "approved",
    label: "Cases approuvées",
    summary: "2 cases sans version choisie sur 9",
    fix: "Choisis une version de chaque case dans l'atelier",
    screen: "atelier",
    blocks: ["lettrer", "exporter"],
  });
  const done = stage({ key: "layout", passed: true, complete: true, blocks: [] });
  assert.deepEqual(blockingStages([direction, approved, done], "generation"), [direction]);
  assert.deepEqual(blockingStages([direction, approved, done], "export"), [approved]);
  assert.deepEqual(blockingStages(null, "generation"), []);
  assert.equal(
    blockingMessage(direction, "generation"),
    "Direction artistique appliquée : 5 pages en attente sur 5. Applique-la avant de générer.",
  );
  assert.match(blockingMessage(approved, "export"), /avant d'exporter\.$/);
  assert.equal(blockedReason([direction], "generation"), "Bloqué : direction artistique appliquée (5 pages en attente sur 5)");
  assert.equal(blockedReason([direction], "lettering"), null);
});

test("lien vers l'écran qui règle l'étape", () => {
  assert.equal(stageHref({ screen: "direction" }, 12, 3), "/chapitres/12/direction");
  assert.equal(stageHref({ screen: "personnages" }, 12, 3), "/projets/3");
  assert.equal(stageLinkLabel({ screen: "lettrage" }), "Aller au Lettrage");
});

test("le lien d'étape recopie la planche courante (Atelier planche 5 → Lettrage reste sur la planche 5)", () => {
  assert.equal(stageHref({ screen: "lettrage" }, 12, 3, 5), "/chapitres/12/lettrage?page=5");
  assert.equal(stageHref({ screen: "direction" }, 12, 3, null), "/chapitres/12/direction");
  assert.equal(stageHref({ screen: "personnages" }, 12, 3, 5), "/projets/3"); // fiches de la série : pas de planche
  assert.equal(withPage("/chapitres/12/atelier?case=9", 5), "/chapitres/12/atelier?case=9&page=5");
  assert.equal(withPage("/chapitres/12/atelier?page=2", 5), "/chapitres/12/atelier?page=5");
  assert.equal(withPage("/chapitres/12/scenario", undefined), "/chapitres/12/scenario");
  assert.equal(hrefPath("/chapitres/12/lettrage?page=5"), "/chapitres/12/lettrage");
});

test("décision affichée : validée, forcée, levée", () => {
  const at = "2026-10-13T12:00:00";
  assert.match(decisionLabel({ decision: { decision: "forced", author: "Ouro", note: "", at } }) ?? "", /^forcée par Ouro le /);
  assert.match(decisionLabel({ decision: { decision: "validated", author: "", note: "", at } }) ?? "", /^validée le /);
  assert.equal(decisionLabel({ decision: { decision: "revoked", author: "", note: "", at } }), null);
  assert.equal(decisionLabel({ decision: null }), null);
});
