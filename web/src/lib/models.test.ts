// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { AgentSetting, DeepSeekModels } from "./api.ts";
import { fromFormValue, toFormValue } from "./agents.ts";
import {
  OTHER_MODEL,
  chooseModel,
  envNote,
  inOtherMode,
  isOtherModel,
  modelNotes,
  modelOptions,
  pickModel,
  selectValue,
  typeModel,
  type ModelChoice,
} from "./models.ts";

function list(extra: Partial<DeepSeekModels> = {}): DeepSeekModels {
  return {
    source: "preset",
    source_label: "liste livrée",
    detail: "mode mock (LLM_PROVIDER) : DeepSeek n'est pas interrogé",
    models: [
      { id: "deepseek-chat", label: "DeepSeek Chat", note: "rapide, sans raisonnement", reasoning: false },
      { id: "deepseek-reasoner", label: "DeepSeek Reasoner", note: "raisonne avant de répondre, plus lent", reasoning: true },
    ],
    preset_model: "deepseek-chat",
    env_model: null,
    default_model: "deepseek-chat",
    ...extra,
  };
}

function modelSetting(extra: Partial<AgentSetting> = {}): AgentSetting {
  return {
    key: "model",
    label: "Modèle",
    help: "",
    group: "Modèle",
    type: "text",
    choices: [],
    nullable: false,
    variables: [],
    min: null,
    max: null,
    step: null,
    global_only: false,
    options_from: "deepseek_models",
    env_override: "DEEPSEEK_MODEL",
    env_value: null,
    source: "presets/providers.yaml › deepseek.model",
    value: "deepseek-chat",
    origin: "preset",
    preset: "deepseek-chat",
    inherited: "deepseek-chat",
    ...extra,
  };
}

test("la liste déroulante : chaque modèle « id — note » en français, puis « Autre… »", () => {
  assert.deepEqual(modelOptions(list(), "deepseek-chat"), [
    { value: "deepseek-chat", text: "deepseek-chat — rapide, sans raisonnement" },
    { value: "deepseek-reasoner", text: "deepseek-reasoner — raisonne avant de répondre, plus lent" },
    { value: OTHER_MODEL, text: "Autre…" },
  ]);
  // Liste pas encore chargée : la valeur effective reste affichée et sélectionnée.
  assert.deepEqual(modelOptions(null, "deepseek-reasoner"), [
    { value: "deepseek-reasoner", text: "deepseek-reasoner" },
    { value: OTHER_MODEL, text: "Autre…" },
  ]);
  assert.equal(selectValue(null, "deepseek-reasoner"), "deepseek-reasoner");
});

test("le modèle effectif est sélectionné", () => {
  assert.equal(selectValue(list(), "deepseek-reasoner"), "deepseek-reasoner");
  assert.equal(isOtherModel(list(), "deepseek-reasoner"), false);
});

