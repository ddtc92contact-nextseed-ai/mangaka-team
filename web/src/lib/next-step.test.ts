// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import { nextStep, stepHref } from "./next-step.ts";

test("messages du moteur : l'étape à faire d'abord", () => {
  assert.equal(nextStep("Aucune page à diriger : découpe d'abord le chapitre dans l'onglet Scénario")?.step, "scenario");
  assert.equal(nextStep("Écris d'abord le synopsis ou le script brut du chapitre")?.step, "scenario");
  assert.equal(nextStep("Aucune direction artistique à appliquer : lance d'abord l'agent")?.step, "direction");
  assert.equal(nextStep("Page 3 pas encore mise en page : calcule la mise en page d'abord")?.step, "mise-en-page");
  assert.equal(nextStep("La page 2 n'est pas mise en page : lance « Recalculer » d'abord")?.step, "mise-en-page");
  assert.equal(nextStep("Aucun croquis validé : valide d'abord une composition au tri")?.step, "croquis");
  assert.equal(nextStep("Génère d'abord une version de la case : c'est elle qui tourne")?.step, "atelier");
  assert.equal(nextStep("Aucune version à contrôler : génère d’abord la case")?.label, "Aller à l'Atelier");
});

test("erreur ordinaire : pas d'étape", () => {
  assert.equal(nextStep("Moteur hors ligne"), null);
  assert.equal(nextStep("Un découpage de ce chapitre est déjà en cours"), null);
});

test("lien vers l'onglet du chapitre", () => {
  assert.equal(stepHref(12, "mise-en-page"), "/chapitres/12/mise-en-page");
});
