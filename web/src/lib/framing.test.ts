// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { moveInFrame, moveOffscreen, nameKey, viewpointSpectators, viewpointSummary } from "./framing.ts";

test("noms comparés sans casse ni accents", () => {
  assert.equal(nameKey("Élise  Dupont"), "elise dupont");
  assert.equal(nameKey("Trafiquant 2"), nameKey("trafiquant 2"));
});

test("sortir du cadre puis y remettre un personnage (case 133 : le trafiquant 2 seul)", () => {
  let cast = { characters: ["Trafiquant 2", "Angus", "Seku"], offscreen: [] as string[] };
  cast = moveOffscreen(moveOffscreen(cast, "Angus"), "seku");
  assert.deepEqual(cast, { characters: ["Trafiquant 2"], offscreen: ["Angus", "seku"] });
  cast = moveInFrame(cast, "Angus");
  assert.deepEqual(cast, { characters: ["Trafiquant 2", "Angus"], offscreen: ["seku"] });
});

test("case sans personnage : tout le monde hors cadre (case 138)", () => {
  const cast = moveOffscreen(moveOffscreen({ characters: ["Angus", "Seku"], offscreen: [] }, "Angus"), "Seku");
  assert.deepEqual(cast.characters, []);
});

test("point de vue : spectateurs du choix, sinon ceux repérés ; résumé en français", () => {
  assert.deepEqual(viewpointSpectators(null, ["Seku", "Angus"]), ["Seku", "Angus"]);
  assert.deepEqual(viewpointSpectators({ spectators: ["Seku"] }, ["Seku", "Angus"]), ["Seku"]);
  assert.equal(viewpointSummary("subjective", ["Seku", "Angus"]), "Vue subjective — Seku, Angus hors cadre");
  assert.equal(viewpointSummary("reaction", ["Seku"]), "Plan de réaction — Seku à l'image");
  // Bascule partielle : Seku remis dans l'image, Angus encore hors cadre.
  const cast = { characters: ["Trafiquant 1", "Seku"], offscreen: ["Angus"] };
  assert.equal(
    viewpointSummary("reaction", ["Seku", "Angus"], cast),
    "Plan de réaction — Seku à l'image, Angus hors cadre",
  );
  assert.equal(
    viewpointSummary("subjective", ["Seku", "Angus"], { characters: [], offscreen: ["seku", "Angus"] }),
    "Vue subjective — Seku, Angus hors cadre",
  );
});
