// Lancé par `npm test` (node --test, types retirés par Node : pas d'alias `@/`, imports en `.ts`).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { PageData } from "./api.ts";
import { fromDraft, newDialogue, toDraft } from "./script.ts";

const page = {
  id: 7,
  kind: "story",
  rythme: null,
  panels: [
    {
      id: 70,
      description: "Aiko sur un toit",
      characters: ["Aiko"],
      shot_type: null,
      importance: 2,
      dialogues: [
        { id: 701, speaker: "Aiko", text: "Là-haut !", kind: "speech" },
        { id: 702, speaker: "", text: "Pendant ce temps…", kind: "narration" },
      ],
    },
  ],
} as unknown as PageData;

test("le Scénario renvoie l'id des répliques : leur lettrage (cadre, absence de queue) suit la bulle", () => {
  const draft = toDraft([page]);
  const panel = draft[0].panels[0];
  // retouche du texte, réordonnancement, nouvelle réplique : l'id suit la réplique, la nouvelle n'en a pas
  panel.dialogues = [
    { ...panel.dialogues[1], text: "Pendant ce temps, en ville…" },
    panel.dialogues[0],
    { ...newDialogue(), speaker: "Aiko", text: "Et toi ?" },
  ];
  const sent = fromDraft(draft)[0].panels[0].dialogues;
  assert.deepEqual(sent, [
    { id: 702, speaker: "", text: "Pendant ce temps, en ville…", kind: "narration" },
    { id: 701, speaker: "Aiko", text: "Là-haut !", kind: "speech" },
    { id: undefined, speaker: "Aiko", text: "Et toi ?", kind: "speech" },
  ]);
});
