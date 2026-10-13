---
title: manga_visual_knowledge — Base de connaissances de mise en scène manga pour agents
version: 1.0
langue: fr (fragments de prompt en anglais)
date: 2026-10-12
usage: RAG — découpage par fiche (titres de niveau ###), métadonnées JSON en tête de chaque fiche
---

# manga_visual_knowledge

> Base documentaire destinée aux agents de la « mangaka team » (scénariste, metteur en scène, storyboarder, directeur artistique, générateur ComfyUI, contrôleur qualité).
> Objectif : casser la monotonie des plans moyens frontaux et apprendre aux agents à **choisir** un cadrage, un angle, une composition et un découpage en fonction d'une **intention narrative**.

---

## 0.A — Mode d'emploi pour l'indexation RAG

**Découpage recommandé (chunking).**
- 1 chunk = 1 fiche, c'est-à-dire tout le contenu situé entre deux titres `###`.
- Chaque fiche commence par un bloc ```` ```meta ```` en JSON. Extraire ce bloc comme **métadonnées** du chunk (filtres) et l'enlever du texte embarqué, ou le garder — les deux fonctionnent.
- Le chemin de section (`## 01_cadrages / plan_moyen.md`) est à stocker comme champ `path` pour reconstituer l'arborescence d'origine.
- Taille visée : 250 à 700 tokens par fiche. Aucune fiche ne dépend d'une autre pour être comprise ; les renvois se font par identifiant (`→ SHOT_CU_001`).

**Champs de métadonnées (schéma commun).**

```json
{
  "id": "STRING unique, ex. SHOT_CU_001",
  "path": "01_cadrages/gros_plan.md",
  "type": "fundamental | shot_scale | camera_angle | body_gesture | action_beat | composition | layout | emotion | anti_repetition | worked_example",
  "agents": ["director", "storyboarder", "art_director", "prompter", "qa"],
  "intent": ["liste de tags d'intention, voir vocabulaire 0.B"],
  "shot_scale": "extreme_long | long | full | medium_full | medium | medium_close | close_up | extreme_close_up | detail | variable",
  "camera_angle": "eye_level | high | low | birds_eye | worms_eye | dutch | pov | over_shoulder | variable",
  "motion_level": "static | low | medium | high | variable",
  "genres": ["action", "drama", "thriller", "comedy", "horror", "romance", "slice_of_life", "kids_edu"],
  "avoid_when": ["conditions où la fiche est contre-productive"],
  "pairs_with": ["IDs de fiches complémentaires"]
}
```

**Requêtes typiques que les agents doivent pouvoir faire.**
- « techniques pour montrer une esquive sans plan moyen » → filtre `type=action_beat` + `intent=evasion`.
- « montrer la peur sans cadrer le visage » → `intent=fear` + `avoid_when` ne contenant pas `face_required`.
- « comment ouvrir une page de révélation » → `type=layout` + `intent=reveal`.
- « la case précédente était un plan moyen frontal, que proposer ? » → `type=anti_repetition`.

**Ordre de consultation conseillé par agent.**

| Agent | Sections prioritaires | Moment de la consultation |
|---|---|---|
| Scénariste | 00, 07 | Avant d'écrire les « beats » de la scène |
| Metteur en scène | 00, 02, 04, 07 | Pour transformer chaque beat en intention visuelle |
| Storyboarder | 01, 02, 04, 06, 08 | Pour choisir échelle, angle, taille de case, transition |
| Directeur artistique | 03, 05 | Pour la composition interne, les masses, les silhouettes |
| Prompter ComfyUI | Fragments « Prompt (EN) » de toutes les fiches | Au moment d'écrire le prompt |
| Contrôleur qualité | 08, puis 09 comme références | Après le storyboard, avant génération ; puis après génération |

---

## 0.B — Vocabulaire contrôlé (à réutiliser tel quel dans les fiches de cases)

Ce vocabulaire doit être le même dans le RAG, dans les sorties JSON du storyboarder et dans le contrôleur qualité. Sinon la détection de répétition ne fonctionne pas.

**Échelles de plan (`shot_scale`)**

| Valeur | Français | Ce qui est cadré |
|---|---|---|
| `extreme_long` | Plan général / très grand ensemble | Le décor domine, personnage minuscule ou absent |
| `long` | Plan d'ensemble | Personnage entier + beaucoup de décor |
| `full` | Plan en pied | Personnage de la tête aux pieds, peu de marge |
| `medium_full` | Plan américain | De la tête aux cuisses/genoux |
| `medium` | Plan moyen / plan taille | De la tête à la taille |
| `medium_close` | Plan rapproché poitrine | De la tête à la poitrine |
| `close_up` | Gros plan | Le visage remplit la case |
| `extreme_close_up` | Très gros plan | Une partie du visage (yeux, bouche) |
| `detail` | Insert / plan de détail | Un objet ou une partie du corps hors visage (main, pied, poing, arme) |

**Angles (`camera_angle`)** : `eye_level` (hauteur d'yeux), `high` (plongée), `low` (contre-plongée), `birds_eye` (vue zénithale), `worms_eye` (ras du sol, regard vers le haut), `dutch` (horizon incliné), `pov` (vue subjective), `over_shoulder` (amorce par-dessus l'épaule).

**Orientation du sujet (`subject_facing`)** : `front`, `three_quarter_front`, `profile`, `three_quarter_back`, `back`.

**Profondeur (`depth`)** : `flat` (tout sur un même plan), `layered` (premier plan / plan moyen / fond), `exaggerated_foreground` (amorce énorme au premier plan), `deep_perspective` (fuyantes marquées).

**Composition (`composition`)** : `centered`, `rule_of_thirds`, `strong_diagonal`, `triangle`, `frame_in_frame`, `negative_space`, `asymmetric_weight`, `symmetrical`, `spiral`, `radial` (lignes de concentration).

**Cohn — contenu de la case (`attention_frame`)** : `macro` (plusieurs entités actives), `mono` (une seule entité active), `micro` (moins qu'une entité : une partie du corps, un détail), `amorphic` (aucune entité active : décor, ciel, objet inerte).

**Cohn — rôle narratif de la case (`narrative_role`)** : `orienter`, `establisher`, `initial`, `prolongation`, `peak`, `release`.

**Transitions McCloud (`transition`)** : `moment_to_moment`, `action_to_action`, `subject_to_subject`, `scene_to_scene`, `aspect_to_aspect`, `non_sequitur`.

**Taille relative de case (`panel_weight`)** : `tiny` (< 1/12 de page), `small`, `medium`, `large`, `tier` (bande complète), `half_page`, `splash` (pleine page), `spread` (double page), `bleed` (case à fond perdu / tachikiri).

**Tags d'intention (`intent`)** — liste ouverte, à enrichir : `establish_place`, `establish_relation`, `tension`, `anticipation`, `speed`, `impact`, `evasion`, `grab`, `throw`, `fall`, `power`, `domination`, `vulnerability`, `isolation`, `fear`, `anger`, `sadness`, `surprise`, `shock`, `reveal`, `mystery`, `hesitation`, `decision`, `intimacy`, `comedy_beat`, `silence`, `time_slowdown`, `time_skip`, `atmosphere`, `emphasis`, `aftermath`, `explanation` (utile en manga pédagogique).

---

## 0.C — Fiche de case : format de sortie attendu du storyboarder

Chaque case planifiée doit sortir avec au minimum ces champs. Ils servent à la fois au prompter et au contrôleur qualité.

```json
{
  "panel_id": "p03_c2",
  "page": 3,
  "beat": "Le héros esquive le crochet",
  "narrative_role": "peak",
  "intent": ["evasion", "speed"],
  "attention_frame": "micro",
  "shot_scale": "close_up",
  "camera_angle": "worms_eye",
  "subject_facing": "three_quarter_front",
  "body_focus": "torse incliné + poing adverse",
  "composition": "strong_diagonal",
  "depth": "exaggerated_foreground",
  "line_of_action": "diagonale bas-gauche → haut-droite",
  "focal_point": "le poing qui frôle la joue",
  "panel_weight": "medium",
  "panel_shape": "slanted",
  "transition_from_previous": "action_to_action",
  "effects": ["speed_lines_horizontal"],
  "variation_reason": "rompt avec deux cases eye_level précédentes",
  "prompt_fragments": ["worm's-eye view", "fist in extreme foreground", "torso leaning back"]
}
```


---

## 0.D — Index des fiches

| Section | ID | Titre |
|---|---|---|
| 00_fondamentaux | `FUND_001` | Narration visuelle : une case = une décision |
| 00_fondamentaux | `FUND_002` | Grammaire de la BD : les rôles narratifs des cases (Cohn) |
| 00_fondamentaux | `FUND_003` | Rythme et transitions : McCloud, compression et relâchement |
| 00_fondamentaux | `FUND_004` | Hiérarchie visuelle : guider l'œil dans la case et la page |
| 01_cadrages | `SHOT_XLS_001` | Plan général (très grand ensemble) |
| 01_cadrages | `SHOT_LS_001` | Plan d'ensemble |
| 01_cadrages | `SHOT_MS_001` | Plan moyen (plan taille) |
| 01_cadrages | `SHOT_MFS_001` | Plan américain / plan en pied |
| 01_cadrages | `SHOT_CU_001` | Gros plan (visage) |
| 01_cadrages | `SHOT_XCU_001` | Très gros plan |
| 01_cadrages | `SHOT_DET_001` | Plan de détail / insert (corps et objets) |
| 01_cadrages | `SHOT_PART_001` | Cadrages partiels, amorces et hors champ |
| 01_cadrages | `SHOT_OTS_001` | Amorce par-dessus l'épaule (champ / contrechamp) |
| 02_angles_camera | `ANG_HIGH_001` | Plongée |
| 02_angles_camera | `ANG_LOW_001` | Contre-plongée |
| 02_angles_camera | `ANG_BIRD_001` | Vue zénithale (plongée verticale) |
| 02_angles_camera | `ANG_WORM_001` | Vue ras du sol |
| 02_angles_camera | `ANG_DUTCH_001` | Angle hollandais (horizon incliné) |
| 02_angles_camera | `ANG_POV_001` | Vue subjective |
| 02_angles_camera | `ANG_FORCE_001` | Perspective forcée (raccourci extrême) |
| 03_corps_et_gestes | `BODY_001` | Mains et doigts |
| 03_corps_et_gestes | `BODY_002` | Bras et épaules |
| 03_corps_et_gestes | `BODY_003` | Jambes et pieds |
| 03_corps_et_gestes | `BODY_004` | Torsion du buste et contrapposto |
| 03_corps_et_gestes | `BODY_005` | Expressions faciales (au-delà du visage frontal) |
| 03_corps_et_gestes | `BODY_006` | Silhouettes, poses et ligne d'action |
| 03_corps_et_gestes | `BODY_007` | Gestes interrompus et micro-mouvements |
| 04_action_et_mouvement | `ACT_001` | Anticipation (l'instant avant) |
| 04_action_et_mouvement | `ACT_002` | Accélération et vitesse |
| 04_action_et_mouvement | `ACT_009` | Lignes d'effet (*kōka-sen*) : catalogue |
| 04_action_et_mouvement | `ACT_003` | Impact |
| 04_action_et_mouvement | `ACT_004` | Esquive |
| 04_action_et_mouvement | `ACT_005` | Chute |
| 04_action_et_mouvement | `ACT_006` | Projection / saisie |
| 04_action_et_mouvement | `ACT_007` | Mouvement hors champ |
| 04_action_et_mouvement | `ACT_008` | Décomposition d'une action en cases |
| 05_composition | `COMP_001` | Diagonales et lignes de force |
| 05_composition | `COMP_002` | Profondeur et premier plan |
| 05_composition | `COMP_003` | Espace négatif |
| 05_composition | `COMP_004` | Silhouettes, contraste et masses noires |
| 05_composition | `COMP_005` | Cadres dans le cadre |
| 05_composition | `COMP_006` | Compositions asymétriques et formes de base |
| 06_decoupage_manga | `LAY_001` | Ouverture de page et de scène |
| 06_decoupage_manga | `LAY_002` | Révélations et tournes de page |
| 06_decoupage_manga | `LAY_003` | Scènes de dialogue |
| 06_decoupage_manga | `LAY_004` | Scènes de tension et de suspense |
| 06_decoupage_manga | `LAY_005` | Scènes de combat |
| 06_decoupage_manga | `LAY_006` | Transitions entre cases : formes, gouttières, débordements |
| 06_decoupage_manga | `LAY_007` | Compositions de page et de double page |
| 07_emotions | `EMO_001` | Peur |
| 07_emotions | `EMO_002` | Colère |
| 07_emotions | `EMO_003` | Tristesse |
| 07_emotions | `EMO_004` | Surprise |
| 07_emotions | `EMO_005` | Intimidation / domination |
| 07_emotions | `EMO_006` | Vulnérabilité |
| 07_emotions | `EMO_007` | Silence et attente |
| 08_anti_repetition | `ANTI_001` | Détection des cadrages répétitifs |
| 08_anti_repetition | `ANTI_002` | Variation des angles |
| 08_anti_repetition | `ANTI_003` | Variation des échelles |
| 08_anti_repetition | `ANTI_004` | Variation des compositions et des pages |
| 08_anti_repetition | `ANTI_005` | Exceptions : quand la répétition est voulue |
| 09_exemples_analyses | `EX_001` | Dialogue tendu |
| 09_exemples_analyses | `EX_002` | Combat rapide |
| 09_exemples_analyses | `EX_003` | Révélation |
| 09_exemples_analyses | `EX_004` | Poursuite |
| 09_exemples_analyses | `EX_005` | Scène émotionnelle |

---

## 00_fondamentaux

### FUND_001 — Narration visuelle : une case = une décision
`path: 00_fondamentaux/narration_visuelle.md`

```meta
{"id":"FUND_001","type":"fundamental","agents":["director","storyboarder","qa"],"intent":["emphasis"],"shot_scale":"variable","camera_angle":"variable","pairs_with":["FUND_002","FUND_004","ANTI_001"]}
```

**Principe.** Une case n'illustre pas le texte : elle choisit **un instant**, **un point de vue** et **une priorité de lecture**. Le manga traditionnel japonais traite la page comme un dispositif de contrôle du regard ; le choix du cadrage, de la taille de case et de la composition sont décidés ensemble, à partir de ce que la case doit faire ressentir (c'est la règle centrale enseignée par le cours de mangaka de Shōgakukan : « ce que la case doit exprimer décide de sa taille et de son cadrage »).

**Les 7 questions obligatoires avant de décrire une case** (le metteur en scène y répond, le storyboarder les traduit) :
1. Quel est l'**événement** de cette case, en un verbe ? (esquive, découvre, hésite, tombe…)
2. Quel est son **rôle dans la séquence** : installer, amorcer, prolonger, culminer, relâcher ? (→ FUND_002)
3. Qu'est-ce que le lecteur doit **regarder en premier** ? (point focal unique)
4. Quelle **partie du corps ou du décor** raconte le mieux l'événement ? Souvent ce n'est **pas** le personnage entier.
5. Quelle **distance** sert l'émotion ? Plus on se rapproche, plus on entre dans la subjectivité ; plus on s'éloigne, plus on montre le contexte et l'isolement.
6. Quel **angle** ajoute un sens (domination, vulnérabilité, malaise, vitesse) ?
7. Qu'est-ce qui doit être **caché** ou **hors champ** ? Ne pas tout montrer crée l'attente.

**Ce que la recherche dit du manga.** Les études comparatives de Neil Cohn sur des corpus annotés montrent que les comics américains cadrent plus volontiers des scènes entières avec plusieurs personnages, alors que le manga découpe davantage : personnages isolés, fragments de corps, morceaux de décor. Une étude plus récente sur plus de 300 œuvres montre aussi que le manga recourt plus souvent à la **vue subjective**, et que ces vues subjectives apparaissent surtout dans les cases serrées (détails, gros plans) ou dans les cases de décor sans personnage. Conséquence directe pour les agents : **un découpage « manga » crédible contient beaucoup de cases `micro` et `amorphic`, pas seulement des `macro` et `mono`.**

**Règle de travail.** Si la réponse à la question 4 est « le personnage en entier » plus de deux fois de suite, le storyboarder doit justifier ce choix dans `variation_reason`.

**À éviter.**
- Décrire la case comme une photo de plateau (« A et B debout dans la chambre, ils parlent »).
- Laisser le générateur d'images « inventer » la mise en scène à partir d'un prompt vague.
- Choisir le cadrage après le dialogue : le dialogue s'adapte à l'image, pas l'inverse.

---

### FUND_002 — Grammaire de la BD : les rôles narratifs des cases (Cohn)
`path: 00_fondamentaux/grammaire_de_la_bd.md`

```meta
{"id":"FUND_002","type":"fundamental","agents":["director","storyboarder","qa"],"intent":["tension","anticipation","impact","aftermath"],"pairs_with":["FUND_003","ACT_008","LAY_007"]}
```

**Le modèle.** La *Visual Narrative Grammar* de Neil Cohn propose que chaque image d'une séquence occupe un rôle catégoriel, organisé en constituants emboîtés comme les éléments d'une phrase. La séquence canonique est : **Establisher → Initial → (Prolongation) → Peak → Release**, éventuellement précédée d'un **Orienter**. Des études en électrophysiologie ont montré que les lecteurs perçoivent réellement ces frontières de constituants.

| Rôle | Fonction | Cadrages qui fonctionnent souvent | Erreur fréquente |
|---|---|---|---|
| `orienter` | Situer le lieu/l'ambiance, avant même les personnages | `extreme_long`, `amorphic`, `birds_eye` | Le faire en plan moyen avec personnages qui posent |
| `establisher` | Poser les entités et leur relation sans action | `long`, `full`, `over_shoulder`, `macro` | Le répéter à chaque page |
| `initial` | Déclencher la tension, préparer l'action | `detail` (main qui se crispe), `medium_close`, angle bas | Montrer déjà le résultat |
| `prolongation` | Retenir, étirer le temps juste avant le pic | `extreme_close_up`, case étroite, silence | La supprimer dans les moments forts : le pic perd sa force |
| `peak` | Le moment culminant (impact, révélation, décision) | case la plus grande de la séquence, angle fort, diagonale | Lui donner la même taille que les autres cases |
| `release` | Conséquence, réaction, retombée | `long` (vue d'après), `close_up` réaction, `amorphic` | L'oublier : la scène paraît coupée |

**Propriétés utiles pour les agents.**
- **Emboîtement** : un `peak` peut lui-même contenir une mini-séquence initial→peak. Un combat entier est une grande séquence dont chaque coup est une sous-séquence.
- **Le contexte décide du rôle** : une même image (un poing levé) est `initial` si le coup arrive ensuite, `peak` si c'est le geste culminant.
- **Le pic peut être remplacé** : les expériences de Cohn montrent qu'une « étoile d'action » (case d'impact abstraite) peut remplacer le pic sans casser la compréhension. Pour nous : un pic peut être un **flash d'impact sans corps visible**.
- **Branchements à gauche** : chaque scène peut servir d'`initial` à la suivante, ce qui enchaîne les pages.

**Règle de découpage.** Le storyboarder étiquette chaque case avec `narrative_role`. Le contrôleur qualité vérifie : (a) qu'il y a un `peak` par séquence, (b) que le `peak` a le plus gros `panel_weight` de la séquence ou un traitement visuel distinctif, (c) qu'il existe un `release`.

---

### FUND_003 — Rythme et transitions : McCloud, compression et relâchement
`path: 00_fondamentaux/rythme_et_transitions.md`

```meta
{"id":"FUND_003","type":"fundamental","agents":["storyboarder","qa"],"intent":["time_slowdown","speed","atmosphere","silence"],"pairs_with":["LAY_006","EMO_007","ANTI_003"]}
```

**Les 6 transitions de Scott McCloud** (*Understanding Comics*) :

| Transition | Ce qui change entre deux cases | Effet | Usage manga typique |
|---|---|---|---|
| `moment_to_moment` | Presque rien, quelques instants | Ralenti, tension, suspense | Œil qui s'ouvre ; goutte qui tombe ; main qui se ferme lentement |
| `action_to_action` | Le même sujet passe d'une action à la suivante | Lisibilité, cause → effet | Coup armé → coup porté |
| `subject_to_subject` | On reste dans la scène, on change de sujet | Dynamisme, montage | Le héros parle → la main de l'adversaire se crispe |
| `scene_to_scene` | Saut de temps ou de lieu | Ellipse | Fin de chapitre, flash-back |
| `aspect_to_aspect` | Le temps est suspendu, l'œil « se promène » dans le même instant | Ambiance, lieu, émotion | Chambre : poster, lampe, rideau, visage — sans action |
| `non_sequitur` | Aucun lien logique | Humour absurde, rêve | Gag, onirisme |

McCloud a observé que les transitions `aspect_to_aspect` (et dans une moindre mesure `moment_to_moment`) sont fréquentes dans le manga et rares dans la BD occidentale ; elles servent surtout à installer une humeur ou un lieu plutôt qu'à faire avancer l'action. **C'est l'outil n°1 pour sortir du « plan moyen qui parle »** : au lieu de trois cases de dialogue frontales, intercaler des aspects du lieu et des fragments du corps.

**Compression (*asshuku*) et relâchement (*kaihō*) — Natsume Fusanosuke.** Le critique Natsume décrit trois fonctions de la case : découper le temps, produire des effets de compression/relâchement, et créer un espace symbolique. Points directement exploitables :
- Une suite de **petites cases de même taille** crée un battement régulier et une compression ; on « entre » progressivement dans la tête du personnage, surtout si on se rapproche de lui case après case (dos → visage → oreille).
- Une **case soudainement très large** après cette série produit un relâchement, une respiration.
- Une **case haute et étroite** après une série de bandes horizontales produit un relâchement vertical (élévation, chute, verticalité).
- Le **changement de scène et le changement de forme de case ne doivent pas tomber sur la même case** : décaler la rupture d'une case accumule la tension (*tame*) avant de la libérer.
- Le calcul se fait **par page et par double page**.

**Le *ma* (間, l'intervalle).** Les cases sans dialogue, les silences, les cases de décor vides sont des temps de respiration. Elles ne sont pas du remplissage : elles règlent la vitesse de lecture.

**Règles opérationnelles.**
- Plus de texte → lecture plus lente. Case muette → lecture rapide ou silence pesant selon sa taille.
- Ralentir = multiplier les cases sur un même instant (`moment_to_moment`) ou ajouter une `prolongation`.
- Accélérer = cases étroites, sans texte, `action_to_action`, lignes de vitesse.
- Une séquence d'action ne doit pas contenir que des `action_to_action` : insérer un `subject_to_subject` (réaction, témoin, objet) donne de l'air et de l'échelle.

---

### FUND_004 — Hiérarchie visuelle : guider l'œil dans la case et la page
`path: 00_fondamentaux/hierarchie_visuelle.md`

```meta
{"id":"FUND_004","type":"fundamental","agents":["storyboarder","art_director","qa"],"intent":["emphasis"],"pairs_with":["COMP_004","LAY_007","COMP_001"]}
```

**Sens de lecture.** Manga japonais : de droite à gauche puis de haut en bas, case par case et bulle par bulle. Si la publication est en sens occidental (gauche → droite), **inverser toutes les règles de direction ci-dessous**. Le storyboarder doit connaître ce paramètre (`reading_direction: rtl | ltr`) avant toute décision.

**Ordre de lecture sans ambiguïté** (règles du cours Shōgakukan) :
- Ne jamais créer une disposition qui peut se lire de deux façons.
- Espace entre cases côte à côte **étroit** (≈ 4–6 mm à l'échelle d'une page imprimée), espace entre bandes **large** (≈ 8–10 mm) : l'œil saute naturellement à la case la plus proche. Inverser ces écarts pour forcer une lecture verticale.
- Varier franchement la taille des cases (« mettre de la *meri-hari* », du contraste) ; une page de cases de taille égale paraît confuse et terne.
- Au maximum ~8 cases par page ; 5 environ est un rythme confortable.
- Raisonner en **double page**, pas page par page.
- Les cases déformées (obliques, trapézoïdales) sont réservées aux moments-clés ; trop nombreuses, elles rendent la page illisible.

**Direction du regard et du mouvement.** Natsume observe qu'en manga lu de droite à gauche, un personnage qui **avance vers l'événement à venir est tourné vers la gauche** (sens de lecture) ; aller vers la droite évoque le retour, le recul, ou l'intériorité. Pour `ltr`, inverser.
- Personnage qui fonce / progresse → orienté dans le sens de lecture.
- Personnage qui recule, est repoussé, hésite → orienté contre le sens de lecture.

**Haut / bas du cadre.** Le haut d'une case évoque la légèreté, la liberté ; le bas, la lourdeur et la contrainte. Placer la menace en bas et l'espoir en haut (ou inversement pour un effet d'écrasement).

**Dans la case : un seul point focal.** Outils pour l'imposer :
1. Contraste de valeur maximal au point focal (noir contre blanc).
2. Netteté / densité de détail au point focal, simplification ailleurs.
3. Lignes convergentes (perspective, lignes de concentration *shūchūsen*, bras tendus, regards).
4. Isolement dans l'espace négatif.
5. Position : tiers forts, ou centre pour un face-à-face frontal volontaire.

**Bulles.** Les bulles font partie de la composition : elles se lisent dans le même ordre que les cases, ne doivent pas masquer le point focal, et restent à l'intérieur de la zone de sécurité d'impression quand la case est à fond perdu.


---

## 01_cadrages

> Rappel : l'échelle de plan dit **à quelle distance** on regarde. Elle ne dit pas d'où (→ 02_angles_camera). Toujours choisir les deux.

### SHOT_XLS_001 — Plan général (très grand ensemble)
`path: 01_cadrages/plan_general.md`

```meta
{"id":"SHOT_XLS_001","type":"shot_scale","agents":["storyboarder","art_director"],"shot_scale":"extreme_long","intent":["establish_place","isolation","atmosphere","aftermath","scale"],"motion_level":"low","avoid_when":["dialogue_dense","emotion_must_read_on_face"],"pairs_with":["ANG_BIRD_001","COMP_003","LAY_001"]}
```

**Définition.** Le décor domine ; le personnage est petit, parfois une silhouette, parfois absent (case `amorphic`).

**Quand l'utiliser.**
- Ouverture de scène ou de chapitre (`orienter`).
- Montrer l'échelle d'une menace (monstre, ville détruite, tempête).
- Solitude, perte, fin d'une confrontation (`release`).
- Respiration après une série de gros plans (relâchement).

**Règles de composition.**
- Horizon placé haut (écrasement, sol dominant) ou bas (ciel dominant, liberté).
- Un point de contraste unique pour retrouver le personnage (silhouette noire sur ciel blanc, ou inverse).
- Largeur : idéalement une bande entière (`tier`) ou une case à fond perdu (`bleed`).

**À éviter.** Mettre une bulle de dialogue longue (le lecteur ne voit plus personne parler) ; en utiliser deux de suite sans changement d'angle.

**Prompt (EN).** `extreme wide shot, tiny lone figure, vast environment dominating the frame, high horizon line, strong silhouette, manga panel, black and white ink, screentone sky`

---

### SHOT_LS_001 — Plan d'ensemble
`path: 01_cadrages/plan_ensemble.md`

```meta
{"id":"SHOT_LS_001","type":"shot_scale","agents":["storyboarder"],"shot_scale":"long","intent":["establish_relation","establish_place","choreography"],"motion_level":"variable","pairs_with":["COMP_002","ACT_008"]}
```

**Définition.** Personnages entiers dans leur environnement, assez de décor pour comprendre la géographie de la scène.

**Quand l'utiliser.**
- `establisher` : qui est où, qui fait face à qui. Indispensable avant un échange champ/contrechamp ou un combat.
- Montrer la chorégraphie d'une action complexe en une image (poursuite, chute).
- Rétablir la géographie après plusieurs cases serrées (règle : **après 4 à 6 cases serrées, re-situer**).

**Règles de composition.** Exploiter la profondeur : un personnage proche, un éloigné, plutôt que deux personnages alignés sur la même ligne. Utiliser l'angle (plongée légère) pour lisibilité du sol.

**À éviter.** Les deux personnages de profil, côte à côte, au même plan, à hauteur d'yeux : c'est l'image « plate » par excellence.

**Prompt (EN).** `long shot, two characters at different depths, clear spatial layout of the room, slight high angle, layered foreground and background`

---

### SHOT_MS_001 — Plan moyen (plan taille)
`path: 01_cadrages/plan_moyen.md`

```meta
{"id":"SHOT_MS_001","type":"shot_scale","agents":["storyboarder","qa"],"shot_scale":"medium","intent":["dialogue","neutral"],"motion_level":"low","avoid_when":["peak","impact","more_than_2_consecutive"],"pairs_with":["ANTI_001","SHOT_OTS_001","SHOT_CU_001"]}
```

**Définition.** Cadré de la tête à la taille. Valeur « par défaut » de la plupart des générateurs : c'est le plan **qui pose problème quand il devient automatique**.

**Quand il est le bon choix.**
- Dialogue où gestes des mains ET visage comptent.
- Case de transition calme, `establisher` léger entre deux personnages proches.
- Gag : posture + expression dans la même case.

**Comment le rendre vivant (obligatoire si on l'utilise).**
- Jamais frontal pur : trois-quarts, dos partiel, amorce (épaule/tête d'un autre personnage au premier plan) → SHOT_OTS_001.
- Angle non neutre (légère contre-plongée ou plongée).
- Le personnage **fait** quelque chose avec ses mains (objet, geste).
- Décentrer le sujet et laisser de l'espace dans la direction du regard.

**Seuils.** Maximum 2 plans moyens consécutifs ; maximum ~30 % des cases d'une page (paramètre de départ, à ajuster).

**À éviter.** Plan moyen pour un `peak` ; plan moyen frontal centré à hauteur d'yeux avec fond neutre (le « portrait d'identité »).

**Prompt (EN), version vivante.** `medium shot, three-quarter view, over-the-shoulder framing with blurred shoulder in foreground, slight low angle, character gesturing with hand, off-center composition`

---

### SHOT_MFS_001 — Plan américain / plan en pied
`path: 01_cadrages/plan_americain.md`

```meta
{"id":"SHOT_MFS_001","type":"shot_scale","agents":["storyboarder","art_director"],"shot_scale":"medium_full","intent":["power","pose","confrontation","entrance"],"motion_level":"medium","pairs_with":["BODY_006","ANG_LOW_001"]}
```

**Définition.** Plan américain : de la tête à mi-cuisse ; plan en pied (`full`) : corps entier. Ce sont les plans de la **posture**.

**Quand l'utiliser.**
- Entrée d'un personnage, pose iconique (le *mie* théâtral : arrêt sur une pose forte).
- Face-à-face avant un combat : on lit les appuis et l'arme.
- Langage corporel important (épaules tombantes, poings serrés le long du corps).

**Règles.** Ligne d'action courbe et lisible (→ BODY_006). Combiné à une contre-plongée pour imposer, à une plongée pour fragiliser. En `full`, attention aux pieds coupés : couper au-dessus des chevilles ou montrer entièrement, pas sur l'articulation.

**Prompt (EN).** `cowboy shot, confident stance, strong S-curve line of action, low angle, character framed from head to mid-thigh, dramatic rim light`

---

### SHOT_CU_001 — Gros plan (visage)
`path: 01_cadrages/gros_plan.md`

```meta
{"id":"SHOT_CU_001","type":"shot_scale","agents":["storyboarder","art_director"],"shot_scale":"close_up","intent":["emotion","decision","reaction","intimacy","surprise"],"motion_level":"low","avoid_when":["geography_unclear","more_than_3_faces_in_a_row"],"pairs_with":["SHOT_XCU_001","EMO_004","BODY_005"]}
```

**Définition.** Le visage remplit la case. Le cadre entre dans la subjectivité.

**Quand l'utiliser.** Réaction (`release`), prise de décision, réplique-clé, émotion intense, avant/après un choc.

**Rendre le gros plan expressif.**
- Recadrer **hors du centre** : couper le haut du crâne (intensité), ou laisser de l'espace devant le regard (attente).
- Inclinaison légère de la tête et de la caméra.
- Lumière dure latérale : moitié du visage dans l'ombre (doute, menace), **hachurée ou tramée, jamais en aplat noir plein** : en aplat, le modèle la rend comme un bloc noir qui mange la moitié de la figure, et le lecteur y voit un visage déformé (→ REN_VAL_002).
- Ajouter un **élément de contexte** dans le cadre (main au premier plan, reflet, objet) pour qu'il ne soit pas qu'un portrait.

**À éviter.** Enchaîner des gros plans de visage pour toute une scène émotionnelle : alterner avec mains, objets, espace (→ EMO_003). Le contrôleur signale plus de 3 gros plans visage consécutifs.

**Prompt (EN).** `close-up of face, cropped at forehead, off-center, harsh side lighting, half of the face in hatched shadow, never a flat black fill, intense eyes, manga ink`

---

### SHOT_XCU_001 — Très gros plan
`path: 01_cadrages/tres_gros_plan.md`

```meta
{"id":"SHOT_XCU_001","type":"shot_scale","agents":["storyboarder"],"shot_scale":"extreme_close_up","intent":["shock","tension","time_slowdown","prolongation","reveal"],"motion_level":"static","avoid_when":["first_panel_of_scene"],"pairs_with":["FUND_002","LAY_002","EMO_001"]}
```

**Définition.** Une partie du visage : les yeux, une pupille, la bouche, une goutte de sueur.

**Quand l'utiliser.** `prolongation` juste avant un `peak` ; réalisation soudaine ; suspense ; regard qui découvre (le reflet dans la pupille est un classique de révélation).

**Formats.** Case **bande horizontale étroite** pour les yeux (cinémascope) ; petite case insérée par-dessus une grande case (*inset*).

**Règles.** Contexte nécessaire : un très gros plan ne fonctionne que si le lecteur sait déjà à qui il appartient. Ne jamais ouvrir une scène dessus.

**Prompt (EN).** `extreme close-up on eyes, wide horizontal letterbox panel, dilated pupils, reflection of a silhouette in the iris, sweat drop, heavy black ink`

---

### SHOT_DET_001 — Plan de détail / insert (corps et objets)
`path: 01_cadrages/plan_detail.md`

```meta
{"id":"SHOT_DET_001","type":"shot_scale","agents":["director","storyboarder","art_director"],"shot_scale":"detail","attention_frame":"micro","intent":["anticipation","tension","action_clarity","hesitation","emphasis","clue"],"motion_level":"variable","avoid_when":["detail_without_narrative_function","object_not_yet_introduced_and_unreadable"],"pairs_with":["BODY_001","BODY_002","BODY_003","ACT_001","ACT_008"]}
```

**Définition.** Isoler une main, un pied, un poing, une arme, un objet-clé. C'est la case `micro` de Cohn — **la plus sous-utilisée par les générateurs**, et la plus « manga ».

**Variantes prêtes à l'emploi.**
- Main : qui saisit, qui tremble, qui hésite devant une poignée, qui lâche un objet, poing qui se serre, ongles qui griffent le sol.
- Bras : avant-bras qui bloque, bras tendu traversant le premier plan, épaule qui pivote.
- Jambes : genou qui fléchit avant un saut, pied qui pivote, talon qui dérape, pied qui écrase un objet.
- Objets : téléphone qui vibre, poignée qui tourne, goutte qui tombe, horloge, arme qu'on dégaine.

**Fonctions.** Montrer une action sans montrer tout le personnage ; anticiper (`initial`) ; rendre lisible un mécanisme (la saisie d'un poignet) ; ralentir le temps ; donner un indice.

**Règles.** Préciser **qui** (vêtement, accessoire reconnaissable pour identifier le personnage), **quelle partie**, **quelle action**, **quel angle**. Ne pas couper sur une articulation par accident. Fond simplifié ou lignes d'effet.

**À éviter.** Le détail décoratif qui n'apporte aucune information ; plus de deux inserts consécutifs sans case de contexte.

**Prompt (EN).** `extreme close-up insert of a hand gripping a wrist, knuckles tense, sleeve detail identifying the character, foreshortened, speed lines background, manga ink, high contrast`

---

### SHOT_PART_001 — Cadrages partiels, amorces et hors champ
`path: 01_cadrages/cadrages_partiels.md`

```meta
{"id":"SHOT_PART_001","type":"shot_scale","agents":["director","storyboarder"],"shot_scale":"variable","intent":["mystery","reveal","tension","fear","depth"],"pairs_with":["SHOT_OTS_001","ACT_007","LAY_002"]}
```

**Définition.** Montrer volontairement **une partie** de l'information : silhouette coupée par le bord de case, visage hors cadre (on ne voit que la bouche), personnage vu à travers un obstacle, ombre portée seule.

**Techniques.**
1. **Amorce au premier plan** (épaule, nuque, objet flou) : donne profondeur + point de vue.
2. **Coupe du visage au-dessus de la bouche** : personnage mystérieux ou menaçant ; on lit la réplique sans voir les yeux.
3. **Ombre seule** : quelqu'un arrive, on ne sait pas qui.
4. **Partie du corps qui entre dans le cadre** : main posée sur l'épaule par un personnage hors champ.
5. **Obstacle** : à travers une porte entrouverte, des stores, une foule.

**Quand l'utiliser.** Avant une révélation (ne pas tout donner) ; pour créer une présence menaçante ; pour rendre le lecteur complice d'un personnage qui observe.

---

### SHOT_OTS_001 — Amorce par-dessus l'épaule (champ / contrechamp)
`path: 01_cadrages/cadrages_partiels.md`

```meta
{"id":"SHOT_OTS_001","type":"shot_scale","agents":["storyboarder"],"shot_scale":"medium_close","camera_angle":"over_shoulder","intent":["dialogue","confrontation","relation"],"pairs_with":["LAY_003","SHOT_MS_001"]}
```

L'épaule et la nuque d'un personnage au premier plan, l'autre de face en arrière-plan. Respecter la **règle des 180°** : imaginer une ligne entre les deux personnages et garder la caméra du même côté pendant l'échange, pour que chacun reste du même côté de l'image. En BD, cette règle est moins stricte qu'au cinéma (les cases ne sont pas de taille constante et se lisent comme un puzzle), mais pour un dialogue à deux elle évite que les personnages paraissent se tourner le dos. La franchir **volontairement** (→ ANTI_005) marque un basculement : rapport de force qui s'inverse, changement de point de vue.

**Prompt (EN).** `over-the-shoulder shot, dark silhouette of shoulder and hair in the foreground, second character facing camera in the midground, shallow depth, dialogue scene`


---

## 02_angles_camera

> L'angle porte un **jugement** sur le sujet. Hauteur d'yeux = neutre. Tout autre angle ajoute un sens. Un générateur non guidé choisit presque toujours `eye_level` : c'est la deuxième cause de planches « plates » après le plan moyen.

### ANG_HIGH_001 — Plongée
`path: 02_angles_camera/plongee.md`

```meta
{"id":"ANG_HIGH_001","type":"camera_angle","agents":["director","storyboarder"],"camera_angle":"high","intent":["vulnerability","defeat","isolation","overview","surveillance"],"pairs_with":["SHOT_XLS_001","EMO_006","ACT_005"]}
```

**Définition.** Caméra au-dessus du sujet, regard vers le bas.

**Sens produit.** Le sujet paraît plus petit, écrasé, observé, vaincu. Mateu-Mestre (*Framed Ink*) résume l'idée en associant « regarder vers le bas » et « se sentir abattu ».

**Usages.**
- Personnage à terre après une défaite, au sol après une chute (`release`).
- Point de vue d'un dominant (vue subjective d'un adversaire qui toise).
- Lisibilité spatiale : une plongée moyenne montre le sol, donc les positions et trajectoires (combat, poursuite).
- Solitude : plongée forte + plan général + espace négatif.

**Dosage.** Légère (15–30°) = lisibilité sans jugement fort. Forte (45–70°) = écrasement émotionnel.

**Prompt (EN).** `high-angle shot looking down at the character, character appears small and vulnerable, floor visible around them, strong perspective, negative space`

---

### ANG_LOW_001 — Contre-plongée
`path: 02_angles_camera/contre_plongee.md`

```meta
{"id":"ANG_LOW_001","type":"camera_angle","agents":["director","storyboarder"],"camera_angle":"low","intent":["power","domination","intimidation","heroism","threat","entrance"],"pairs_with":["SHOT_MFS_001","EMO_005","COMP_004"]}
```

**Définition.** Caméra sous le sujet, regard vers le haut. *Framed Ink* parle de « plans qui écrasent » (*overpowering upshots*).

**Sens produit.** Puissance, menace, héroïsme, monumentalité. Le ciel ou le plafond devient le fond : silhouette très lisible.

**Usages.** Entrée d'un antagoniste ; héros qui se relève ; décision ferme ; bâtiment ou créature immense.

**Règles.** Mettre l'horizon très bas ou hors cadre ; accentuer les fuyantes verticales ; rapprocher la caméra pour déformer (jambes et mains énormes, tête petite). Combiner avec un contre-jour.

**À éviter.** Utiliser la contre-plongée pour **tous** les personnages : elle perd son sens. La réserver au personnage en position de force **à ce moment-là**.

**Prompt (EN).** `low-angle shot, camera below the character looking up, towering silhouette against the sky, converging vertical lines, imposing, backlit`

---

### ANG_BIRD_001 — Vue zénithale (plongée verticale)
`path: 02_angles_camera/vue_zenithale.md`

```meta
{"id":"ANG_BIRD_001","type":"camera_angle","agents":["storyboarder","art_director"],"camera_angle":"birds_eye","intent":["overview","fate","isolation","pattern","aftermath","choreography"],"pairs_with":["SHOT_XLS_001","ACT_005","EMO_003"]}
```

**Définition.** Caméra à la verticale du sujet, regard à 90° vers le sol.

**Sens produit.** Détachement, regard « divin », destin, plan d'ensemble d'une chorégraphie. Transforme le décor en motif graphique.

**Usages.** Corps étendu au sol (fin de chute, défaite, désespoir) ; personnage seul au milieu d'un carrefour ; deux personnages qui se tournent autour avant un duel ; chambre vue d'en haut pour poser le lieu (case `orienter` originale).

**Prompt (EN).** `top-down bird's-eye view, character lying on the floor seen from directly above, radial composition, floor pattern as graphic shape`

---

### ANG_WORM_001 — Vue ras du sol
`path: 02_angles_camera/vue_ras_du_sol.md`

```meta
{"id":"ANG_WORM_001","type":"camera_angle","agents":["storyboarder","art_director"],"camera_angle":"worms_eye","intent":["impact","speed","threat","scale","dynamism","evasion"],"pairs_with":["ACT_003","ACT_004","BODY_003","COMP_002"]}
```

**Définition.** Caméra posée au sol (ou quasi), regard vers l'avant ou vers le haut.

**Sens produit.** Immersion, échelle exagérée, sensation d'être dans l'action. Les pieds, les débris, le sol deviennent premier plan.

**Usages.**
- Pied qui frappe le sol avant un sprint ; atterrissage d'un saut.
- Esquive : le poing passe au-dessus de la caméra, le corps se penche en arrière.
- Objet tombé au premier plan (indice) avec le personnage flou au fond.
- Point de vue d'un personnage à terre (subjectif).

**Prompt (EN).** `worm's-eye view from ground level, shoe in extreme foreground, debris and dust, character towering in the background, dramatic foreshortening`

---

### ANG_DUTCH_001 — Angle hollandais (horizon incliné)
`path: 02_angles_camera/angle_dutch.md`

```meta
{"id":"ANG_DUTCH_001","type":"camera_angle","agents":["storyboarder"],"camera_angle":"dutch","intent":["unease","madness","chaos","dizziness","speed","impact"],"avoid_when":["calm_scene","used_in_previous_panel"],"pairs_with":["COMP_001","EMO_001","LAY_006"]}
```

**Définition.** Caméra tournée sur son axe : horizon et verticales penchés.

**Sens produit.** Déséquilibre, malaise, folie, chaos, vertige ; en action, sensation de vitesse et de choc.

**Règles.** Inclinaison franche (15–35°) : une inclinaison timide ressemble à une erreur. Combiner avec une case elle-même oblique (case *henkei-goma*) pour amplifier. Basculer l'horizon dans le **sens de la chute** ou du mouvement.

**Dosage.** Effet fort : pas deux fois de suite, pas plus d'une ou deux fois par page sauf séquence de chaos assumée.

**Prompt (EN).** `dutch angle, tilted horizon about 25 degrees, off-balance composition, unsettling atmosphere, slanted panel border`

---

### ANG_POV_001 — Vue subjective
`path: 02_angles_camera/vue_subjective.md`

```meta
{"id":"ANG_POV_001","type":"camera_angle","agents":["director","storyboarder"],"camera_angle":"pov","intent":["empathy","fear","threat","discovery","intimacy","reveal"],"pairs_with":["SHOT_DET_001","LAY_002","EMO_001"]}
```

**Définition.** Le lecteur voit exactement ce que voit un personnage.

**Pourquoi c'est très « manga ».** Les analyses de corpus de Cohn et collègues indiquent que le manga utilise davantage de cases subjectives que les comics occidentaux, et que ces cases sont surtout des détails, des gros plans ou des vues de décor.

**Construction en 2 cases.** (1) gros plan du personnage qui regarde (direction du regard claire) → (2) ce qu'il voit, cadré depuis sa hauteur d'yeux. L'ordre inverse (objet puis réaction) fonctionne aussi pour une révélation.

**Indices visuels de subjectivité.** Mains du personnage au premier plan ; bord flou ou vignettage ; vision troublée (dédoublement, flou) pour malaise ; cadre en forme de judas, de jumelles, d'entrebâillement de porte.

**Usages.** Menace qui s'approche du personnage ; découverte d'un objet ; personnage à terre qui voit l'adversaire au-dessus de lui (subjectif + contre-plongée).

**Prompt (EN).** `first-person point of view, own hands visible at the bottom of the frame, looking at [subject], slight vignette, eye-level of the character`

---

### ANG_FORCE_001 — Perspective forcée (raccourci extrême)
`path: 02_angles_camera/perspective_forcee.md`

```meta
{"id":"ANG_FORCE_001","type":"camera_angle","agents":["storyboarder","art_director","prompter"],"camera_angle":"variable","intent":["impact","speed","power","dynamism"],"avoid_when":["calm_dialogue","character_consistency_critical_and_model_struggles"],"pairs_with":["ACT_003","BODY_002","COMP_002"]}
```

**Définition.** Un membre ou un objet projeté vers la caméra devient énorme par rapport au reste du corps (poing, pied, lame, main tendue). Technique typique des shōnen d'action et des pages d'impact.

**Usages.** Coup de poing vers le lecteur ; main tendue pour attraper / sauver ; pied qui écrase ; doigt accusateur ; épée pointée.

**Règles.**
- Le membre au premier plan et le visage au second plan doivent **tous deux** rester lisibles : point focal sur le contact ou sur le visage, pas les deux à égalité.
- Lignes de vitesse convergeant vers le membre.
- Ne pas couper le membre au poignet par le bord de case.

**Note génération.** Les modèles de diffusion gèrent mal les raccourcis extrêmes ; utiliser un ControlNet de pose / profondeur ou une esquisse 3D de référence (poseur 3D) pour ces cases-là. Prévoir plusieurs essais.

**Prompt (EN).** `extreme foreshortening, fist punching toward the viewer, fist huge in the foreground, face smaller behind it, radial speed lines converging on the fist, dynamic perspective`


---

## 03_corps_et_gestes

> Le corps raconte avant le visage. Pour chaque case, le metteur en scène doit pouvoir dire **quelle partie du corps porte l'émotion ou l'action**.

### BODY_001 — Mains et doigts
`path: 03_corps_et_gestes/mains_et_doigts.md`

```meta
{"id":"BODY_001","type":"body_gesture","agents":["director","storyboarder","art_director"],"shot_scale":"detail","attention_frame":"micro","intent":["hesitation","tension","anger","fear","decision","intimacy","grab"],"pairs_with":["SHOT_DET_001","BODY_007","EMO_003"]}
```

**Pourquoi.** Les mains sont le second visage. Elles montrent ce que le personnage cache (sourire au visage, poing serré sous la table).

**Répertoire geste → sens.**

| Geste | Sens fréquent |
|---|---|
| Poing qui se serre, jointures blanches | Colère contenue, détermination |
| Doigts qui tremblent | Peur, choc, épuisement |
| Main qui s'arrête à quelques centimètres d'un objet/d'une personne | Hésitation, désir retenu |
| Doigts qui lâchent un objet (en 2–3 cases) | Renoncement, choc, mort |
| Ongles qui griffent une surface | Douleur, rage, désespoir |
| Main ouverte tendue | Appel, sauvetage, offre |
| Main posée sur l'épaule (entrant dans le champ) | Soutien, ou menace si le visage est caché |
| Mains qui s'agrippent au tissu (vêtement, drap) | Angoisse, retenue |
| Doigt pointé | Accusation, ordre, découverte |
| Mains qui pianotent, tripotent | Nervosité, impatience |

**Règles.** Identifier à qui appartient la main (manche, bague, gant, couleur de peau, bandage). Angle de trois-quarts plutôt que de profil plat. Fond simple ou effets.

**Prompt (EN).** `close-up of trembling fingers about to touch a door handle, hesitation, sleeve with [identifying detail], soft background, manga ink`

---

### BODY_002 — Bras et épaules
`path: 03_corps_et_gestes/bras_et_epaules.md`

```meta
{"id":"BODY_002","type":"body_gesture","agents":["storyboarder","art_director"],"intent":["anticipation","impact","defense","power","effort"],"pairs_with":["ACT_001","ACT_003","ANG_FORCE_001"]}
```

**Ce qu'ils racontent.**
- **Épaule qui pivote / se ramène en arrière** : armé d'un coup (anticipation).
- **Bras tendu qui traverse le cadre en diagonale** : vitesse, portée.
- **Avant-bras en garde, croisés** : défense, blocage, encaissement.
- **Épaules relevées et rentrées** : peur, froid, protection.
- **Épaules basses** : abattement, fatigue, défaite.
- **Biceps contracté, veines** : effort extrême, retenue.

**Cadrages forts.** Bras au premier plan en amorce, le reste du corps au second plan ; avant-bras qui bloque cadré en gros plan au point de contact (les deux bras qui se croisent forment un X → impact).

**Prompt (EN).** `forearm block, two forearms colliding in an X shape at the center, impact burst, shockwave lines, close-up on the point of contact`

---

### BODY_003 — Jambes et pieds
`path: 03_corps_et_gestes/jambes_et_pieds.md`

```meta
{"id":"BODY_003","type":"body_gesture","agents":["storyboarder","art_director"],"intent":["anticipation","speed","stability","fear","entrance","impact"],"pairs_with":["ANG_WORM_001","ACT_001","ACT_002"]}
```

**Ce qu'ils racontent.**
- **Pieds ancrés, écartés** : stabilité, maîtrise, défi.
- **Talon qui pivote / pointe qui s'enfonce** : départ imminent (le « clic » avant le sprint).
- **Genou qui fléchit** : préparation de saut, ou faiblesse (genou qui cède).
- **Pied qui glisse / dérape** : perte d'équilibre → chute.
- **Pied qui recule d'un pas** : peur, recul, hésitation (orienté contre le sens de lecture).
- **Pas qui entre dans le cadre** (seul le pied) : arrivée de quelqu'un, suspense.
- **Pied qui écrase un objet** : domination, cruauté, décision.

**Cadrage roi.** Ras du sol, pied au premier plan, poussière ou fissures autour. Excellent remplaçant d'un plan en pied d'entrée.

**Prompt (EN).** `ground-level close-up of a sneaker digging into the asphalt, heel lifting, dust kicking up, ready to sprint, speed lines`

---

### BODY_004 — Torsion du buste et contrapposto
`path: 03_corps_et_gestes/torsion_du_buste.md`

```meta
{"id":"BODY_004","type":"body_gesture","agents":["art_director","prompter"],"intent":["dynamism","anticipation","evasion","throw","tension"],"pairs_with":["BODY_006","ACT_004","ACT_006"]}
```

**Principe.** Un corps vivant n'est jamais aligné : épaules et bassin tournent dans des directions différentes. La torsion crée du ressort ; l'absence de torsion fait « mannequin ».

**Usages.** Armé d'un coup (buste tourné en arrière, bassin vers la cible) ; esquive (buste qui bascule en arrière ou de côté) ; projection (rotation complète autour de l'axe) ; regard par-dessus l'épaule (tension, méfiance).

**Règles.** Indiquer dans la fiche de case : direction des épaules, direction du bassin, direction du regard. Les trois ne doivent pas être identiques dans une case d'action.

**Prompt (EN).** `dynamic twisting torso, shoulders rotated opposite to hips, coiled like a spring, looking back over the shoulder, contrapposto`

---

### BODY_005 — Expressions faciales (au-delà du visage frontal)
`path: 03_corps_et_gestes/expressions_faciales.md`

```meta
{"id":"BODY_005","type":"body_gesture","agents":["art_director","prompter"],"shot_scale":"close_up","intent":["emotion","reaction","surprise","fear","anger","sadness"],"pairs_with":["SHOT_CU_001","EMO_001","EMO_002","EMO_003","EMO_004"]}
```

**Six variables à préciser** (au lieu de « surpris » ou « triste ») : sourcils (forme, hauteur), paupières (ouverture), pupilles (taille, reflets), bouche (ouverte, crispée, tremblante), tête (inclinaison, rotation), effets (sueur, larmes, ombre sur les yeux, lignes).

**Codes manga utiles.**
- Pupilles qui rétrécissent jusqu'au point + absence de reflet : choc, peur.
- Yeux masqués par l'ombre ou le reflet des lunettes : menace, secret, colère froide.
- Ombre sur le haut du visage (bande d'ombre hachurée ou tramée, jamais un aplat noir plein) : intention sombre, détermination glaciale.
- Lignes verticales qui tombent du haut de la case (*tare-sen*) : abattement, malaise, gêne.
- Hachures obliques sur les joues : gêne, rougeur.
- Goutte de sueur : embarras, nervosité.
- Veine en croix sur le front : colère comique.

**Angle.** Varier : profil, trois-quarts, vue de dessous, tête baissée cadrée de dessus. Un visage frontal à hauteur d'yeux est la valeur à justifier.

**Note public jeune.** Pour un manga pédagogique destiné aux enfants, privilégier les codes lisibles et non effrayants (gouttes, lignes, symboles) plutôt que les ombres menaçantes.

---

### BODY_006 — Silhouettes, poses et ligne d'action
`path: 03_corps_et_gestes/silhouettes_et_poses.md`

```meta
{"id":"BODY_006","type":"body_gesture","agents":["art_director","prompter","qa"],"intent":["readability","dynamism","pose","power"],"pairs_with":["COMP_004","BODY_004","SHOT_MFS_001"]}
```

**Test de la silhouette.** Si on remplit le personnage en noir, l'action doit rester lisible. Les ateliers de storyboard enseignent cette règle : une pose doit se reconnaître même détails effacés. *Framed Ink* consacre une partie entière à la silhouette d'ensemble (tête, corps) comme outil d'expression.

**Ligne d'action.** Une courbe unique (C ou S) qui traverse le corps de la tête au pied d'appui. Courbe franche = énergie. Droite verticale = rigidité, solennité, choc. Courbe dirigée vers la gauche (lecture `rtl`) = progression.

**Règles.**
- Écarter les membres du tronc pour que les bras ne se perdent pas dans la masse du corps.
- Éviter la symétrie gauche/droite des bras et jambes (pose « mannequin »).
- Exagérer : en manga, la pose est plus marquée que la réalité.
- Une pose iconique (arrêt, *mie*) = case plus grande, fond simplifié.

**Prompt (EN).** `strong readable silhouette, clear C-shaped line of action, limbs separated from the torso, asymmetrical pose, exaggerated gesture`

---

### BODY_007 — Gestes interrompus et micro-mouvements
`path: 03_corps_et_gestes/gestes_interrompus.md`

```meta
{"id":"BODY_007","type":"body_gesture","agents":["director","storyboarder"],"intent":["hesitation","tension","time_slowdown","decision","intimacy","silence"],"pairs_with":["BODY_001","FUND_003","EMO_007"]}
```

**Principe.** Un geste commencé puis arrêté raconte un conflit intérieur sans un mot. C'est la base des scènes de tension et de romance.

**Exemples.**
- Main qui se lève pour frapper / toucher, puis s'arrête en l'air.
- Bouche qui s'ouvre pour parler, puis se ferme (bulle vide ou « … »).
- Pas en avant, puis pas en arrière.
- Doigt au-dessus du bouton « envoyer ».

**Découpage type (3 cases `moment_to_moment`).** Geste qui commence (petite case) → geste suspendu (case étroite, silence) → soit la réaction d'en face, soit la main qui retombe (`release`).

**Règle.** Ne pas expliquer le geste par une bulle de pensée : l'image suffit.


---

## 04_action_et_mouvement

> Une action se décompose en **temps** : préparation → déclenchement → contact → conséquence. Chaque temps peut avoir son cadrage. Le défaut à éviter : trois plans moyens qui montrent « le combat en général ».

### ACT_001 — Anticipation (l'instant avant)
`path: 04_action_et_mouvement/anticipation.md`

```meta
{"id":"ACT_001","type":"action_beat","agents":["director","storyboarder"],"narrative_role":"initial","intent":["anticipation","tension","power"],"pairs_with":["BODY_002","BODY_003","FUND_002","ACT_008"]}
```

**Principe.** Le mouvement est plus fort quand on voit le ressort se tendre. C'est le temps `initial` de Cohn. En animation, c'est l'« anticipation » ; en manga, c'est souvent la case **la plus silencieuse** avant la plus bruyante.

**Images d'anticipation.**
- Épaule tirée en arrière, poing armé à hauteur de hanche.
- Genoux fléchis, poids sur l'avant du pied.
- Main qui se pose sur la poignée de l'arme / le sol.
- Regard qui se fixe (très gros plan sur les yeux).
- Poussière qui se soulève autour des pieds, cheveux et vêtements qui s'agitent avant le mouvement.

**Cadrages recommandés.** Détail (pied, main), très gros plan sur les yeux, contre-plongée sur le corps entier ramassé. Case **plus petite** que la case de déclenchement qui suit.

**Prompt (EN).** `moment before the strike, coiled body, fist pulled back at the hip, weight on the front foot, dust rising around the feet, intense focused eyes, tense stillness`

---

### ACT_002 — Accélération et vitesse
`path: 04_action_et_mouvement/acceleration.md`

```meta
{"id":"ACT_002","type":"action_beat","agents":["storyboarder","art_director","prompter"],"intent":["speed","chase","dynamism"],"motion_level":"high","pairs_with":["ACT_009","COMP_001","LAY_006"]}
```

**Outils de vitesse.**
1. **Composition diagonale** : le sujet et ses lignes traversent la case en diagonale (→ COMP_001).
2. **Case large et étroite** dans le sens du mouvement, ou case oblique.
3. **Lignes de vitesse** (*speed-sen*) parallèles au déplacement ; fond supprimé ou réduit aux lignes (→ ACT_009).
4. **Flou / traînée** sur les membres, images multiples (après-images).
5. **Sujet coupé par le bord de case** : il sort déjà du cadre.
6. **Décor déformé** : objets qui s'envolent, cheveux et vêtements plaqués en arrière.

**Deux familles de lignes.**
- *Lignes de mouvement* : derrière le sujet, fond fixe → le sujet bouge.
- *Lignes de défilement* : partout sur le fond, sujet net → la caméra suit le sujet (effet travelling).

**Direction.** Dans le sens de lecture = progression ; contre le sens de lecture = recul, fuite, poussée subie.

**Prompt (EN).** `dynamic diagonal composition, character dashing across the panel, horizontal speed lines replacing the background, afterimages of legs, hair and clothes blown back, motion blur`

---

### ACT_009 — Lignes d'effet (*kōka-sen*) : catalogue
`path: 04_action_et_mouvement/acceleration.md`

```meta
{"id":"ACT_009","type":"action_beat","agents":["art_director","prompter","lettering"],"intent":["speed","surprise","impact","emphasis","sadness","fear","comedy_beat"],"pairs_with":["ACT_002","ACT_003","EMO_004"]}
```

Les *kōka-sen* (effets de traits) sont tracés sur le fond ou au premier plan pour exprimer un mouvement, une émotion ou une ambiance. Catalogue utilisable par le directeur artistique et par la couche vectorielle de lettrage/effets :

| Nom | Japonais | Description | Usage |
|---|---|---|---|
| Lignes de mouvement | 動線 *dōsen* | Traits suivant la trajectoire | Trajectoire d'un coup, d'un objet, mouvement de tête |
| Lignes de vitesse | スピード線 | Traits parallèles | Vitesse ; venues du bas en verticales : ferveur, exaltation |
| Lignes de tremblement | 揺れ線 *yure-sen* | Traits courts autour du sujet (courbes si souple, droits si rigide) | Vibration, tremblement de peur ou d'excitation |
| Lignes de concentration | 集中線 *shūchū-sen* | Traits convergeant du bord vers un point | Attirer l'œil, réalisation, activation d'un pouvoir, objet qui fonce vers le lecteur ; une étude japonaise a montré qu'elles renforcent la perception de la **surprise** |
| Lignes inquiétantes | おどろ線 *odoro-sen* | Variante irrégulière et sombre des lignes de concentration | Malaise, menace, colère sourde |
| Rayons | 放射線 *hōsha-sen* | Traits rayonnant **depuis** le personnage | Joie, enthousiasme, aura positive |
| Lignes tombantes | タレ線 *tare-sen* | Verticales qui pendent du haut de la case | Abattement, déprime, choc, gêne |
| Hachures-cordes | ナワアミ *nawa-ami* | Trame croisée en motif de cordes | Inquiétude, angoisse |
| Flash noir | ベタフラッシュ | Explosion de traits noirs autour d'un centre blanc | Choc, impact, révélation brutale |

**Règle.** Une ligne d'effet par intention ; ne pas superposer concentration + vitesse + tremblement dans la même case. Le centre des lignes de concentration = le point focal (→ FUND_004).

**Note pipeline.** Ces effets peuvent être générés en vectoriel par la couche de lettrage (contrôle total de centre, densité, épaisseur) plutôt que demandés au modèle de diffusion, qui les rend souvent de façon approximative. Si on les demande au modèle, garder le fond simple.

---

### ACT_003 — Impact
`path: 04_action_et_mouvement/impact.md`

```meta
{"id":"ACT_003","type":"action_beat","agents":["director","storyboarder","art_director"],"narrative_role":"peak","intent":["impact","shock","power","peak"],"motion_level":"high","pairs_with":["FUND_002","ANG_FORCE_001","LAY_005","ACT_009"]}
```

**Principe.** L'impact est le `peak`. Il mérite la case la plus grande ou la plus marquée de la séquence.

**Façons de montrer un impact.**
1. **Le contact lui-même** en gros plan : poing contre joue, déformation du visage, onde de choc.
2. **L'impact abstrait** : case presque vide, flash noir, onomatopée géante — Cohn montre qu'une telle case peut remplacer le pic sans perte de compréhension.
3. **La conséquence immédiate** : corps qui part en arrière, mur qui se fissure, débris.
4. **Le témoin** : visage d'un spectateur qui sursaute (`subject_to_subject`), l'impact a lieu hors champ.
5. **L'arrêt sur image** : tout est figé, gouttes et débris en suspension (ralenti).

**Composition.** Perspective forcée, contre-plongée ou ras du sol, case à fond perdu ou découpée en éclats, onomatopée intégrée à la composition (elle fait partie du dessin, elle suit la direction de la force).

**À éviter.** Impact en plan moyen à hauteur d'yeux ; impact de même taille que la case d'anticipation.

**Prompt (EN).** `moment of impact, fist connecting with the jaw, face distorted by the blow, shockwave rings, flying sweat and debris frozen in mid-air, extreme low angle, black flash burst background`

---

### ACT_004 — Esquive
`path: 04_action_et_mouvement/esquive.md`

```meta
{"id":"ACT_004","type":"action_beat","agents":["storyboarder","art_director"],"intent":["evasion","speed","tension","skill"],"pairs_with":["BODY_004","ANG_WORM_001","COMP_002"]}
```

**Principe.** Une esquive se lit par la **relation** entre l'attaque et le corps qui s'en écarte. Les deux doivent être dans le cadre.

**Cadrages qui marchent.**
- **Ras du sol** : le poing/la lame traverse le haut du cadre, le buste bascule en arrière vers le bas.
- **Plan rapproché oblique** : le poing au premier plan, la tête qui passe juste à côté, quelques mèches coupées qui volent.
- **Vue de dessus** : deux trajectoires qui se croisent sans se toucher.
- **Après-image** : la silhouette fantôme à l'endroit où était le personnage, le vrai corps déjà ailleurs.

**Ligne d'action.** Le corps forme une courbe **opposée** à la trajectoire de l'attaque.

**Prompt (EN).** `narrow dodge, enemy fist passing inches from the face in the foreground, torso bending backward in a strong curve, a few strands of hair cut and floating, low oblique angle`

---

### ACT_005 — Chute
`path: 04_action_et_mouvement/chute.md`

```meta
{"id":"ACT_005","type":"action_beat","agents":["storyboarder"],"intent":["fall","defeat","danger","vertigo","comedy_beat"],"pairs_with":["ANG_BIRD_001","ANG_HIGH_001","LAY_006"]}
```

**Décomposition.** Déséquilibre (pied qui glisse, détail) → corps en l'air (case verticale, dutch angle) → contact au sol (impact) → corps au sol (plongée/zénithale, `release`).

**Cadrages.** Case **haute et étroite** pour la chute verticale ; vue zénithale sur le corps au sol ; vue subjective de celui qui tombe (le sol qui monte) ; plongée depuis le haut d'où il est tombé (vertige).

**Comédie.** La chute comique gagne à être montrée en **une** case de résultat (personnage écrasé, jambes en l'air) après une case d'avant.

**Prompt (EN).** `tall vertical panel, character falling backward through the air, dutch angle, arms flailing, objects falling with them, ground far below`

---

### ACT_006 — Projection / saisie
`path: 04_action_et_mouvement/projection.md`

```meta
{"id":"ACT_006","type":"action_beat","agents":["director","storyboarder"],"intent":["grab","throw","power","action_clarity"],"pairs_with":["BODY_001","BODY_004","ACT_003"]}
```

**Lisibilité d'abord.** Une projection est un mécanisme : saisie → levier → rotation → réception. Le lecteur doit comprendre **comment** ça marche.

**Découpage type.**
1. Détail : la main qui se referme sur le poignet / le col.
2. Plongée oblique : la torsion du lanceur, le déséquilibre de l'autre (deux silhouettes en spirale).
3. Case large, grand angle : le corps en l'air, arc de trajectoire en lignes de mouvement.
4. Impact au sol vu de haut ou ras du sol (débris, fissures).
5. Détail des pieds du vainqueur bien ancrés, ou visage calme (`release`).

**Prompt (EN).** `judo throw, character twisting and pulling the opponent over the shoulder, opponent's body in a high arc, motion lines tracing the arc, high oblique angle`

---

### ACT_007 — Mouvement hors champ
`path: 04_action_et_mouvement/mouvement_hors_champ.md`

```meta
{"id":"ACT_007","type":"action_beat","agents":["director","storyboarder"],"intent":["mystery","speed","suspense","violence_softened","impact"],"pairs_with":["SHOT_PART_001","ACT_003","EMO_001"]}
```

**Principe.** Ne pas montrer le mouvement, montrer ses traces. Le lecteur « réalise » l'action dans l'intervalle entre les cases (c'est l'ellipse que McCloud appelle *closure*).

**Techniques.**
- Montrer l'avant et l'après, pas le pendant (le personnage est debout / il est contre le mur).
- Montrer l'effet sur un objet : vase qui tombe, rideaux qui bougent, verre qui tremble.
- Montrer l'ombre ou le son (onomatopée seule dans une case de décor).
- Montrer la réaction d'un témoin.
- Faire sortir le sujet du cadre (seul un pied, une écharpe reste visible).

**Quand l'utiliser.** Vitesse surhumaine (trop rapide pour être vue), violence à atténuer (public jeune), suspense, économie de cases.

---

### ACT_008 — Décomposition d'une action en cases
`path: 04_action_et_mouvement/decomposition_action.md`

```meta
{"id":"ACT_008","type":"action_beat","agents":["director","storyboarder","qa"],"intent":["action_clarity","choreography","pacing"],"pairs_with":["FUND_002","FUND_003","LAY_005","EX_002"]}
```

**Méthode en 5 étapes pour le storyboarder.**
1. Écrire l'action en verbes simples (« esquive, saisit, projette »).
2. Pour chaque verbe, identifier les **temps** : anticipation / déclenchement / contact / conséquence.
3. Choisir les temps à montrer (rarement tous) : en général **1 temps sur 2** pour une action rapide, tous les temps pour un ralenti dramatique.
4. Attribuer à chaque temps retenu : rôle Cohn, échelle, angle, partie du corps focale. Interdire deux échelles identiques consécutives sauf intention.
5. Placer une case de **géographie** (plan d'ensemble) au début ou au milieu si l'action dépasse 4 cases.

**Grille de densité.**

| Effet voulu | Cases par action | Transitions |
|---|---|---|
| Fulgurant | 1–2 (avant / après) | `action_to_action` + hors champ |
| Lisible standard | 3–4 | `action_to_action` + 1 `subject_to_subject` |
| Ralenti épique | 5–7 | `moment_to_moment` + `prolongation` |

**Vérification.** Lire uniquement les cases (sans texte) : l'action doit être compréhensible. Sinon, il manque un temps ou la géographie.


---

## 05_composition

> La composition est l'organisation **à l'intérieur** de la case. *Framed Ink* (Mateu-Mestre) l'aborde par paires de contrastes qui portent chacune un message : ordre / chaos, complexe / simple, grand / petit, anguleux / courbe, et par l'usage de l'espace négatif. Ces paires sont reprises ci-dessous comme leviers que le directeur artistique peut actionner.

### COMP_001 — Diagonales et lignes de force
`path: 05_composition/diagonales_et_lignes_de_force.md`

```meta
{"id":"COMP_001","type":"composition","agents":["art_director","prompter"],"composition":"strong_diagonal","intent":["dynamism","speed","instability","conflict","impact"],"avoid_when":["calm_establisher","peaceful_intimacy"],"pairs_with":["ACT_002","ANG_DUTCH_001","COMP_006"]}
```

**Principe.** Horizontales = repos, stabilité. Verticales = dignité, rigidité, élévation. **Diagonales = mouvement, déséquilibre, conflit.**

**Leviers.**
- Aligner le corps, l'arme, le regard sur une diagonale du cadre.
- Diagonale montante (dans le sens de lecture) = élan, triomphe. Descendante = chute, défaite.
- Deux diagonales opposées qui se croisent = affrontement (deux personnages qui chargent l'un vers l'autre).
- Lignes du décor (rambardes, routes, rayons de lumière) utilisées comme lignes de force vers le point focal.

**Contraste ordre / chaos.** Une scène calme se compose de lignes droites et parallèles ; quand le chaos arrive, les lignes se brisent et s'entrecroisent. Le passage de l'un à l'autre est en soi un signal narratif.

**Prompt (EN).** `strong diagonal composition, character and weapon aligned along the frame diagonal, converging leading lines toward the focal point`

---

### COMP_002 — Profondeur et premier plan
`path: 05_composition/profondeur_et_premier_plan.md`

```meta
{"id":"COMP_002","type":"composition","agents":["art_director","prompter","qa"],"depth":"layered","intent":["depth","immersion","relation","tension","reveal"],"pairs_with":["SHOT_PART_001","SHOT_OTS_001","ANG_FORCE_001"]}
```

**Principe.** Une image « plate » a tout sur un même plan. Une image vivante a au moins **trois plans** : premier plan, plan médian, arrière-plan.

**Techniques.**
- **Amorce sombre au premier plan** (épaule, objet, cadre de porte, feuillage) : profondeur immédiate et point de vue.
- **Personnages à des distances différentes** de la caméra au lieu d'être alignés.
- **Échelle exagérée** : objet proche énorme, personnage lointain minuscule.
- **Valeurs** : premier plan sombre, fond clair (ou l'inverse) — perspective atmosphérique.
- **Recouvrement** : un élément en cache partiellement un autre.

**Pour le contrôleur qualité.** Si `depth = flat` pour plus de la moitié des cases d'une page, signaler.

**Prompt (EN).** `layered composition, dark silhouette of [object] in the extreme foreground, character in the midground, detailed background, strong depth, overlapping elements`

---

### COMP_003 — Espace négatif
`path: 05_composition/espace_negatif.md`

```meta
{"id":"COMP_003","type":"composition","agents":["director","art_director"],"composition":"negative_space","intent":["isolation","silence","anticipation","sadness","threat","atmosphere"],"pairs_with":["SHOT_XLS_001","EMO_003","EMO_007"]}
```

**Principe.** Le vide est un sujet. *Framed Ink* traite explicitement l'usage de l'espace négatif comme un outil de message.

**Usages.**
- **Solitude** : petit personnage, grand vide autour.
- **Attente / menace** : espace vide dans la direction du regard, ou derrière le personnage (quelque chose va surgir).
- **Silence** : case blanche ou noire avec un seul élément.
- **Respiration** de page après une séquence chargée.

**Règle de direction.** Laisser de l'espace **devant** le regard = attente, ouverture. Le sujet collé au bord vers lequel il regarde = blocage, enfermement, malaise.

**Prompt (EN).** `vast negative space, small lone figure placed at the bottom corner, empty white sky occupying most of the panel, minimalist`

---

### COMP_004 — Silhouettes, contraste et masses noires
`path: 05_composition/silhouettes_et_contraste.md`

```meta
{"id":"COMP_004","type":"composition","agents":["art_director","prompter"],"intent":["readability","threat","mystery","emphasis","drama"],"pairs_with":["BODY_006","FUND_004","EMO_005"]}
```

**Principe.** En noir et blanc, la composition est d'abord une répartition de **masses de valeur** (noir, gris trame, blanc). *Framed Ink* insiste sur l'éclairage, le clair-obscur et la lisibilité des silhouettes.

**Leviers.**
- **Silhouette noire sur fond clair** : lisibilité maximale, mystère (personnage non identifié), menace.
- **Contre-jour** : héroïsme, apparition.
- **Grand aplat noir (*beta*)** : poids, nuit, émotion sombre, menace.
- **Clair-obscur** (lumière latérale dure) : drame, dualité morale.
- **Regrouper les valeurs** : 2 ou 3 grandes zones plutôt qu'un patchwork de gris.

**Pour le point focal.** Le contraste le plus fort de la case doit se trouver sur le point focal.

**Note génération.** Préciser dans le prompt la répartition des noirs (`large black mass in the lower half`, `backlit silhouette`) ; sinon les modèles produisent des valeurs moyennes uniformes.

**Prompt (EN).** `high contrast black and white, backlit character as a solid black silhouette against a bright white background, heavy black ink masses, chiaroscuro`

---

### COMP_005 — Cadres dans le cadre
`path: 05_composition/cadres_dans_le_cadre.md`

```meta
{"id":"COMP_005","type":"composition","agents":["art_director","storyboarder"],"composition":"frame_in_frame","intent":["isolation","surveillance","entrapment","voyeurism","focus"],"pairs_with":["ANG_POV_001","SHOT_PART_001","EMO_003"]}
```

**Principe.** Un élément du décor (porte, fenêtre, miroir, écran, embrasure, bras d'un autre personnage) encadre le sujet une deuxième fois.

**Sens produit.** Enfermement, observation (on épie), isolement, focalisation de l'attention.

**Exemples.** Personnage vu à travers une porte entrouverte (on espionne) ; reflet dans un miroir brisé (identité fracturée) ; visage dans l'écran d'un téléphone ; personnage encadré par les jambes écartées d'un adversaire (domination).

**Prompt (EN).** `frame within a frame, character seen through a half-open doorway, dark door edges framing the subject, voyeuristic viewpoint`

---

### COMP_006 — Compositions asymétriques et formes de base
`path: 05_composition/compositions_asymetriques.md`

```meta
{"id":"COMP_006","type":"composition","agents":["art_director"],"composition":"asymmetric_weight","intent":["tension","dynamism","hierarchy","balance"],"pairs_with":["COMP_001","FUND_004","ANTI_004"]}
```

**Principe.** Le centrage symétrique est stable et solennel ; il convient aux confrontations frontales ou aux images iconiques — mais devient monotone s'il est systématique.

**Leviers.**
- **Règle des tiers** : sujet sur une ligne de tiers, regard vers le côté le plus vaste.
- **Poids déséquilibré** : grande masse d'un côté, petit élément important de l'autre (tension).
- **Triangle** : trois personnages ou trois points d'intérêt en triangle, pointe en haut = stabilité, pointe en bas = instabilité.
- **Grand / petit** : opposer un élément massif à un élément minuscule pour dire la hiérarchie (pouvoir, menace).
- **Anguleux / courbe** : formes anguleuses = danger, agressivité ; formes courbes = douceur, sécurité. Utile pour designer un décor ou un antagoniste.

**Prompt (EN).** `asymmetrical composition, character on the left third, large empty space to the right, off-balance visual weight`


---

## 06_decoupage_manga

> Le découpage (*koma-wari*) décide de la taille, de la forme et de l'ordre des cases. Le cours de mangaka de Shōgakukan distingue clairement deux décisions : le **découpage** (taille, forme, ordre des cases dans la page) et la **composition** (ce qu'on dessine dans chaque case : point de vue, tailles relatives). Les deux se décident ensemble, à partir de ce que la case doit exprimer.

### LAY_001 — Ouverture de page et de scène
`path: 06_decoupage_manga/ouverture_de_page.md`

```meta
{"id":"LAY_001","type":"layout","agents":["storyboarder"],"intent":["establish_place","atmosphere","hook"],"pairs_with":["SHOT_XLS_001","FUND_002","LAY_002"]}
```

**Position stratégique.** La première case lue d'une page (en haut à droite en `rtl`) arrête l'œil. En double page, la première case de la page de droite et la première de la page de gauche sont deux points d'entrée.

**Ouvrir une scène : options autres que le plan moyen.**
1. **Orienter atmosphérique** : décor sans personnage (`amorphic`), heure du jour, météo.
2. **Détail intrigant** : objet ou geste qui pose une question (une main qui écrit, un réveil qui sonne).
3. **In medias res** : on démarre sur l'action ou une réplique forte, la géographie arrive après.
4. **Vue zénithale** du lieu.
5. **Plan d'ensemble à fond perdu** (*tachikiri*) : case qui déborde jusqu'au bord du papier. Le cours Shōgakukan note qu'elle donne plus de place pour le décor et les personnages sans gêner la lecture, et la recommande pour l'arrivée d'un nouveau personnage.

**Taille.** Si le lieu est **important** pour l'histoire, sa case doit être grande et contenir le personnage dans le décor (exemple du cours : une petite case de mer passe inaperçue ; une grande case avec le personnage qui regarde la mer reste en mémoire). Si le lieu n'est qu'une transition, une petite case suffit.

**Règle.** Ne pas mettre de texte à fond perdu côté bord : la bulle doit rester dans la zone imprimable. Éviter le fond perdu côté reliure (*nodo*), difficile à lire.

---

### LAY_002 — Révélations et tournes de page
`path: 06_decoupage_manga/revelations.md`

```meta
{"id":"LAY_002","type":"layout","agents":["director","storyboarder","qa"],"intent":["reveal","surprise","shock","hook","suspense"],"pairs_with":["SHOT_PART_001","SHOT_XCU_001","ANG_POV_001","EX_003"]}
```

**La tourne de page.** En édition papier, le lecteur ne voit pas la page suivante avant de tourner. On place donc la **question** en bas de la page de gauche (dernière case lue avant de tourner, en `rtl`), et la **réponse** en première case de la page suivante. Cette case de révélation après la tourne est appelée *mekuri-goma* (« case de la tourne »). Le procédé est aussi enseigné dans les manuels de shōjo : accrocher le lecteur en bas de page pour qu'il se demande « et après ? ».

**Règle d'or.** Ne jamais révéler sur la même double page que la mise en place : le lecteur voit la réponse du coin de l'œil avant de lire la question.

**Construction d'une révélation (4 temps).**
1. **Préparation** : réaction d'un personnage qui voit quelque chose (on ne voit pas quoi). Cadrage serré sur le regard, ou de dos.
2. **Retardement** (`prolongation`) : détail (main qui tremble, très gros plan sur la pupille), réplique coupée « C'est… ».
3. **Tourne de page.**
4. **Révélation** : grande case, souvent pleine page ou bande pleine largeur, angle fort.

**Variantes sans tourne (web, défilement vertical).** Le webtoon perd la tourne de page ; la remplacer par un **grand espace vide** (défilement) avant l'image de révélation.

**Révéler par le cadrage.** Élargir progressivement : très gros plan → gros plan → plan d'ensemble révélant le contexte (« zoom arrière » de la révélation). Ou l'inverse : plan large innocent → détail inquiétant.

---

### LAY_003 — Scènes de dialogue
`path: 06_decoupage_manga/scenes_de_dialogue.md`

```meta
{"id":"LAY_003","type":"layout","agents":["director","storyboarder","qa"],"intent":["dialogue","relation","tension","intimacy","explanation"],"pairs_with":["SHOT_OTS_001","FUND_003","EX_001","ANTI_001"]}
```

**Problème.** Le dialogue est la cause n°1 des pages en plans moyens frontaux répétés.

**Boîte à outils pour un dialogue vivant.**
1. **Établir puis découper** : 1 case d'ensemble qui situe les interlocuteurs, puis champ / contrechamp avec amorce (→ SHOT_OTS_001).
2. **Faire varier l'échelle avec l'intensité** : plus l'échange monte, plus on se rapproche (plan moyen → rapproché → gros plan → très gros plan sur la réplique-clé).
3. **Faire agir les personnages** : ils cuisinent, marchent, rangent, manipulent un objet. L'action secondaire donne des inserts naturels.
4. **Montrer l'écoute** : la case de celui qui écoute est souvent plus forte que celle de celui qui parle (bulle de l'autre qui « entre » dans la case de celui qui réagit).
5. **Inserts `aspect_to_aspect`** : objet du décor, mains, tasse qui refroidit, pendant les silences.
6. **Bulle hors champ** : la voix vient d'un personnage absent de la case (la queue de bulle pointe hors cadre).
7. **Changer d'angle quand le rapport de force change** : celui qui prend le dessus passe en contre-plongée ; on peut franchir l'axe des 180° à ce moment précis.
8. **Silence** : une case muette au cœur d'un dialogue est un événement.

**Seuils de départ.** Max 3 répliques par case ; max 2 cases consécutives avec la même échelle ET le même angle ; au moins 1 case non-visage par tranche de 4 cases de dialogue.

**Manga pédagogique (explication).** Quand un personnage explique un concept, illustrer **l'objet de l'explication** (schéma, objet, métaphore visuelle, vue imaginaire) plutôt que de montrer l'explicateur parler en plan moyen. Alterner : explicateur → visualisation → réaction de l'élève.

---

### LAY_004 — Scènes de tension et de suspense
`path: 06_decoupage_manga/scenes_de_tension.md`

```meta
{"id":"LAY_004","type":"layout","agents":["director","storyboarder"],"intent":["tension","suspense","fear","anticipation","silence"],"pairs_with":["FUND_003","BODY_007","EMO_001","EMO_007"]}
```

**Mécanique.** La tension naît de l'**étirement du temps** avant un événement attendu.

**Outils.**
- Petites cases régulières de même taille, rapprochées (compression, battement d'horloge).
- `moment_to_moment` : détails successifs (goutte de sueur, poignée qui tourne, pas dans le couloir).
- Alternance montée parallèle (`subject_to_subject`) : menace qui approche / victime qui ne sait pas.
- Peu ou pas de texte ; onomatopées discrètes (tic-tac, pas, respiration).
- Cadrages serrés + vue subjective + hors champ.
- Cases qui **rétrécissent** progressivement, puis une case qui **explose** (relâchement) au moment de l'événement.

**À éviter.** Révéler la menace trop tôt ; casser la tension par une case large au milieu.

---

### LAY_005 — Scènes de combat
`path: 06_decoupage_manga/scenes_de_combat.md`

```meta
{"id":"LAY_005","type":"layout","agents":["director","storyboarder","qa"],"intent":["action_clarity","impact","speed","choreography"],"pairs_with":["ACT_008","ACT_003","EX_002","ANTI_003"]}
```

**Structure d'un échange.** Géographie (plan d'ensemble, positions) → anticipation (détail) → attaque (diagonale, case oblique) → contact (`peak`, grande case) → conséquence (corps projeté, débris) → réaction / relance.

**Principes de découpage.**
- **Varier l'échelle à chaque temps** : jamais deux temps consécutifs à la même échelle.
- **Une case maîtresse par page** pour le coup le plus important (case la plus grande, éventuellement à fond perdu ou en double page pour l'apogée du combat).
- **Cases obliques et trapézoïdales** pour les moments de mouvement violent (le cours Shōgakukan montre la même action en case rectangulaire et en case oblique : l'oblique a nettement plus de force) — mais avec parcimonie.
- **Bords de case brisés** : un membre ou une onde de choc qui déborde de la case = puissance.
- **Directions cohérentes** : garder chaque combattant du même côté (axe des 180°) pendant un échange ; inverser volontairement quand l'avantage change de camp.
- **Respirations** : une case de visage (fatigue, détermination) ou de témoin entre deux échanges.
- Réserver les **pages pleines et doubles pages** à l'apogée ; le cours Shōgakukan suggère aussi la double page partielle (seule la bande supérieure traverse les deux pages).

**Lisibilité.** Le lecteur doit pouvoir répondre à « qui frappe qui, avec quoi, où ? » à chaque case.

---

### LAY_006 — Transitions entre cases : formes, gouttières, débordements
`path: 06_decoupage_manga/transitions_entre_cases.md`

```meta
{"id":"LAY_006","type":"layout","agents":["storyboarder","lettering"],"intent":["pacing","speed","time_slowdown","emphasis","dream"],"pairs_with":["FUND_003","FUND_004","LAY_007"]}
```

**La forme de case est une transition en soi.**

| Forme / traitement | Effet |
|---|---|
| Rectangle standard | Neutre, lisible |
| Bande horizontale pleine largeur | Panorama, défilement, relâchement horizontal ; idéal pour les yeux (bande étroite) |
| Case haute et étroite | Verticalité : chute, élévation, grandeur, relâchement vertical |
| Case oblique / trapèze | Vitesse, violence, déséquilibre ; trapèze ouvert vers le bas pour une plongée |
| Case sans bord (dessin libre) | Flottement, souvenir, émotion, respiration |
| Case à fond perdu (*tachikiri*) | Espace qui déborde, immersion, monde plus grand que la page |
| Case en incrustation (*inset*) | Simultanéité : détail ou réaction pendant la grande image |
| Personnage qui déborde de sa case | Puissance, sortie du cadre, présence |
| Bord ondulé / flou | Rêve, flash-back, pensée |
| Gouttière noire (fond de page noir) | Flash-back, passé, cauchemar |
| Case fracturée en éclats | Choc, monde qui se brise, impact |

**Gouttières.** Gouttière étroite = enchaînement rapide, continuité ; gouttière large = pause, temps qui passe. Supprimer la gouttière (cases collées ou chevauchantes) = simultanéité.

**Dosage (Shōgakukan).** Les formes déformées sont des accents ; trop nombreuses, elles rendent la page difficile à lire. Paramètre de départ : au plus 1–2 cases déformées par page hors séquence de combat.

---

### LAY_007 — Compositions de page et de double page
`path: 06_decoupage_manga/compositions_de_page.md`

```meta
{"id":"LAY_007","type":"layout","agents":["storyboarder","qa"],"intent":["pacing","emphasis","structure"],"pairs_with":["FUND_002","FUND_003","FUND_004","ANTI_004"]}
```

**Règles de base (cours Shōgakukan).** Lecture sans ambiguïté ; gouttières verticales étroites et horizontales larges ; contraste net de tailles ; ≤ 8 cases, ~5 confortables ; raisonner en double page ; formes déformées en accent.

**Courbe de la double page (Natsume).** Une double page bien construite organise une compression qui augmente vers le bas de la page de droite, puis un relâchement qui remonte en haut de la page de gauche. Autrement dit : la tension se resserre en descendant la première page, la seconde page s'ouvre.

**Gabarits de page (à faire varier, jamais deux fois de suite le même).**

| Code | Disposition | Usage |
|---|---|---|
| `T_ESTAB` | Grande bande en haut + 3–4 petites cases dessous | Ouverture de scène |
| `T_BUILDUP` | Cases qui grandissent de haut en bas jusqu'à une grande case finale | Montée vers un pic |
| `T_STACCATO` | 6–8 petites cases régulières | Tension, dialogue rapide, comédie |
| `T_SPLASH_INSET` | Case pleine page + 1–2 incrustations | Apogée, révélation avec réaction |
| `T_VERTICAL` | 2–3 colonnes hautes | Chute, élévation, simultanéité de personnages |
| `T_DIAG` | Bandes obliques | Combat, poursuite |
| `T_SILENCE` | 1 petite case dans un grand blanc / noir | Choc, deuil, fin de scène |
| `T_SPREAD` | Double page (ou bande supérieure en double page) | Climax du chapitre |

**Kishōtenketsu.** Le cours Shōgakukan enseigne la structure en 4 temps *ki-shō-ten-ketsu* (introduction, développement, retournement, conclusion). Natsume montre qu'elle s'applique jusqu'à l'échelle d'une double page. Elle peut servir de squelette pour une page autonome : 1 case d'introduction, des cases de développement, une case de **retournement** (la plus marquante), une case de conclusion.

**Contrôle « graphique en barres ».** Natsume propose d'aligner les cases dans l'ordre de lecture et de comparer leurs tailles comme un histogramme. Le contrôleur qualité peut faire exactement cela avec `panel_weight` : une courbe plate = page monotone.


---

## 07_emotions

> Chaque fiche donne plusieurs **moyens non faciaux** de montrer l'émotion. Une scène émotionnelle racontée uniquement par des gros plans de visage est un signal de monotonie (→ ANTI_001).

### EMO_001 — Peur
`path: 07_emotions/peur.md`

```meta
{"id":"EMO_001","type":"emotion","agents":["director","storyboarder","art_director"],"intent":["fear","tension","threat","vulnerability"],"pairs_with":["ANG_POV_001","SHOT_PART_001","LAY_004","ACT_007"]}
```

| Levier | Choix possibles |
|---|---|
| Corps | Recul d'un pas, épaules rentrées, mains qui tremblent, dos collé au mur, genoux qui cèdent |
| Cadrage | Très gros plan pupilles rétrécies ; détail de la main tremblante ; plan large où le personnage est minuscule |
| Angle | Plongée sur la victime ; contre-plongée sur la menace ; vue subjective de la victime ; dutch angle |
| Composition | Espace négatif **derrière** le personnage (quelque chose peut surgir) ; personnage coincé contre le bord de case ; menace en silhouette ou en ombre |
| Découpage | Petites cases rapprochées, `moment_to_moment`, menace hors champ, révélation à la tourne |
| Effets | *yure-sen* (tremblement), *odoro-sen*, sueur, grands aplats noirs |

**Prompt (EN).** `character pressed against the wall, trembling hands, tiny pupils, looming shadow cast over them in dense screentone, the face still readable, high angle, heavy black shadows in the background, unsettling dutch angle`

---

### EMO_002 — Colère
`path: 07_emotions/colere.md`

```meta
{"id":"EMO_002","type":"emotion","agents":["director","storyboarder","art_director"],"intent":["anger","tension","power","confrontation"],"pairs_with":["BODY_001","ANG_LOW_001","COMP_004"]}
```

| Levier | Choix possibles |
|---|---|
| Corps | Poing serré (détail), mâchoire crispée, épaules en avant, objet écrasé dans la main |
| Cadrage | Gros plan coupé au front ; détail du poing ; très gros plan sur les dents serrées |
| Angle | Contre-plongée ; face-à-face frontal très serré (confrontation) |
| Composition | Diagonales anguleuses, contraste dur, ombre sur les yeux (colère froide) |
| Découpage | Colère froide = cases calmes et silencieuses qui contrastent avec la réplique ; colère explosive = case large, bulle hérissée, débordement |
| Effets | *odoro-sen*, flash noir, veine (comique), aura sombre |

**Distinguer.** Colère froide (silence, ombre, immobilité, gros plan stable) ≠ colère explosive (mouvement, diagonale, débordement de case).

---

### EMO_003 — Tristesse
`path: 07_emotions/tristesse.md`

```meta
{"id":"EMO_003","type":"emotion","agents":["director","storyboarder"],"intent":["sadness","grief","isolation","silence"],"pairs_with":["COMP_003","ANG_HIGH_001","FUND_003","EX_005"]}
```

| Levier | Choix possibles |
|---|---|
| Corps | Dos voûté, tête baissée, mains inertes sur les genoux, objet tenu contre soi |
| Cadrage | **Personnage de dos** ; plan général avec espace vide ; détail d'un objet lié à l'absent |
| Angle | Plongée ; vue zénithale sur un personnage recroquevillé |
| Composition | Espace négatif, horizontales, valeurs grises douces, pluie |
| Découpage | `aspect_to_aspect` (la chambre, la tasse, la fenêtre), cases sans bord, silence ; ralentir |
| Effets | *tare-sen*, pluie, cheveux qui cachent les yeux |

**Règle forte.** Une tristesse profonde gagne souvent à **ne pas montrer le visage** : dos, mains, objet. Le lecteur projette sa propre émotion.

**Prompt (EN).** `character seen from behind sitting on the edge of a bed, head lowered, empty room around, rain on the window, soft grey screentones, high angle, quiet`

---

### EMO_004 — Surprise
`path: 07_emotions/surprise.md`

```meta
{"id":"EMO_004","type":"emotion","agents":["storyboarder","art_director"],"intent":["surprise","shock","reveal","comedy_beat"],"pairs_with":["ACT_009","LAY_002","SHOT_CU_001"]}
```

| Levier | Choix possibles |
|---|---|
| Corps | Sursaut, objet qui tombe des mains, pas en arrière |
| Cadrage | Gros plan net, ou plan plus large si la surprise est physique (sursaut) |
| Angle | Changement brusque d'angle par rapport à la case précédente |
| Composition | Lignes de concentration vers le visage (l'étude d'Akio Honda montre qu'elles renforcent la lecture de la surprise) |
| Découpage | Case de surprise **juste après** le stimulus ; souvent couplée à un objet qui tombe (insert) |
| Effets | *shūchū-sen*, flash, symbole « ! », lignes autour de la tête |

**Comique vs dramatique.** Comique : exagération, déformation, case nette. Dramatique : pupilles rétrécies, silence, petite case serrée ou très grande case.

---

### EMO_005 — Intimidation / domination
`path: 07_emotions/intimidation.md`

```meta
{"id":"EMO_005","type":"emotion","agents":["director","storyboarder","art_director"],"intent":["intimidation","domination","power","threat"],"pairs_with":["ANG_LOW_001","COMP_004","COMP_005"]}
```

| Levier | Choix possibles |
|---|---|
| Corps | Immobilité, menton relevé, regard de haut, main posée lentement, posture large |
| Cadrage | Plan américain en contre-plongée ; silhouette qui remplit la case ; ombre du dominant qui recouvre l'autre |
| Angle | Contre-plongée sur le dominant / plongée sur le dominé (même scène, deux angles) |
| Composition | Grand / petit ; dominant au premier plan énorme, dominé au fond ; dominé encadré par le corps du dominant (frame in frame) |
| Découpage | Peu de mouvement, cases stables ; le dominant parle peu ; la case du dominé plus petite |
| Effets | Contre-jour, yeux dans l'ombre, reflet des lunettes |

---

### EMO_006 — Vulnérabilité
`path: 07_emotions/vulnerabilite.md`

```meta
{"id":"EMO_006","type":"emotion","agents":["director","storyboarder"],"intent":["vulnerability","intimacy","fear","sadness"],"pairs_with":["ANG_HIGH_001","COMP_003","BODY_007"]}
```

| Levier | Choix possibles |
|---|---|
| Corps | Bras qui entourent le corps, genoux repliés, mains cachées dans les manches, regard fuyant |
| Cadrage | Plan large avec beaucoup d'espace ; ou très proche et doux (intimité) |
| Angle | Plongée ; position au sol |
| Composition | Personnage petit dans le cadre, bas de la case, espace négatif au-dessus |
| Découpage | Cases sans bord, bulles petites (voix faible), silences |
| Effets | Trames douces, lumière diffuse, pas de lignes agressives |

---

### EMO_007 — Silence et attente
`path: 07_emotions/silence_et_attente.md`

```meta
{"id":"EMO_007","type":"emotion","agents":["director","storyboarder"],"intent":["silence","anticipation","atmosphere","time_slowdown"],"pairs_with":["FUND_003","COMP_003","BODY_007"]}
```

**Principe.** Le silence se construit visuellement : le *ma* (intervalle) de la tradition japonaise est un temps actif.

**Outils.**
- Case muette après une réplique forte (réaction sans mot, ou bulle « … »).
- `aspect_to_aspect` : objets du décor, lumière qui change, horloge, rideaux.
- Répétition d'un même cadrage avec un seul détail qui change (la seule répétition légitime : elle **montre** le temps qui passe → ANTI_005).
- Case très large et vide.
- Onomatopée d'ambiance minuscule (vent, insecte, horloge).

**Règle.** Un silence efficace vient après du bruit : placer la case muette juste après le pic sonore de la scène.


---

## 08_anti_repetition

> Objectif : supprimer la **répétition involontaire**, pas maximiser la variété. Toutes les valeurs numériques ci-dessous sont des **paramètres de départ** à calibrer sur tes propres planches.

### ANTI_001 — Détection des cadrages répétitifs
`path: 08_anti_repetition/detection_des_cadrages_repetitifs.md`

```meta
{"id":"ANTI_001","type":"anti_repetition","agents":["qa","storyboarder"],"intent":["variety","quality_control"],"pairs_with":["ANTI_002","ANTI_003","ANTI_004","ANTI_005"]}
```

**Signature d'une case.** Le contrôleur calcule pour chaque case un vecteur à partir de la fiche de case (→ 0.C) :
`sig = (shot_scale, camera_angle, subject_facing, composition, depth, attention_frame)`

**Similarité entre deux cases A et B** (pondérations de départ) :

```
sim(A,B) = 0.30 * [scale identique]
         + 0.25 * [angle identique]
         + 0.15 * [facing identique]
         + 0.15 * [composition identique]
         + 0.10 * [depth identique]
         + 0.05 * [attention_frame identique]
```

Échelle « voisine » (ex. `medium` vs `medium_close`) compte pour 0.5 au lieu de 1 sur ce critère.

**Alertes.**

| Code | Condition | Sévérité |
|---|---|---|
| R1 | `sim ≥ 0.80` entre deux cases consécutives | bloquant sauf exception justifiée |
| R2 | 3 cases consécutives avec la même `shot_scale` | bloquant |
| R3 | Plus de 40 % des cases d'une page en `medium` ou `medium_close` | avertissement |
| R4 | Plus de 60 % des cases d'une page en `eye_level` | avertissement |
| R5 | Plus de 50 % des cases d'une page en `depth = flat` | avertissement |
| R6 | Aucune case `micro` ou `amorphic` sur 2 pages consécutives | avertissement |
| R7 | Le `peak` d'une séquence n'a pas le plus gros `panel_weight` ni un traitement distinctif | bloquant |
| R8 | Même gabarit de page deux fois de suite (→ LAY_007) | avertissement |
| R9 | Plus de 3 gros plans visage consécutifs | avertissement |
| R10 | Plus de 4–6 cases serrées sans case de géographie | avertissement |
| R11 | `subject_facing = front` + `centered` + `eye_level` + `medium` (le « portrait d'identité ») | avertissement à chaque occurrence |

**Sortie attendue du contrôleur.** Pour chaque alerte : code, cases concernées, et **une proposition concrète** tirée de ANTI_002 à ANTI_004 — jamais un simple « varier davantage ».

---

### ANTI_002 — Variation des angles
`path: 08_anti_repetition/variation_des_angles.md`

```meta
{"id":"ANTI_002","type":"anti_repetition","agents":["storyboarder","qa"],"intent":["variety"],"pairs_with":["ANG_HIGH_001","ANG_LOW_001","ANG_WORM_001","ANG_POV_001"]}
```

**Table de substitution : si la case précédente était `eye_level`, proposer selon l'intention.**

| Intention de la case | Remplacement d'angle |
|---|---|
| Personnage prend l'ascendant | `low` |
| Personnage perd pied | `high` |
| Lieu / géographie | `birds_eye` ou `high` |
| Action au sol, vitesse, impact | `worms_eye` |
| Malaise, chaos | `dutch` |
| Découverte, menace perçue | `pov` |
| Dialogue | `over_shoulder` (en changeant de côté d'amorce) |

**Règle de rotation.** Sur une séquence de 4 cases, viser au moins 3 angles différents, sauf scène d'intimité calme (voir exceptions ANTI_005).

**Rotation autour du sujet.** Même sans changer de hauteur, tourner autour du personnage : face → trois-quarts → profil → trois-quarts dos → dos. Le dos est très sous-utilisé et très expressif.

---

### ANTI_003 — Variation des échelles
`path: 08_anti_repetition/variation_des_echelles.md`

```meta
{"id":"ANTI_003","type":"anti_repetition","agents":["storyboarder","qa"],"intent":["variety","pacing"],"pairs_with":["FUND_002","ACT_008","SHOT_DET_001"]}
```

**Principe du saut d'échelle.** Le passage d'une échelle à une échelle **éloignée** (plan d'ensemble → détail) a plus d'impact qu'un passage à une échelle voisine. Les sauts voisins (moyen → rapproché) donnent une progression douce ; les sauts lointains, un choc.

**Proposition par rôle Cohn.**

| Rôle | Échelles recommandées | Échelles à éviter |
|---|---|---|
| `orienter` | extreme_long, long, detail de décor | medium |
| `establisher` | long, full, over_shoulder | extreme_close_up |
| `initial` | detail, close_up, medium_close | extreme_long |
| `prolongation` | extreme_close_up, detail | même échelle que l'initial |
| `peak` | dépend : grand angle spectaculaire ou gros plan d'impact — **différent des deux cases précédentes** | medium frontal |
| `release` | long, extreme_long, close_up réaction | même échelle que le peak |

**Budget de page indicatif** (page d'action / page de dialogue) :

| Catégorie d'échelle | Action | Dialogue |
|---|---|---|
| Larges (extreme_long, long, full) | 20–30 % | 15–25 % |
| Moyennes (medium_full, medium, medium_close) | 20–30 % | 35–45 % |
| Serrées (close_up, extreme_close_up) | 20–30 % | 25–35 % |
| Détails (detail, micro) | 15–25 % | 10–20 % |

---

### ANTI_004 — Variation des compositions et des pages
`path: 08_anti_repetition/variation_des_compositions.md`

```meta
{"id":"ANTI_004","type":"anti_repetition","agents":["art_director","storyboarder","qa"],"intent":["variety"],"pairs_with":["COMP_001","COMP_002","COMP_003","LAY_007"]}
```

**Rotation de composition.** Ne pas enchaîner deux fois la même composition, en particulier `centered`. Alterner : centré → tiers → diagonale → espace négatif → cadre dans le cadre → premier plan.

**Rotation de position du sujet.** Si le sujet est à droite dans la case précédente, le placer à gauche, en bas, ou le faire entrer/sortir du cadre dans la suivante — en respectant la direction de lecture et l'axe des 180° dans un dialogue.

**Rotation de densité.** Alterner case chargée (décor détaillé) et case épurée (fond blanc, trames, lignes d'effet). Une page entièrement détaillée fatigue ; une page entièrement épurée paraît vide.

**Variation de pages.** Gabarit de page (→ LAY_007) différent d'une page à l'autre ; au moins une case nettement plus grande que les autres par page ; vérifier le profil « histogramme » des tailles de case.

---

### ANTI_005 — Exceptions : quand la répétition est voulue
`path: 08_anti_repetition/exceptions_aux_regles.md`

```meta
{"id":"ANTI_005","type":"anti_repetition","agents":["director","storyboarder","qa"],"intent":["time_slowdown","silence","comedy_beat","tension"],"pairs_with":["ANTI_001","FUND_003","EMO_007"]}
```

Le contrôleur **ne bloque pas** une répétition si la fiche de case contient `repetition_intent` avec l'une de ces valeurs :

| `repetition_intent` | Description | Exemple |
|---|---|---|
| `time_passing` | Même cadrage fixe, un seul élément change | Personnage qui attend : l'horloge et la lumière changent |
| `beat_comedy` | Même case répétée, réaction qui change à la dernière | Le gag en trois temps, la chute sur la 3e case |
| `staccato_tension` | Cases identiques régulières pour un battement d'horloge | Compression avant un choc (Natsume) |
| `mirror` | Deux scènes cadrées pareil à distance pour comparer | Même plan au début et à la fin du chapitre |
| `decomposition` | Même cadrage pour décomposer un geste lent | Main qui lâche un objet en 3 cases |
| `crossing_the_line` | Franchissement volontaire de l'axe des 180° | Bascule du rapport de force (signale aussi la rupture) |
| `kids_readability` | Simplicité voulue pour un jeune lectorat | Manga pédagogique : constance rassurante, mais garder une case forte par page |

**Règle.** Une exception = une justification écrite d'une phrase dans `variation_reason`. Pas de justification → le contrôleur traite la répétition comme involontaire.


---

## 09_exemples_analyses

> Chaque exemple montre **la même scène découpée plusieurs fois**. Le découpage « A » est le découpage par défaut à éviter ; « B » et « C » sont deux mises en scène valables et différentes. Les agents doivent retenir qu'il n'existe pas une bonne réponse, mais des choix motivés.

### EX_001 — Dialogue tendu
`path: 09_exemples_analyses/dialogue_tendu.md`

```meta
{"id":"EX_001","type":"worked_example","agents":["director","storyboarder","qa"],"intent":["dialogue","tension","confrontation","reveal"],"pairs_with":["LAY_003","SHOT_OTS_001","EMO_002"]}
```

**Scène.** Dans une cuisine, Mia accuse son frère Sora d'avoir lu son journal. Sora nie, puis avoue. 6 cases, 1 page.

**A — Découpage par défaut (à éviter).** 6 × plan moyen frontal, hauteur d'yeux, fond cuisine, alternance Mia / Sora. Alertes : R1, R2, R3, R4, R11.

**B — Escalade par l'échelle et l'objet.**

| # | Rôle | Échelle / angle | Focus | Composition / poids | Pourquoi |
|---|---|---|---|---|---|
| 1 | establisher | long, légère plongée | Les deux à distance, table entre eux, journal sur la table | Bande large, journal au centre du cadre | Géographie + objet du conflit |
| 2 | initial | detail | Main de Mia qui pousse le journal vers Sora | Petite case, diagonale | L'accusation passe par le geste |
| 3 | prolongation | over_shoulder (amorce Mia), Sora en medium_close | Sourire forcé de Sora : « Quoi ? » | Moyenne | Mensonge lisible sur le visage |
| 4 | prolongation | extreme_close_up | Doigts de Sora qui tapotent la table | Bande étroite, muette | Le corps trahit le mensonge |
| 5 | peak | close_up, contre-plongée, Mia | Mia : « Page 32. » | Case la plus grande, ombre sur les yeux | Mia prend l'ascendant → angle bas |
| 6 | release | long, plongée forte, Sora tête baissée | « … d'accord. » | Espace négatif au-dessus de Sora | Sora perd → plongée, petit dans le cadre |

**C — Variante « silence ».** Mêmes cases 1–2, puis case 3 entièrement muette en gros plan sur Sora (yeux qui fuient vers la gauche/hors champ), case 4 vue subjective de Sora vers le journal, case 5 Mia de dos qui attend (bras croisés, on ne voit pas son visage), case 6 très petite case : bulle « …pardon » dans un grand blanc.

**Leçon.** Le rapport de force se lit dans l'angle (bas = domine, haut = domine-t-on) ; les mains et l'objet portent autant que les visages.

---

### EX_002 — Combat rapide
`path: 09_exemples_analyses/combat_rapide.md`

```meta
{"id":"EX_002","type":"worked_example","agents":["director","storyboarder","qa"],"intent":["action_clarity","impact","evasion","throw"],"pairs_with":["ACT_008","LAY_005","ACT_004","ACT_006"]}
```

**Scène.** « Le héros esquive un coup de poing, saisit le bras de son adversaire et le projette au sol. »

**A — Par défaut (à éviter).** 3 plans moyens latéraux, hauteur d'yeux : coup / saisie / adversaire au sol. Alertes : R2, R4, R5, R7.

**B — Lisible et dynamique (6 cases, 1 page, gabarit `T_DIAG`).**

| # | Rôle | Échelle / angle | Focus | Composition / poids |
|---|---|---|---|---|
| 1 | initial | detail, eye_level | Poing adverse au premier plan, visage du héros flou derrière | Petite case, poing énorme |
| 2 | peak (esquive) | medium_close, worms_eye | Le poing traverse le haut du cadre, buste qui bascule en arrière | Case oblique, diagonale opposée au coup, lignes de vitesse |
| 3 | initial (saisie) | detail | Doigts qui se referment sur le poignet | Petite case, insert |
| 4 | prolongation | full, plongée oblique | Torsion des deux corps, déséquilibre | Moyenne, spirale |
| 5 | peak (projection) | long, vue haute grand angle | Corps de l'adversaire qui s'écrase en diagonale, débris, onomatopée | **Plus grande case, fond perdu** |
| 6 | release | detail, ras du sol | Pieds du héros ancrés, poussière qui retombe | Bande étroite en bas de page |

**C — Version fulgurante (3 cases).** (1) très gros plan des yeux du héros, calmes ; (2) case large quasi vide : lignes de vitesse en arc, onomatopée, une seule chaussure visible (action hors champ, pic abstrait) ; (3) plan d'ensemble : adversaire au sol, héros déjà de dos qui s'éloigne. → Montre la supériorité écrasante par l'**ellipse**.

**Leçon.** Choisir quels temps montrer change le sens : B = combat technique, C = maîtrise absolue.

---

### EX_003 — Révélation
`path: 09_exemples_analyses/revelation.md`

```meta
{"id":"EX_003","type":"worked_example","agents":["director","storyboarder"],"intent":["reveal","suspense","fear","surprise"],"pairs_with":["LAY_002","SHOT_PART_001","ANG_POV_001"]}
```

**Scène.** Une enquêtrice ouvre la porte d'un atelier abandonné et découvre que le mur est couvert de photos d'elle.

**A — Par défaut.** Plan moyen elle ouvre la porte → plan moyen elle regarde → plan moyen du mur. Tout est sur la même page, la révélation est vue avant d'être préparée.

**B — Avec tourne de page (2 pages).**

Page de gauche (dernière avant la tourne) :
| # | Rôle | Cadrage | Focus |
|---|---|---|---|
| 1 | orienter | extreme_long, nuit | Atelier dans la pénombre, une seule fenêtre éclairée |
| 2 | initial | detail | Main gantée sur la poignée rouillée |
| 3 | prolongation | over_shoulder (de dos), porte qui s'ouvre sur du noir | Faisceau de lampe qui entre |
| 4 | prolongation | extreme_close_up, bande étroite en bas de page | Ses yeux qui s'écarquillent, reflet de multiples petits rectangles dans la pupille. Bulle : « …c'est… » |

→ **Tourne de page.**

Page de droite suivante :
| # | Rôle | Cadrage | Focus |
|---|---|---|---|
| 5 | peak | Pleine page (ou 2/3), contre-champ large, légère contre-plongée | Le mur entier couvert de ses photos, elle petite en silhouette au premier plan |
| 6 | release | inset : detail | Une photo récente, prise ce matin même |

**C — Révélation inversée (zoom arrière).** Case 1 : très gros plan sur une photo d'elle (le lecteur croit à un souvenir) ; case 2 : gros plan, la photo est punaisée ; case 3 : plan moyen, des dizaines de photos ; case 4 : plan général, tout le mur, elle sur le seuil.

---

### EX_004 — Poursuite
`path: 09_exemples_analyses/poursuite.md`

```meta
{"id":"EX_004","type":"worked_example","agents":["storyboarder","art_director"],"intent":["chase","speed","tension","fear"],"pairs_with":["ACT_002","ACT_009","FUND_004","LAY_006"]}
```

**Scène.** Un garçon poursuivi par un chien géant dans des ruelles, jusqu'à une impasse.

**Principes appliqués.** Direction constante (le fuyard va toujours dans le sens de lecture, le poursuivant le suit) ; alternance poursuivi / poursuivant (`subject_to_subject`) ; distance qui se réduit d'une case à l'autre ; cases horizontales qui s'étirent.

| # | Cadrage | Focus | Note |
|---|---|---|---|
| 1 | long, plongée | Ruelle, le garçon court, ombre énorme qui le suit | Géographie |
| 2 | detail, ras du sol | Ses baskets qui dérapent dans un virage, eau qui gicle | Vitesse, perte d'équilibre |
| 3 | close_up, POV du chien | Le dos du garçon, plus proche | Menace subjective |
| 4 | medium_close, il regarde par-dessus l'épaule | Panique, sueur | Torsion du buste |
| 5 | extreme_long, vue zénithale | Le labyrinthe de ruelles, il s'engage dans un cul-de-sac | Le lecteur sait avant lui → suspense |
| 6 | full, de dos, face au mur | Impasse | Bloqué : sujet collé contre le bord dans la direction du regard |
| 7 | low, ombre du chien qui recouvre le garçon | Peak | Grande case, contre-plongée sur la silhouette du chien |

---

### EX_005 — Scène émotionnelle
`path: 09_exemples_analyses/scene_emotionnelle.md`

```meta
{"id":"EX_005","type":"worked_example","agents":["director","storyboarder"],"intent":["sadness","silence","intimacy","grief"],"pairs_with":["EMO_003","EMO_007","FUND_003","COMP_003"]}
```

**Scène.** Une adolescente range la chambre de son grand-père décédé et retrouve la montre qu'il portait.

**A — Par défaut.** Gros plans de visage qui pleure, 5 fois. Alertes : R2, R9.

**B — Raconter par les objets et le corps.**

| # | Transition | Cadrage | Focus |
|---|---|---|---|
| 1 | — | extreme_long, de la porte | Chambre vide, lumière de fin d'après-midi, cartons |
| 2 | aspect_to_aspect | detail | Lunettes posées sur un livre ouvert |
| 3 | aspect_to_aspect | detail | Fauteuil creusé par l'usage |
| 4 | subject_to_subject | medium, de dos | Elle à genoux devant un tiroir ouvert |
| 5 | moment_to_moment | detail | Ses mains qui sortent la montre, toujours en marche |
| 6 | moment_to_moment | extreme_close_up | Le cadran, l'aiguille des secondes (onomatopée minuscule « tic ») |
| 7 | release | long, plongée douce, sans bord de case | Elle serre la montre contre elle, recroquevillée ; grand espace blanc au-dessus |

Le visage n'apparaît **jamais** en gros plan : le lecteur projette l'émotion. Aucune bulle sauf l'onomatopée.

**C — Variante avec souvenir.** Après la case 6, une case sans bord à gouttière noire (flash-back) : la montre au poignet du grand-père qui lui apprend à lire l'heure ; retour au présent par le même cadrage de cadran (raccord par l'objet).

**Leçon.** L'émotion la plus forte passe souvent par l'objet, le dos et le silence.

---

## Annexe A — Checklist rapide pour le storyboarder (à injecter dans le prompt système)

1. Ai-je étiqueté chaque case avec `narrative_role` ? Chaque séquence a-t-elle un `peak` et un `release` ?
2. Le `peak` a-t-il la case la plus grande ou un traitement unique ?
3. Ai-je au moins une case `micro` (main, pied, objet) et une case `amorphic` ou large sur la double page ?
4. Ai-je au moins 3 angles différents sur 4 cases (hors exception) ?
5. Aucune `shot_scale` répétée 3 fois de suite ?
6. Le sens des mouvements et des regards respecte-t-il le sens de lecture ? L'axe des 180° est-il tenu en dialogue (ou franchi volontairement) ?
7. Les cases déformées et pleines pages sont-elles réservées aux moments-clés ?
8. La révélation tombe-t-elle après une tourne de page ?
9. Chaque répétition a-t-elle un `repetition_intent` et une `variation_reason` ?
10. Si je retire tout le texte, l'action reste-t-elle compréhensible ?

## Annexe B — Pont vers ComfyUI (traduction décision → prompt)

Construire le prompt dans cet ordre, du plus structurant au plus décoratif :

```
[shot_scale] + [camera_angle] + [subject + body_focus + action] + [composition + depth]
+ [line_of_action / pose] + [lighting & value masses] + [effects] + [style tokens]
```

| Champ | Exemples de tokens (EN) |
|---|---|
| shot_scale | `extreme wide shot`, `long shot`, `full body shot`, `cowboy shot`, `medium shot`, `medium close-up`, `close-up`, `extreme close-up`, `insert shot of [hand]` |
| camera_angle | `eye-level`, `high angle`, `low angle`, `bird's-eye view`, `worm's-eye view`, `dutch angle`, `first-person POV`, `over-the-shoulder` |
| depth | `extreme foreground [object]`, `layered depth`, `deep perspective`, `foreshortening` |
| composition | `diagonal composition`, `rule of thirds`, `negative space`, `frame within a frame`, `symmetrical` |
| value | `backlit silhouette`, `heavy black ink masses`, `chiaroscuro`, `soft screentone` |
| effects | `speed lines`, `radial focus lines`, `impact burst`, `motion blur afterimages` |

**Conseils techniques.**
- Les angles extrêmes et les raccourcis sont mal suivis par le texte seul : utiliser ControlNet (OpenPose, profondeur, ou lineart d'une esquisse 3D) pour les cases `worms_eye`, `birds_eye` et perspective forcée.
- Mettre le cadrage et l'angle **en tête** du prompt (poids plus fort), éventuellement pondérés `(low angle:1.3)` selon la syntaxe du workflow.
- Les lignes d'effet, onomatopées et bulles sont mieux produites en vectoriel par la couche de lettrage qu'en diffusion.
- Garder la cohérence des personnages (LoRA, références multiples) **séparée** des tokens de mise en scène, pour pouvoir changer d'angle sans perdre le personnage.

## Annexe C — Sources et lectures recommandées

Sources consultées pour cette base (paraphrasées ; aucune reproduction de planche) :
- Neil Cohn, *Visual Narrative Grammar* et articles associés : rôles Establisher / Initial / Prolongation / Peak / Release, emboîtement, remplacement du pic — PMC (PMC4159446, PMC4364919), *Frontiers in Psychology* 2014.
- Cohn, Taylor-Weiner, Grossman (2012), « Framing attention in Japanese and American comics » : catégories macro / mono / micro / amorphic, *Frontiers in Psychology*.
- Cohn, Hacımusaoğlu, Klomberg (2023), « The framing of subjectivity: Point-of-view in a cross-cultural analysis of comics », *Journal of Graphic Novels and Comics*.
- Scott McCloud, *Understanding Comics* (1993) : six transitions, fréquence de l'aspect-to-aspect dans le manga.
- Natsume Fusanosuke, « Les fonctions de la case dans le manga » (trad. Holt & Fukuda, *ejcjs* 2021) : découpage du temps, compression / relâchement, espace symbolique, *ma*, direction gauche/droite, double page.
- Shōgakukan, cours *Mangaka yōsei kōza* — Koma-wari (parties 1 et 2) : 5 règles de découpage, tachikiri, doubles pages, cases déformées ; Kishōtenketsu.
- Marcos Mateu-Mestre, *Framed Ink* (Design Studio Press, 2010) : plans plongeants/contre-plongeants, espace négatif, ordre/chaos, grand/petit, anguleux/courbe, silhouettes.
- Akio Honda, étude sur l'effet des lignes de concentration sur la reconnaissance des émotions (Shizuoka Institute of Science and Technology).
- Japanese with Anime, « Types of Manga Line Effects » : catalogue des *kōka-sen*.
- GlobalComix, « The Art of the Page Turn » : *mekuri-goma*.
- Ressources sur la règle des 180° en cinéma et en BD (LMU Filmmaking, analyse « Comics and the 180 degree rule »).

Lectures à acheter pour approfondir : *Understanding Comics* et *Making Comics* (McCloud), *Framed Ink* et *Framed Perspective* (Mateu-Mestre), *The Visual Language of Comics* (Cohn), *Manga in Theory and Practice* (Hirohiko Araki), *Comics and Sequential Art* (Will Eisner).