test("la valeur venue de .env est signalée, dans la liste et sous le champ", () => {
  const options = modelOptions(list({ env_model: "deepseek-reasoner", default_model: "deepseek-reasoner" }), "deepseek-reasoner");
  assert.equal(options[1].text, "deepseek-reasoner — raisonne avant de répondre, plus lent (choisi dans .env)");
  assert.equal(options[0].text, "deepseek-chat — rapide, sans raisonnement");
  const setting = modelSetting({ env_value: "deepseek-reasoner" });
  assert.match(envNote(setting, "deepseek-reasoner") ?? "", /^DEEPSEEK_MODEL=deepseek-reasoner dans \.env .*c'est le modèle sélectionné/);
  assert.match(envNote(setting, "deepseek-chat") ?? "", /un autre modèle/);
  assert.equal(envNote(modelSetting(), "deepseek-chat"), null);
});

test("« Autre… » : champ libre pour un nom absent de la liste", () => {
  assert.equal(pickModel(OTHER_MODEL), "");
  assert.equal(pickModel("deepseek-reasoner"), "deepseek-reasoner");
  assert.equal(isOtherModel(list(), ""), true);
  assert.equal(selectValue(list(), "deepseek-v4-preview"), OTHER_MODEL);
  assert.ok(modelNotes(list(), "deepseek-v4-preview").some((n) => n.includes("n'est pas dans la liste livrée")));
  const live = list({ source: "live", source_label: "en direct", detail: null });
  assert.equal(modelNotes(live, "deepseek-chat")[0], "Liste en direct de DeepSeek.");
  assert.ok(modelNotes(live, "mon-modele").some((n) => n.includes("risque d'être refusé")));
});

// Rejoue le champ comme ModelSelect : chaque geste met à jour l'état local et la valeur du formulaire.
function field(value: string) {
  let choice: ModelChoice | null = null;
  const apply = (next: ModelChoice) => {
    choice = next;
    value = next.value;
  };
  return {
    pick: (option: string) => apply(chooseModel(option)),
    type: (text: string) => apply(typeModel(text)),
    get value() {
      return value;
    },
    get other() {
      return inOtherMode(list(), value, choice);
    },
    get select() {
      return selectValue(list(), value, choice);
    },
  };
}

for (const name of ["deepseek-chat-v2", "deepseek-reasoner-2"]) {
  test(`« Autre… » : « ${name} » se tape lettre par lettre sans revenir à la liste`, () => {
    const f = field("deepseek-chat");
    assert.equal(f.other, false);
    f.pick(OTHER_MODEL);
    assert.equal(f.value, "");
    for (let i = 1; i <= name.length; i++) {
      f.type(name.slice(0, i)); // passe par « deepseek-chat » / « deepseek-reasoner », ids de la liste
      assert.equal(f.other, true, `champ libre démonté à « ${f.value} »`);
      assert.equal(f.select, OTHER_MODEL);
    }
    assert.equal(f.value, name);
  });
}

test("« Autre… » : seul un choix dans la liste referme le champ libre", () => {
  const f = field("deepseek-chat");
  f.pick(OTHER_MODEL);
  f.type("deepseek-reasoner");
  assert.equal(f.other, true);
  f.pick("deepseek-reasoner");
  assert.equal(f.other, false);
  assert.equal(f.select, "deepseek-reasoner");
  // Valeur changée hors du champ (réinitialisation) : le mode se déduit de nouveau de la valeur.
  assert.equal(inOtherMode(list(), "deepseek-chat", typeModel("deepseek-chat-v")), false);
  assert.equal(inOtherMode(list(), "mon-modele", chooseModel("deepseek-chat")), true);
});

test("d'où vient la liste, et la note des modèles qui raisonnent", () => {
  const notes = modelNotes(list(), "deepseek-reasoner");
  assert.match(notes[0], /^Liste livrée \(presets\/providers\.yaml\) : mode mock/);
  assert.ok(notes.includes("Modèle qui raisonne : plus lent, la température n'est pas envoyée."));
  assert.equal(modelNotes(list(), "deepseek-chat").length, 1);
  // Tapé à la main, absent de la liste : deviné d'après le nom, comme dans le moteur.
  const reasons = (id: string) => modelNotes(list(), id).some((n) => n.startsWith("Modèle qui raisonne"));
  assert.equal(reasons("deepseek-v4-pro-0925"), true);
  assert.equal(reasons("maison-r1"), true);
  assert.equal(reasons("deepseek-v4-preview"), false);
});

test("enregistrement par agent : chaque profil envoie son propre modèle, tel quel", () => {
  const forms: Record<string, string> = { scenariste: "deepseek-reasoner", "directeur-artistique": "deepseek-chat" };
  const payloads = Object.fromEntries(
    Object.entries(forms).map(([agent, model]) => {
      const setting = modelSetting();
      return [agent, { model: fromFormValue(setting, toFormValue(setting, model)) }];
    }),
  );
  assert.deepEqual(payloads, { scenariste: { model: "deepseek-reasoner" }, "directeur-artistique": { model: "deepseek-chat" } });
  assert.equal(fromFormValue(modelSetting(), "deepseek-v4-preview"), "deepseek-v4-preview");
});
