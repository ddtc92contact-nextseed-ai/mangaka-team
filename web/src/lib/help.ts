// Textes des bulles d'aide (« ? ») de l'atelier, rangés par écran. Une ou deux phrases : ce que ça fait, et quand
// s'en servir. À reformuler ici librement : les écrans n'y font référence que par leur clé.

export const HELP = {
  // --- série (création / modification) -------------------------------------------------------------------------
  // (section série)

  // --- planche de style ------------------------------------------------------------------------------------------
  // (section planche de style)

  // --- chapitre : scénario ---------------------------------------------------------------------------------------
  "scenario.synopsis":
    "Raconte le chapitre en quelques lignes ou colle un script brut. Le scénariste s'en sert, avec la fiche de la série et sa bibliothèque, pour proposer pages, cases et dialogues.",
  "scenario.decouper":
    "Le LLM découpe le synopsis en pages, cases et répliques. Le résultat est enregistré automatiquement dès qu'il est terminé : rien à faire de plus, même si tu recharges la page.",
  "scenario.enregistrer":
    "Enregistre tes retouches à la main (texte, cases, pages ajoutées ou déplacées). Le découpage du LLM, lui, est déjà enregistré : le bouton n'est actif que si tu as modifié quelque chose.",
  "scenario.page_kind":
    "Une page d'histoire fait partie du récit et sera remplacée au prochain « Découper ». Les pages bonus (croquis, notes) et la page de garde sont toujours conservées.",
  "scenario.rythme":
    "Indice pour la mise en page : une page lente (ambiance) garde des cases régulières, une page rapide (action) contraste davantage les tailles et incline les cases.",
  "scenario.shot_type":
    "Le cadrage de la case (plan large, rapproché, gros plan…). Il oriente la composition de l'image générée.",
  "scenario.importance":
    "Le poids de la case dans la page : 1 pour une transition, 3 pour un moment fort, qui reçoit plus de place à la mise en page.",
  "scenario.intensity":
    "L'énergie de la case : « choc » l'agrandit et peut l'incliner, « calme » la garde sage. Laisse « non précisée » si tu n'as pas d'avis.",
  "scenario.bubbles":
    "Chaque réplique devient une bulle au lettrage. Le type change sa forme : parole, pensée, cri, hors champ (personnage hors de la case) ou récitatif (narration dans un cartouche).",
  "scenario.objets":
    "Les objets récurrents de la bibliothèque visibles dans la case : leur description et leurs références sont jointes à la génération pour qu'ils restent identiques.",

  // --- chapitre : mise en page, croquis, atelier, lettrage, production, QC --------------------------------------
  // (section chapitre)

  // --- banc d'essai, savoir-faire, équipe ------------------------------------------------------------------------
  // (section outils)
} as const satisfies Record<string, string>;

export type HelpId = keyof typeof HELP;
