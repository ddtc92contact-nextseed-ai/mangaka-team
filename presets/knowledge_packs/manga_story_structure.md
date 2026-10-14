---
title: manga_story_structure — Base de connaissances de la structure et du rythme (chapitre, genre, arc)
version: 1.0
langue: fr
date: 2026-10-14
usage: RAG — découpage par fiche (titres de niveau ###), métadonnées JSON en tête de chaque fiche
auteur: équipe Mangaka (issue #168), repères alignés sur les presets de l'appli au 14/10/2026
---

# manga_story_structure

> Base documentaire jumelle de `manga_visual_knowledge` (choisir un cadrage) et `manga_rendering_knowledge`
> (rendre une case). Celle-ci apprend au scénariste à **construire** : où placer l'accroche, la bascule, les
> pics et la fin dans un chapitre, quelle courbe de tension suit chaque genre, comment varier d'un chapitre à
> l'autre, où se taire. Chaque fiche donne des repères chiffrés (positions en %, nombres de pages).

## 0.A — Mode d'emploi pour l'indexation RAG

Mêmes règles que les deux autres packs : 1 fiche = 1 chunk (entre deux titres `###`), bloc ```` ```meta ```` en
JSON extrait comme métadonnées, `path` conservé, 250 à 700 jetons par fiche, aucune fiche dépendante d'une autre
(renvois par identifiant). Pas de fragment « Prompt (EN) » : aucune de ces fiches ne va au modèle d'image.

Champs de métadonnées propres à la structure :

```json
{
  "id": "STR_CH_001",
  "path": "20_deroule_du_chapitre/huit_temps.md",
  "type": "chapter | genre | shot | ending | arc | dialogue",
  "agents": ["script", "series_creator"],
  "intent": ["structure", "tension", "pacing"],
  "genre": "shonen | shojo | seinen | tranche-de-vie | franco-belge | jeunesse | magical-girl | any",
  "pairs_with": ["STR_FIN_004"]
}
```

**Vocabulaire de l'appli, à respecter.** Le scénariste écrit, par page, un « rythme » `lent`, `normal` ou
`rapide`, et par case une « intensity » `calme`, `normal` ou `choc` et une « importance » de 1 à 3. Le
directeur artistique traduit ensuite chaque page en rythme `calme`, `montée`, `respiration` ou `climax`
(calme et respiration → lent, montée → normal, climax → rapide) et réserve la « page choc » aux vrais sommets.
Les fiches parlent ces deux langues : le temps du récit, puis ce que le scénariste écrit dans le JSON.

**Les règles chiffrées vivent dans les presets, jamais ici.** Cases par page : consignes du genre
(`style_genres/*.yaml`) ; répliques : `dialogue_rules` de `prompts/script.yaml` ; plans et cases calmes :
`variety_rules` et `page_rules` de `prompts/direction-artistique.yaml`. Les fiches s'y conforment ; en cas de
doute, le preset gagne.

**Branchement (`knowledge.yaml`).** Scénariste : les 6 collections « Structure · … ». Directeur artistique et
rédacteur de prompt : rien (ils reçoivent déjà le rythme décidé, page par page). Le futur agent de création
de série les recevra aussi.

---

## 20_deroule_du_chapitre

### STR_CH_001 — Le déroulé d'un chapitre en huit temps

`path: 20_deroule_du_chapitre/huit_temps.md`

```meta
{"id":"STR_CH_001","type":"chapter","agents":["script","series_creator"],"intent":["structure","tension","pacing"],"genre":"any","pairs_with":["STR_CH_002","STR_FIN_004"]}
```

**Principe.** Presque tous les chapitres suivent le même déroulé ; seuls les dosages changent selon le genre
(fiches STR_GEN_*). Positions en % des pages du chapitre ; entre parenthèses, les pages d'un chapitre de
15 pages (longueur par défaut dans l'appli).

1. **Ouverture** (0–7 %, p. 1) : où, quand, qui. Une case d'établissement du lieu, les personnages en
   situation. Une seule page au plus : le lecteur doit vite avoir une question.
2. **Accroche** (au plus tard 15 %, fin de p. 1 ou p. 2) : une anomalie, une réplique forte, une menace,
   un désir. C'est la question qui fait tourner la page.
3. **Bascule** (15–25 %, p. 3–4) : l'élément déclencheur. L'enjeu du chapitre change ou se précise ; le
   personnage ne peut plus revenir en arrière.
4. **Montée** (25–50 %, p. 4–7) : obstacles de plus en plus forts, chaque scène un cran plus haut que la
   précédente. Une demi-page de respiration y est permise, pas plus.
5. **Premier pic** (50–60 %, p. 8–9) : premier sommet (affrontement, révélation, aveu), suivi d'un
   retournement ou d'un prix à payer — jamais d'une victoire complète.
6. **Respiration** (60–73 %, p. 10–11) : on souffle, on réagit, on comprend. Dialogue, émotion,
   conséquences du pic. C'est là que le lecteur s'attache.
7. **Pic final** (73–93 %, p. 12–14) : le sommet du chapitre, plus haut que le premier pic. Une seule page
   choc au plus dans le chapitre, ici ou sur la dernière page.
8. **Fin** (93–100 %, p. 15, dernière case surtout) : chute ou cliffhanger (fiches STR_FIN_*). La dernière case
   est une case forte (importance 3), jamais une case de transition.

**Pour une autre longueur.** Page d'un temps = position × nombre de pages, arrondi. 8 pages : ouverture et
accroche p. 1, bascule p. 2, montée p. 3–4, premier pic p. 4–5, respiration p. 5–6, pic final p. 6–7, fin
p. 8. Sous 8 pages, fusionner premier pic et pic final (un seul sommet vers 75 %).

**À éviter.** Un chapitre sans bascule avant 25 % (le lecteur décroche) ; deux pics de même hauteur ; un pic
final dans la toute dernière case sans montée avant.

---

### STR_CH_002 — Traduire le déroulé dans le scénario (rythme, intensité, importance)

`path: 20_deroule_du_chapitre/champs_du_scenario.md`

```meta
{"id":"STR_CH_002","type":"chapter","agents":["script"],"intent":["structure","pacing"],"genre":"any","pairs_with":["STR_CH_001","STR_SIL_002"]}
```

**Ce que chaque temps devient dans le JSON du scénariste.** Rythme du directeur artistique entre parenthèses.

| Temps | rythme de la page | intensity des cases | importance |
|---|---|---|---|
| Ouverture | lent (calme) | calme, normal | une case 3 : l'établissement |
| Accroche | normal (montée) | normal, une choc possible | 3 sur la case de l'accroche |
| Bascule, montée | normal (montée) | normal, choc rare | 2, une case 3 par page au plus |
| Premier pic, pic final | rapide (climax) | choc, normal, et au moins une calme | 3 sur le sommet |
| Respiration | lent (respiration) | calme, normal | 2, cases de transition (1) permises |
| Fin | selon la fin : lent pour une chute, normal ou rapide pour un cliffhanger | — | 3 sur la dernière case |

**Répartition sur 15 pages.** Environ 1–2 pages lentes d'ouverture ou de calme, 6–7 pages normales (montée),
3–4 pages rapides (climax), 2–3 pages lentes de respiration. Jamais plus de 2 pages rapides d'affilée : la
troisième perd son effet.

**Cases par page.** Celles du genre (3 à 7 en général, 6 à 9 en franco-belge) : moins de cases aux pics (les
cases fortes prennent la place), plus aux montées et aux dialogues de respiration. Une pleine page (1 case)
seulement pour le sommet du chapitre.

**Ce que vérifie la direction artistique, à préparer dès le scénario.** Au plus 3 cases « choc » d'affilée,
même d'une page à l'autre : un climax alterne choc et normal. Au moins une case calme par page dès 3 cases,
même en climax : la réaction, le souffle, le regard après le coup.

---

## 21_courbes_par_genre

### STR_GEN_001 — Courbe de tension : Shōnen

`path: 21_courbes_par_genre/shonen.md`

```meta
{"id":"STR_GEN_001","type":"genre","agents":["script","series_creator"],"intent":["tension","pacing"],"genre":"shonen","pairs_with":["STR_CH_001","STR_FIN_001"]}
```

**Forme.** Montée en escalier, deux sommets nets, cliffhanger obligatoire. Tension haute dès la première page.
4 à 6 cases par page (consigne du genre).

**Courbe sur 15 pages** (rythme du directeur artistique) : p. 1 montée (accroche d'action dès la 1re page,
l'ouverture se glisse dedans) · p. 2 calme (qui, où, quel enjeu) · p. 3–4 montée (bascule : le défi, le rival)
· p. 5 respiration · p. 6–7 montée · p. 8–9 climax (premier affrontement, le héros prend le dessus puis perd
l'avantage) · p. 10 respiration (douleur, ami, souvenir, résolution intérieure) · p. 11 montée · p. 12–13
climax (pic final, la technique, le dépassement) · p. 14 montée · p. 15 montée terminée par une case choc :
cliffhanger.

**Repères.** 4 à 5 pages de climax sur 15 (2 dans un chapitre de respiration, STR_ARC_002), jamais plus de
2 d'affilée. Une page choc au plus, réservée au
pic final ou à la révélation de la dernière page. Les respirations sont courtes (1 page) mais présentes : sans
elles, l'action n'a plus de poids.

**Dialogue.** Répliques courtes, cris et ordres dans les cases d'action (une case choc où un personnage est
présent a toujours au moins un mot). Un monologue intérieur dans la respiration (pensée).

---

### STR_GEN_002 — Courbe de tension : Shōjo

`path: 21_courbes_par_genre/shojo.md`

```meta
{"id":"STR_GEN_002","type":"genre","agents":["script","series_creator"],"intent":["tension","emotion"],"genre":"shojo","pairs_with":["STR_PLAN_002","STR_FIN_003"]}
```

**Forme.** La tension est émotionnelle : rapprochement, malentendu, aveu. La courbe ondule avec de longues
respirations intérieures ; les pics sont des regards et des mots, pas des coups. 4 à 6 cases par page.

**Courbe sur 15 pages** : p. 1 calme (le quotidien du personnage, son désir) · p. 2 montée (la rencontre, le
regard qui accroche) · p. 3–4 montée (bascule : un obstacle entre eux) · p. 5 respiration (monologue intérieur)
· p. 6–7 montée · p. 8 climax (premier pic : aveu manqué, geste interrompu, rival) · p. 9–10 respiration
(doute, confidence à une amie) · p. 11–12 montée · p. 13–14 climax (pic final : contact, aveu, dispute) · p. 15
respiration ou montée : fin sur un regard, une pensée (ouverture ou cliffhanger émotionnel).

**Repères.** 3 pages de climax sur 15, 4 pages de respiration. Peu de cases « choc » (1 à 3 dans le chapitre) :
le sommet d'un shōjo est une case forte (importance 3) au calme, un visage. Une page choc au plus, pour l'aveu
ou la révélation.

**Dialogue.** Pensées et récitatifs fréquents (au moins une pensée par scène), répliques sensibles et brèves ;
la case muette juste après une réplique clé vaut un sommet (STR_SIL_002).

---

### STR_GEN_003 — Courbe de tension : Seinen

`path: 21_courbes_par_genre/seinen.md`

```meta
{"id":"STR_GEN_003","type":"genre","agents":["script","series_creator"],"intent":["tension","suspense"],"genre":"seinen","pairs_with":["STR_SIL_001","STR_FIN_002"]}
```

**Forme.** Lente au départ, qui accélère tard et fort. L'ouverture prend le temps d'installer un lieu et un
malaise ; la tension monte par le non-dit. 5 à 7 cases par page, silences et cases muettes bienvenus.

**Courbe sur 15 pages** : p. 1–2 calme (ouverture longue, cases de décor, l'accroche est un détail qui cloche,
au plus tard en fin de page 2) · p. 3 montée (bascule) · p. 4 respiration · p. 5–7 montée (pression, menace sourde)
· p. 8 climax (premier pic : violence ou révélation brève, sèche) · p. 9–10 respiration (conséquences,
silence) · p. 11–12 montée · p. 13–14 climax (pic final) · p. 15 calme : chute sèche (le prix payé) ou
cliffhanger froid, souvent une dernière case muette.

**Repères.** 3 pages de climax, 5 à 6 pages lentes (calme et respiration). Le premier pic est court (1 page) :
il frappe et laisse retomber. Pas de page choc systématique : une sur deux ou trois chapitres suffit.

**Dialogue.** Naturel, nuancé, des sous-entendus. Plus de cases muettes qu'ailleurs, mais dans les limites du
chapitre (environ 1 case sur 6 au plus, STR_SIL_001) : ce sont les autres cases qui portent les répliques.

---

### STR_GEN_004 — Courbe de tension : Tranche de vie

`path: 21_courbes_par_genre/tranche_de_vie.md`

```meta
{"id":"STR_GEN_004","type":"genre","agents":["script","series_creator"],"intent":["tension","calm"],"genre":"tranche-de-vie","pairs_with":["STR_FIN_002","STR_FIN_003"]}
```

**Forme.** Courbe presque plate, en petites vagues, avec un seul vrai sommet : une petite émotion. Pas de
cliffhanger forcé (consigne du genre). 5 à 7 cases par page, cases de décor et de détails du quotidien entre les
dialogues.

**Courbe sur 15 pages** : p. 1–3 calme (une journée, un lieu, une habitude ; l'accroche est un petit désir ou
un petit souci, au plus tard page 2) · p. 4–5 montée (la bascule est minuscule : une lettre, une invitation, une
maladresse) · p. 6 respiration · p. 7–8 calme · p. 9–10 montée · p. 11 climax (le seul pic : le moment
partagé, la phrase enfin dite) · p. 12–13 respiration · p. 14–15 calme : chute douce ou ouverture.

**Repères.** 1 page de climax sur 15, 9 à 10 pages lentes. Aucune page choc. Cases « choc » rares (0 à 2) :
un rire, une surprise. Le pic est placé plus tard qu'ailleurs (70–75 %) et la fin le prolonge au lieu de le
dépasser.

**Dialogue.** Conversations du quotidien, plusieurs répliques par case ; les cases de décor muettes font
respirer entre deux scènes.

---

### STR_GEN_005 — Courbe de tension : Franco-belge

`path: 21_courbes_par_genre/franco_belge.md`

```meta
{"id":"STR_GEN_005","type":"genre","agents":["script","series_creator"],"intent":["tension","pacing"],"genre":"franco-belge","pairs_with":["STR_FIN_002","STR_SIL_002"]}
```

**Forme.** Planches denses de 6 à 9 cases en gaufrier régulier (consigne du genre) : la tension ne vient pas de
la taille des cases mais de l'enchaînement. Règle propre à la BD : **chaque planche se termine sur une
relance** (question, gag, menace, porte qui s'ouvre) pour faire tourner la page.

**Courbe sur 15 pages** : p. 1 calme (récitatif d'ouverture, lieu, héros) · p. 2–4 montée (accroche en page 2,
bascule en page 3) · p. 5 respiration (gag) · p. 6–8 montée (enquête, poursuite, quiproquo) · p. 9 climax (premier
pic) · p. 10 respiration · p. 11–12 montée · p. 13–14 climax (pic final) · p. 15 calme : chute (gag final,
résolution) ou « à suivre » si l'épisode continue.

**Repères.** 3 pages de climax, peu de cases d'importance 3 (une par planche au plus). Pas de pleine page.
Récitatifs pour les ellipses et les changements de lieu (« Pendant ce temps… »).

**Dialogue.** Plus fourni qu'en manga, mais une page de 7 à 9 cases n'a la place que d'une réplique par case
(place des bulles) : on étale les échanges sur plusieurs cases plutôt que d'allonger une bulle.

---

### STR_GEN_006 — Courbe de tension : Jeunesse

`path: 21_courbes_par_genre/jeunesse.md`

```meta
{"id":"STR_GEN_006","type":"genre","agents":["script","series_creator"],"intent":["tension","clarity"],"genre":"jeunesse","pairs_with":["STR_FIN_002"]}
```

**Forme.** Simple et lisible : un problème clair, deux tentatives, une réussite, une fin rassurante. Aucune peur
durable (consigne du genre). 3 à 5 cases par page, une action par case.

**Courbe sur 15 pages** : p. 1 calme (les héros, leur monde) · p. 2 montée (le problème est dit clairement,
souvent par une réplique) · p. 3–5 montée (première tentative, raté drôle) · p. 6 respiration (gag, entraide)
· p. 7–9 montée (deuxième tentative) · p. 10 climax (petit danger, vite désamorcé) · p. 11 respiration · p.
12–13 montée · p. 14 climax (les héros réussissent par leurs qualités) · p. 15 calme : fin rassurante, chute
souriante.

**Repères.** 2 pages de climax, jamais d'affilée. Pas de page choc angoissante (une page choc joyeuse — la
réussite — est permise). Pour un chapitre court (8 à 10 pages), garder la même forme : problème avant 20 %,
réussite vers 85 %.

**Dialogue.** Phrases courtes, vocabulaire de l'âge ; chaque case d'action garde un mot d'un personnage pour
que l'enfant suive. Un récitatif ou une pensée pour dire ce que le héros ressent.

---

### STR_GEN_007 — Courbe de tension : Magical girl

`path: 21_courbes_par_genre/magical_girl.md`

```meta
{"id":"STR_GEN_007","type":"genre","agents":["script","series_creator"],"intent":["tension","pacing"],"genre":"magical-girl","pairs_with":["STR_PLAN_002","STR_FIN_001"]}
```

**Forme.** Deux moitiés : vie quotidienne puis combat magique, reliées par la transformation. Une grande case
pour chaque transformation ou attaque spéciale (consigne du genre). 4 à 6 cases par page.

**Courbe sur 15 pages** : p. 1–2 calme (école, amies, un souci du quotidien qui fera écho au combat) · p. 3
montée (accroche : signe de la menace) · p. 4 respiration · p. 5–6 montée (la menace surgit, l'amie en danger :
bascule) · p. 7 climax (transformation, grande case d'importance 3, candidate à la page choc) · p. 8 montée
(le combat tourne mal) · p. 9 climax · p. 10 respiration (doute, amitié, la leçon du quotidien revient) · p. 11
montée · p. 12–13 climax (attaque spéciale, grande case) · p. 14 respiration (retour au quotidien) · p. 15
calme ou montée : chute tendre ou teaser du prochain ennemi.

**Repères.** 4 pages de climax, 2 grandes cases « rituelles » (transformation vers 45 %, attaque finale vers
80 %). Une page choc au plus, sur l'une des deux.

**Dialogue.** Enjoué ; formules de transformation et noms d'attaque en cri (shout) ; une pensée de doute dans
la respiration.

---

## 22_plans_selon_le_moment

### STR_PLAN_001 — Changement de lieu : la case d'établissement

`path: 22_plans_selon_le_moment/etablissement.md`

```meta
{"id":"STR_PLAN_001","type":"shot","agents":["script","series_creator"],"intent":["clarity","structure"],"genre":"any","pairs_with":["STR_PLAN_002"]}
```

**Règle.** À chaque changement de lieu (et au début du chapitre), la première case de la scène montre le
lieu : c'est elle qui deviendra un plan large ou d'ensemble. Le cadrage revient au directeur artistique ; le
scénariste lui donne de quoi le choisir.

**Ce que le scénariste écrit.** Un « setting » complet (lieu, moment, météo, éléments visibles), des
personnages petits ou absents (« characters » peut être vide pour une case de décor), une importance 2 — 3 pour
l'ouverture du chapitre. Un récitatif de lieu ou de temps si l'ellipse n'est pas évidente.

**Repères chiffrés.** Une seule case d'établissement par changement de lieu, jamais deux d'affilée : la
direction artistique refuse deux plans larges qui se suivent et plafonne les plans larges et moyens à la moitié
des cases. Dans un chapitre de 15 pages, compter 3 à 5 scènes (donc 3 à 5 établissements) ; une scène dure 2 à 5
pages. Retour dans un lieu déjà vu dans le chapitre : un détail du lieu (une enseigne, une fenêtre) suffit,
pas un nouvel établissement complet.

**À éviter.** Ouvrir une scène sur un visage sans avoir montré où l'on est (sauf effet voulu : on révèle le
lieu à la case suivante) ; établir le même lieu à chaque page.

---

### STR_PLAN_002 — Serrer aux pics, élargir pour respirer

`path: 22_plans_selon_le_moment/serrer_elargir.md`

```meta
{"id":"STR_PLAN_002","type":"shot","agents":["script","series_creator"],"intent":["emotion","pacing"],"genre":"any","pairs_with":["STR_PLAN_001","STR_SIL_001"]}
```

**Principe.** L'échelle du plan suit la courbe du chapitre. Le scénariste n'écrit pas le plan, mais sa
description l'appelle : « ses doigts se crispent sur la lettre » appelle un insert ; « elle se tient debout
dans la pièce » appelle un plan large.

**Aux pics émotionnels** (premier pic, pic final, accroche, révélation) : décrire le visage, les yeux, la
main, l'objet — de quoi faire un gros plan ou un insert. Mettre l'importance 3 sur la case du sommet, pas sur
toutes les cases du pic.

**Pour respirer** (respiration, fin d'une scène, après un pic) : décrire le lieu, la distance entre les
personnages, la silhouette dans le décor — de quoi faire un plan large. Une ou deux cases de ce type par page
de respiration, pas plus.

**Pendant la montée** : alterner le moyen (deux personnages qui se parlent, qui s'affrontent) et le serré (la
réaction). Une description de réaction (« Kenji pâlit ») par page au moins.

**Repères chiffrés, alignés sur la direction artistique.** Au moins une case serrée (gros plan, très gros plan
ou insert) par page dès 3 cases : prévoir dans chaque page au moins un moment qui l'appelle (réaction, détail,
regard). Plans larges et moyens : la moitié des cases au plus. Jamais deux plans larges d'affilée.

---

## 23_fins_de_chapitre

### STR_FIN_001 — Fin en cliffhanger

`path: 23_fins_de_chapitre/cliffhanger.md`

```meta
{"id":"STR_FIN_001","type":"ending","agents":["script","series_creator"],"intent":["tension","ending"],"genre":"any","pairs_with":["STR_FIN_004","STR_ARC_001"]}
```

**Définition.** Le chapitre s'arrête au moment où la question est la plus forte, avant la réponse :
l'arrivée d'un ennemi, une révélation incomplète, une décision non encore prise, un héros en chute.

**Comment.** Les 2 ou 3 dernières cases montent (page « normal » ou « rapide ») ; la dernière case est une case
forte (importance 3), souvent « choc », avec un mot d'un personnage (un nom crié, « Toi ?! ») ou une seule
réplique qui pose la question. On montre la menace ou le visage qui la découvre, pas la suite.

**Quand.** Shōnen et magical girl : presque toujours. Seinen : cliffhanger froid (une image, pas un cri).
Milieu d'arc (STR_ARC_001) : oui. Dernier chapitre d'un arc : non, sauf pour amorcer l'arc suivant après une
vraie résolution. Tranche de vie et jeunesse : non (pas de cliffhanger forcé, pas de peur durable ; une petite
question souriante suffit).

**À éviter.** Le faux cliffhanger désamorcé à la première page du chapitre suivant (le lecteur s'en lasse au
deuxième) ; trois cliffhangers d'affilée du même type (trois arrivées d'ennemi).

---

### STR_FIN_002 — Fin en chute

`path: 23_fins_de_chapitre/chute.md`

```meta
{"id":"STR_FIN_002","type":"ending","agents":["script","series_creator"],"intent":["humour","ending","resolution"],"genre":"any","pairs_with":["STR_FIN_004","STR_SIL_002"]}
```

**Définition.** La dernière case referme le chapitre en le retournant : un gag, une ironie, une conséquence
inattendue, un détail qui change le sens de ce qu'on vient de lire.

**Comment.** Le pic final se résout à 85–93 % ; la dernière page est lente (calme). Préparer la chute dans les
2 ou 3 cases d'avant (une attente, une réplique sérieuse), puis la dernière case la renverse. Souvent : une
réplique courte suivie d'une case de réaction muette, ou une case muette qui montre le détail qui tue.

**Quand.** Jeunesse et franco-belge : la fin naturelle (gag final, résolution souriante). Tranche de vie : chute
douce. Seinen : chute sèche (le prix payé). Dernier chapitre d'un arc dans tous les genres : la chute clôt l'arc
avant l'amorce du suivant. Chapitre d'humour (ton « humour ») : toujours.

**À éviter.** Une chute qui annule l'enjeu du chapitre (« ce n'était qu'un rêve ») ; une chute expliquée par
une narration.

---

### STR_FIN_003 — Fin en ouverture

`path: 23_fins_de_chapitre/ouverture.md`

```meta
{"id":"STR_FIN_003","type":"ending","agents":["script","series_creator"],"intent":["emotion","ending"],"genre":"any","pairs_with":["STR_FIN_004"]}
```

**Définition.** Le chapitre se clôt sur une image apaisée qui regarde vers la suite : un personnage face à
l'horizon, une promesse, une pensée, un lieu au petit matin. Pas de question urgente, une envie de revenir.

**Comment.** Après le pic final (au plus tard 87 %), une page de respiration ; la dernière case est un plan qui
respire (lieu, silhouette) avec une pensée ou un récitatif d'une ligne, ou rien. Importance 3, intensity
calme.

**Quand.** Shōjo (après un aveu ou un rapprochement), tranche de vie, seinen contemplatif ; fin d'un premier
chapitre de série qui doit installer un monde plutôt qu'une menace ; fin d'un arc avant une pause.

**À éviter.** L'ouverture molle, sans pic avant : elle ne marche que si le chapitre a eu son sommet.

---

### STR_FIN_004 — Choisir sa fin

`path: 23_fins_de_chapitre/choisir.md`

```meta
{"id":"STR_FIN_004","type":"ending","agents":["script","series_creator"],"intent":["ending","structure"],"genre":"any","pairs_with":["STR_FIN_001","STR_FIN_002","STR_FIN_003","STR_ARC_002"]}
```

**Trois questions, dans l'ordre.**

1. **Le genre l'interdit-il ?** Pas de cliffhanger forcé en tranche de vie, pas de cliffhanger angoissant en
   jeunesse (consignes du genre).
2. **Où est-on dans l'arc ?** Premier chapitre et chapitres du milieu : cliffhanger (ou ouverture pour un
   premier chapitre de série). Dernier chapitre d'un arc : chute ou ouverture, puis éventuellement une case
   d'amorce de l'arc suivant.
3. **Quelle fin ont eue les chapitres précédents ?** Pas plus de 3 chapitres de suite avec la même fin ; deux
   cliffhangers consécutifs doivent être de nature différente (menace, puis révélation, puis décision).

**Repères par genre** (fin la plus fréquente, en part des chapitres) : shōnen ≈ 80 % cliffhanger ; magical girl
≈ 60 % cliffhanger, 40 % chute tendre ; shōjo ≈ moitié cliffhanger émotionnel, moitié ouverture ; seinen ≈
moitié cliffhanger froid, moitié chute sèche ; franco-belge : relance en bas de chaque planche, chute en fin
d'épisode ; tranche de vie et jeunesse : chute ou ouverture, presque jamais de cliffhanger.

**Toujours.** La dernière case est une case forte (importance 3). Le « summary » dit en une phrase sur quoi
finit le chapitre : le chapitre suivant en a besoin pour ne pas répéter la même fin.

---

## 24_rythme_d_un_arc

### STR_ARC_001 — Répartir les temps forts sur un arc

`path: 24_rythme_d_un_arc/repartition.md`

```meta
{"id":"STR_ARC_001","type":"arc","agents":["script","series_creator"],"intent":["structure","tension"],"genre":"any","pairs_with":["STR_ARC_002","STR_FIN_004"]}
```

**Principe.** Un arc (une intrigue, un adversaire, un objectif) dure le plus souvent 3 à 8 chapitres et suit, en
grand, le déroulé d'un chapitre (STR_CH_001) : chaque chapitre a son propre pic, mais le sommet de l'arc vient
vers 75–85 % de l'arc.

**Répartition, arc de 5 chapitres.**

- **Chapitre 1** (installation) : nouveau lieu ou nouvel adversaire, bascule de l'arc en fin de chapitre,
  cliffhanger. Pic final modéré.
- **Chapitre 2** (montée) : premier obstacle, premier échec ou victoire partielle. Pic plus haut que le 1.
- **Chapitre 3** (milieu, retournement) : révélation qui change l'enjeu (≈ 50 % de l'arc). Souvent le chapitre
  le plus riche en respiration avant la dernière montée.
- **Chapitre 4** (sommet) : affrontement décisif, le pic de l'arc. Le plus de pages rapides et la page choc de
  l'arc.
- **Chapitre 5** (résolution) : fin de l'affrontement dans la première moitié, puis conséquences, respiration,
  chute ou ouverture, amorce éventuelle de l'arc suivant dans la toute dernière page.

**Arc de 3 chapitres** : installation + montée, sommet, résolution. **Arc de 8** : doubler la montée (chapitres
2 à 5) en y glissant un chapitre de respiration (STR_ARC_002).

**Repères.** Dans tout l'arc, une seule page choc par chapitre au plus, et la plus forte au chapitre du sommet.
Le résumé du chapitre (« summary ») dit où l'on en est de l'arc : c'est ce que relit le chapitre suivant.

---

### STR_ARC_002 — Varier d'un chapitre à l'autre

`path: 24_rythme_d_un_arc/variation.md`

```meta
{"id":"STR_ARC_002","type":"arc","agents":["script","series_creator"],"intent":["pacing","variation"],"genre":"any","pairs_with":["STR_ARC_001","STR_FIN_004"]}
```

**Le risque.** Des chapitres qui suivent tous exactement la même courbe deviennent prévisibles : le lecteur
sait qu'à la page 8 « ça cogne ». Le déroulé est un cadre, pas un moule.

**Ce qu'on fait varier, en relisant les résumés des chapitres précédents.**

- **Position du premier pic** : entre 40 % et 60 % selon le chapitre (p. 6 à 9 sur 15).
- **Ouverture** : une fois sur le lieu, une fois au milieu d'une action (in medias res), une fois sur un
  personnage secondaire ou un souvenir.
- **Densité** : environ un chapitre sur 3 ou 4 est un chapitre « de respiration » (plus de pages lentes,
  1 à 2 pages rapides seulement), placé après le sommet d'un arc ou avant la dernière montée.
- **Point de vue** : un chapitre du milieu d'arc peut suivre un autre personnage que le héros.
- **Fin** : pas plus de 3 chapitres de suite avec le même type de fin (STR_FIN_004).

**Ce qu'on ne fait pas varier.** L'accroche au plus tard à 15 %, une bascule avant 25 %, une dernière case
forte, les consignes du genre (cases par page, ton, public).

**Repères chiffrés.** Sur 15 pages, jamais plus de 5 pages rapides dans un chapitre ; sur 4 chapitres
consécutifs, au moins un en compte 2 ou moins (1 en tranche de vie), et le nombre de pages rapides change d'un
chapitre à l'autre (par exemple 5, 4, 2, 4 en shōnen).

---

## 25_silence_et_dialogue

### STR_SIL_001 — La case muette : quand se taire

`path: 25_silence_et_dialogue/case_muette.md`

```meta
{"id":"STR_SIL_001","type":"dialogue","agents":["script","series_creator"],"intent":["silence","emotion","pacing"],"genre":"any","pairs_with":["STR_SIL_002","STR_PLAN_002"]}
```

**Définition.** Une case sans bulle (ni parole, ni pensée, ni récitatif). Elle ralentit la lecture et donne du
poids à ce qui précède : le lecteur s'arrête avec le personnage.

**Quand.** Juste après une réplique clé (la réaction muette) ; à l'établissement d'un lieu (case de décor) ;
au sommet émotionnel d'un shōjo ou d'un seinen ; dans l'attente avant un choc (l'instant suspendu) ; en
dernière case d'une chute ou d'une ouverture.

**Quand jamais.** Une case d'action (« choc », ou avec une onomatopée) où un personnage est présent garde
toujours au moins un mot de lui (cri, ordre, réaction) : une case d'action muette est refusée, l'onomatopée
seule ne suffit pas.

**Combien, dans les règles de l'appli.** Le dialogue se compte par planche : 4 à 8 répliques par planche par
défaut (l'ADN de la série règle ces chiffres selon le genre), au moins 1 case muette par planche, et la cible
est 2 répliques dans chaque case où un personnage peut parler. Donc :

- une case muette par planche au moins (deux en seinen ou en tranche de vie, selon l'ADN de la série) ;
- jamais plus de 2 cases muettes d'affilée ;
- de préférence des cases sans personnage (décor, objet, insert), ou sur des pages de 6 cases au plus : sur une
  page de 7 à 9 cases, chaque case n'a la place que d'une réplique, une case muette n'y est pas rattrapable ;
- chaque case muette compensée par une voisine à 2 ou 3 répliques.

**Au moins une voix intérieure par chapitre.** Une pensée, une voix off ou un récitatif : souvent juste avant
ou après la case muette, pas dedans.

---

### STR_SIL_002 — Alterner case bavarde et cases muettes

`path: 25_silence_et_dialogue/alternance.md`

```meta
{"id":"STR_SIL_002","type":"dialogue","agents":["script","series_creator"],"intent":["dialogue","pacing"],"genre":"any","pairs_with":["STR_SIL_001","STR_CH_002"]}
```

**Principe.** Le rythme d'une scène de dialogue se lit dans la densité des bulles : des cases chargées font
accélérer l'échange, une case vide le suspend. Un dialogue où chaque case a exactement deux répliques est
monotone.

**Le motif de base** (une page de 5 cases) : bavarde (2 répliques), bavarde (2), réplique clé seule (1),
muette (réaction), relance (2). Soit 7 répliques et une case muette pour 5 cases : la planche est dans les
4 à 8 répliques visées.

**Repères chiffrés, alignés sur les règles de dialogue.**

- Case bavarde : 2 répliques, 3 au plus sur une page de 4 cases ou moins (une case forte en reçoit une de plus) ;
  sur une page de 5 ou 6 cases, 2 au plus (3 pour une case forte) ; de 7 à 9 cases, 1 seule (2 pour une case
  forte).
- Réplique : 12 mots au plus, 7 en moyenne ; la brièveté fait le rythme : on ajoute une bulle, on ne l'allonge
  pas.
- La réplique clé d'une scène est seule dans sa case, la plus courte possible (3 à 6 mots), et suivie d'une
  case de réaction (muette ou d'un seul mot).

**Selon le moment du chapitre.** Montée : échanges rapides, 2 répliques par case, cases de dialogue plus
nombreuses. Pic : peu de mots, des cris et des ordres (jamais une case choc muette). Respiration : les
conversations les plus longues du chapitre, étalées sur plusieurs cases, et les cases muettes de réaction.

**À éviter.** Une scène entière sans une seule case de réaction ; trois cases de suite à 3 répliques (la page
devient un mur de texte et les bulles débordent).
