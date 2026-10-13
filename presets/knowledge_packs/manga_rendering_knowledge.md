---
title: manga_rendering_knowledge — Base de connaissances du rendu manga (encrage, trames, papier, finitions)
version: 1.0
langue: fr (fragments de prompt en anglais)
date: 2026-10-13
usage: RAG — découpage par fiche (titres de niveau ###), métadonnées JSON en tête de chaque fiche
auteur: Morigane (à partir des mesures du 13/10/2026 sur ecoloman ch.1)
---

# manga_rendering_knowledge

> Base documentaire jumelle de `manga_visual_knowledge`. L'autre pack apprend aux agents à **choisir** un
> cadrage et un angle ; celui-ci leur apprend à **rendre** : épaisseur et nature du trait, trames, papier et
> impression, finition (propre, croquis, pinceau, scan) et dosage des masses noires.
> Objectif : que le rendu soit une décision prise à l'écriture, pas un effet du hasard du modèle.

## 0.A — Mode d'emploi pour l'indexation RAG

Mêmes règles que le pack de mise en scène : 1 fiche = 1 chunk (entre deux titres `###`), bloc ```` ```meta ```` en
JSON extrait comme métadonnées, `path` conservé, 250 à 700 jetons par fiche, aucune fiche dépendante d'une autre
(renvois par identifiant).

Champs de métadonnées propres au rendu :

```json
{
  "id": "REN_INK_001",
  "path": "10_encrage/ink_weight.md",
  "type": "ink | screentone | paper | finish | value",
  "agents": ["art_director", "prompter", "qa"],
  "intent": ["gritty", "clean", "handmade", "printed", "high_contrast", "flat"],
  "monochrome_only": true,
  "finish": "clean | sketch | brush | scan | any",
  "cost": "free | moderate | heavy",
  "avoid_when": ["colour rendering required", "poster flat colour expected"],
  "pairs_with": ["REN_FIN_002"]
}
```

**Requêtes typiques.**

- « rendu trop lisse, jeu vidéo » → `type=finish` + `intent=handmade`.
- « le visage part en aplat noir » → `type=value` + `intent=high_contrast`.
- « on veut un vieux scan » → `type=paper`.
- « trame invisible en impression » → `type=screentone`.

**Ce que le prompt d'image accepte.** Le fragment « **Prompt (EN)** » d'une fiche est le seul texte qui doit
sortir en anglais et être court : le rédacteur de prompt reçoit les passages entiers en français, mais les
fragments collés dans un prompt d'image se limitent à une note d'une ligne (budget 160 jetons,
`knowledge.yaml › agents.image_prompt`). Une fiche sans fragment anglais court est inutilisable par le
dessinateur.

**Branchement (`knowledge.yaml`).** Directeur artistique : `14` puis `10`. Rédacteur de prompt : `14` seulement
(son budget est déjà plein sur chaque case). Scénariste : rien. `11`, `12` et `13` restent consultables et
cherchables dans Savoir-faire.

**Les réglages vivent dans les presets, jamais ici.** Les mots-clés d'une finition sont dans le réglage borné
`finition` de la série (`presets/style_options.yaml`) et partent d'office dans chaque case : une copie ici
dériverait. Ce pack dit **quand** et **pourquoi** choisir, pas quoi recopier.

---

## 10_encrage

### REN_INK_001 — Épaisseur du trait et hiérarchie des lignes

`path: 10_encrage/ink_weight.md`

```meta
{"id":"REN_INK_001","type":"ink","agents":["art_director","prompter"],"intent":["clean","readable"],"monochrome_only":true,"finish":"any","cost":"free","avoid_when":[],"pairs_with":["REN_INK_002","REN_VAL_001"]}
```

**Définition.** Trois épaisseurs au plus dans une case : un contour appuyé, un trait intérieur moyen, des
détails fins. Ce qui distingue un encrage manga d'un dessin numérique, c'est l'**irrégularité contrôlée** :
le trait s'épaissit là où la pression porte, s'affine aux extrémités.

**Quand y penser.** Toujours. Une case où tous les traits ont la même épaisseur lit mal et paraît « propre ».

**À éviter.** Demander « clean digital line art » ou « vector lines » : c'est exactement ce qui produit le rendu
lisse que David rejette.

**Prompt (EN).** `inked line art, varied line weight, thicker contours, fine interior details`

---

### REN_INK_002 — Hachures et lignes de construction

`path: 10_encrage/hatching.md`

```meta
{"id":"REN_INK_002","type":"ink","agents":["art_director","prompter"],"intent":["gritty","handmade","shadow"],"monochrome_only":true,"finish":"sketch | brush | scan","cost":"free","avoid_when":["screentone_expected"],"pairs_with":["REN_INK_003","REN_FIN_002"]}
```

**Définition.** La hachure dit l'ombre **par le trait** au lieu de la dire par un aplat ou une trame. C'est
l'outil qui rattrape un visage qui part en masse noire (voir REN_VAL_002).

**Quand l'utiliser.** Visages et mains en clair-obscur, drapés, cheveux, matières rugueuses, tout ce qui doit
montrer la main de l'auteur.

**Piège mesuré (13/10/2026).** Le pack de style de la série contient « no cross-hatching » : la hachure est donc
interdite par défaut dans le rendu aux trames. Si on veut une ombre hachurée, il faut retirer ces mots du pack —
sinon le modèle n'a que l'aplat noir ou la trame pour dire l'ombre. C'est le sens de la mesure : zone de visage
en noir pur passée de 14,8 % (prompt d'origine) à 31,0 % (prompt réécrit, cfg 2,5).

**Prompt (EN).** `rough hatching, sparse cross-hatching in the shadows, visible stroke ends`

---

### REN_INK_003 — Pinceau et trait nerveux

`path: 10_encrage/brush.md`

```meta
{"id":"REN_INK_003","type":"ink","agents":["prompter"],"intent":["handmade","energetic","gritty"],"monochrome_only":true,"finish":"brush","cost":"free","avoid_when":["clean_romance_style"],"pairs_with":["REN_FIN_003","REN_VAL_001"]}
```

**Définition.** Encrage au pinceau : coups secs, densité d'encre inégale, traces d'arrêt du pinceau, quelques
éclaboussures. C'est le rendu « artisanal » le plus fort en trait mesuré après le scan.

**Mesure du 13/10/2026** (case gros plan, même graine, cfg 2,0) : densité de trait **24,6** contre **23,1** pour
le réglage de référence, avec beaucoup moins de blanc pur (57,8 % contre 60,1 %).

**À éviter.** Les éclaboussures sur une scène calme ou enfantine : réserver au mouvement et à la violence.

**Prompt (EN).** `confident rough brush inking, dry brush strokes, ink splatter, uneven ink density`

---

### REN_INK_004 — Croquis visible et lignes non fermées

`path: 10_encrage/sketch_lines.md`

```meta
{"id":"REN_INK_004","type":"ink","agents":["prompter"],"intent":["handmade","draft","light"],"monochrome_only":true,"finish":"sketch","cost":"free","avoid_when":["final_quality_page"],"pairs_with":["REN_FIN_002"]}
```

**Définition.** Le crayonné reste apparent : lignes de construction, traits doubles, quelques lignes laissées
ouvertes. Le lecteur voit la main.

**Attention au niveau sonore du prompt.** Le croquis seul n'a **pas** suffi lors de l'essai du 13/10 (23,6 de
densité, la vision le classe encore « propre ») ; c'est le croquis **plus** un négatif anti-lisse qui a changé la
lecture (26,6, « ARTISANAL »). Le négatif n'est lu qu'à vrai CFG (palier Qualité), donc un croquis en palier
Turbo ne reçoit que la moitié de la recette.

**Prompt (EN).** `rough hand-drawn ink sketch, visible pencil underdrawing and construction lines, unclosed lines, deliberately unfinished`

---

## 11_trames

### REN_TONE_001 — Ce qu'une trame n'est pas

`path: 11_trames/what_screentone_is_not.md`

```meta
{"id":"REN_TONE_001","type":"screentone","agents":["art_director","prompter","qa"],"intent":["printed"],"monochrome_only":true,"finish":"any","cost":"free","avoid_when":[],"pairs_with":["REN_TONE_002","REN_PAPER_001"]}
```

**Définition négative, la plus utile.** Une trame n'est ni un gris lisse, ni un dégradé numérique. C'est un
motif de points imprimés, de densité constante à l'intérieur d'une zone, et dont la **densité** porte la valeur
(clair, moyen, dense). Un gris continu dans une case manga est presque toujours une erreur de rendu.

**Conséquence pratique.** Le modèle de diffusion produit naturellement des dégradés doux : il faut **dire** la
trame dans le prompt, et le contrôleur qualité doit signaler les gris lisses (voir REN_TONE_002 pour les seuils).

**Prompt (EN).** `halftone screentone dots, flat dot pattern in the greys, no smooth digital gradient`

---

### REN_TONE_002 — Densités de trame et dégradés imprimés

`path: 11_trames/screentone_density.md`

```meta
{"id":"REN_TONE_002","type":"screentone","agents":["prompter"],"intent":["shadow","printed"],"monochrome_only":true,"finish":"any","cost":"free","avoid_when":[],"pairs_with":["REN_TONE_001","REN_VAL_001"]}
```

**Définition.** Trois densités suffisent : légère (peau, ciel), moyenne (ombre douce, sol), dense (ombre forte,
nuit). Un dégradé se fait par **paliers de densité**, pas par fondu.

**Réglage de l'appli.** Les réglages fins de la série (`trames` : légères, moyennes, denses) portent déjà ces
mots-clés. Les fiches servent à **décider** quelle densité va où, pas à remplacer le preset.

**Prompt (EN).** `light screentone on skin, medium-density halftone in soft shadows, dense dark screentone in deep shadows`

---

### REN_TONE_003 — Trame en réserve et blancs de papier

`path: 11_trames/open_whites.md`

```meta
{"id":"REN_TONE_003","type":"screentone","agents":["art_director","prompter"],"intent":["flat","readable"],"monochrome_only":true,"finish":"any","cost":"free","avoid_when":[],"pairs_with":["REN_PAPER_001","REN_VAL_001"]}
```

**Définition.** Ce qui n'est pas tramé reste vierge : le blanc est un choix, pas un vide. Une case manga réussie
n'est jamais tramée partout — mais elle n'est pas non plus blanche à 75 %.

**Mesure du 13/10/2026, à retenir comme garde-fou.** Le réglage de l'appli produit **76,7 %** de pixels blancs sur
le gros plan (blanc pur ≥ 250 : 60,1 %) ; la planche de l'auteur est bien plus dense, et le rendu préféré de
David n'a que **7,3 %** de blanc pur et **26,7 %** de papier (200-250). Le blanc pur absolu est un marqueur de
rendu numérique, pas de planche imprimée : il faut le casser (REN_PAPER_001).

**Prompt (EN).** `open white paper left untouched, off-white paper tone, never pure white`

---

## 12_papier_et_impression

### REN_PAPER_001 — Le papier n'est jamais blanc pur

`path: 12_papier_et_impression/paper_tone.md`

```meta
{"id":"REN_PAPER_001","type":"paper","agents":["art_director","prompter","qa"],"intent":["printed","handmade"],"monochrome_only":true,"finish":"any","cost":"free","avoid_when":["digital_clean_look_required"],"pairs_with":["REN_PAPER_002","REN_TONE_003"]}
```

**Définition.** Une planche imprimée a un papier légèrement chaud ou gris, jamais blanc numérique. C'est le
levier le plus efficace pour sortir du « trop léché » : il agit sur toute l'image à la fois.

**Mesure du 13/10/2026.** Le rendu préféré de David : blanc pur **7,3 %**, papier 200-250 **26,7 %**. Le réglage de
l'appli : blanc pur **60,1 %**, papier **14,4 %**. Aucun de mes six essais « artisan » n'a réussi à descendre sous
54 % de blanc pur — c'est la piste ouverte la plus rentable pour la suite.

**Prompt (EN).** `off-white paper, slight paper grain, printed ink on cheap paper, no pure white`

---

### REN_PAPER_002 — Défauts d'impression qui font vrai

`path: 12_papier_et_impression/print_flaws.md`

```meta
{"id":"REN_PAPER_002","type":"paper","agents":["prompter"],"intent":["printed","gritty"],"monochrome_only":true,"finish":"scan","cost":"free","avoid_when":["clean_reference_sheet"],"pairs_with":["REN_FIN_004"]}
```

**Définition.** Le léger décalage des passages d'encre, un grain fin, un fantôme de la page d'envers, une
densité d'encre irrégulière sur les aplats. Ce sont des **défauts** : s'ils sont trop marqués, on obtient une
photocopie de mauvaise qualité au lieu d'une planche.

**À éviter.** Ces mots dans une fiche de référence de personnage ou une planche de style : la référence doit
rester propre, c'est l'image d'identité.

**Prompt (EN).** `slight ink misregistration, fine print grain, faint show-through, uneven ink density in the blacks`

---

### REN_PAPER_003 — Le vieux scan (années 90)

`path: 12_papier_et_impression/old_scan.md`

```meta
{"id":"REN_PAPER_003","type":"paper","agents":["prompter"],"intent":["printed","nostalgic","gritty"],"monochrome_only":true,"finish":"scan","cost":"free","avoid_when":["colour_rendering","new_series_identity"],"pairs_with":["REN_FIN_004"]}
```

**Définition.** Trame grossière, papier jauni ou grisé, léger flou, bords de page, contraste écrasé dans les
noirs. À réserver aux séries dont c'est **l'identité** : mélangé à un rendu propre dans un même chapitre, ça se
lit comme un défaut.

**Mesure du 13/10/2026.** Recette `ART3` : densité de trait **29,7** (contre 23,1 en référence), blanc pur 54,9 %
(le plus bas des six essais), papier 16,6 % (le plus haut). C'est la recette la plus proche d'un vrai scan parmi
les six, et `ART6` (scan + croquis) monte à **32,4**, le maximum mesuré.

**Prompt (EN).** `1990s printed manga page, photocopied, coarse halftone dots, paper grain, off-white paper, faint ghosting`

---

## 13_finitions

> Ces quatre fiches correspondent aux quatre valeurs du réglage borné `finition` de la série
> (`presets/style_options.yaml`). Chaque fiche dit ce que la finition change **en plus** du rendu de la série,
> et ce qu'elle coûte. Ses mots-clés et son négatif sont dans le preset, jamais recopiés ici : la finition
> choisie sur la fiche de la série est ajoutée d'office à chaque case, juste après la phrase de style.

### REN_FIN_001 — Finition « propre »

`path: 13_finitions/finish_clean.md`

```meta
{"id":"REN_FIN_001","type":"finish","agents":["art_director","prompter"],"intent":["clean","readable"],"monochrome_only":false,"finish":"clean","cost":"free","avoid_when":[],"pairs_with":["REN_INK_001"]}
```

**Définition.** Aucun mot ajouté : c'est le rendu actuel de l'appli (trame et ligne propres). À garder pour les
séries jeunesse et les planches qui doivent rester lisibles en petit format.

**Ce que ça coûte, mesuré.** C'est le réglage que David a décrit comme « trop léché, jeu vidéo ultra détaillé ».
La vision le classe « PROPRE » sans hésiter. Ne pas s'en servir comme défaut universel.

**Mots-clés.** Aucun : « propre » n'ajoute rien au prompt.

---

### REN_FIN_002 — Finition « croquis »

`path: 13_finitions/finish_sketch.md`

```meta
{"id":"REN_FIN_002","type":"finish","agents":["prompter"],"intent":["handmade","draft"],"monochrome_only":true,"finish":"sketch","cost":"moderate","avoid_when":["colour_rendering"],"pairs_with":["REN_INK_004","REN_INK_002"]}
```

**Définition.** Crayonné visible, lignes non fermées, traits rapides, l'œuvre reste visiblement dessinée à la
main. Retenu par David le 13/10.

**Effet mesuré.** Densité de trait **26,6** avec le négatif anti-lisse (contre 23,1 en référence), et c'est le
bras que le modèle de vision a classé **ARTISANAL** (« trait irrégulier, encrage expressif, rappelle un manga
imprimé fait à la main »).

**Mots-clés.** Ceux du réglage `finition › croquis` de la série (prompt positif et négatif anti-lisse), ajoutés
d'office à chaque case : ne pas les recopier dans un prompt.

---

### REN_FIN_003 — Finition « pinceau nerveux »

`path: 13_finitions/finish_brush.md`

```meta
{"id":"REN_FIN_003","type":"finish","agents":["prompter"],"intent":["handmade","energetic"],"monochrome_only":true,"finish":"brush","cost":"moderate","avoid_when":["calm_scene","kids_comedy"],"pairs_with":["REN_INK_003"]}
```

**Définition.** Encrage au pinceau : coups secs, éclaboussures, densité inégale. Retenu par David le 13/10.

**Effet mesuré.** Densité de trait **24,6**, blanc pur 57,8 %. Moins fort que le croquis sur ce test, mais plus
expressif sur les scènes de mouvement — à réserver à l'action.

**Mots-clés.** Ceux du réglage `finition › pinceau-nerveux` de la série, ajoutés d'office à chaque case : ne pas
les recopier dans un prompt.

---

### REN_FIN_004 — Finition « scan »

`path: 13_finitions/finish_scan.md`

```meta
{"id":"REN_FIN_004","type":"finish","agents":["prompter"],"intent":["printed","nostalgic"],"monochrome_only":true,"finish":"scan","cost":"light","avoid_when":["colour_rendering","new_series_identity"],"pairs_with":["REN_PAPER_003","REN_PAPER_002"]}
```

**Définition.** Planche imprimée et photocopiée : trame grossière, papier, décalage d'encre, fantôme.

**Effet mesuré.** Densité de trait la plus haute des six essais (`ART6`, croquis + scan : **32,4**, soit +40 % sur
la référence). Attention : c'est le plus « vécu », donc le plus risqué comme identité de série neuve.

**Mots-clés.** Ceux du réglage `finition › scan` de la série (prompt positif et négatif anti-lisse), ajoutés
d'office à chaque case : ne pas les recopier dans un prompt. Pour le rendu `ART6` (croquis + scan), le réglage
`scan` ne porte que la partie impression : le croquis n'y est pas recopié.

---

## 14_valeurs_et_masses

### REN_VAL_001 — Équilibre des valeurs : les seuils mesurés

`path: 14_valeurs_et_masses/value_balance.md`

```meta
{"id":"REN_VAL_001","type":"value","agents":["art_director","qa","prompter"],"intent":["readable","high_contrast"],"monochrome_only":true,"finish":"any","cost":"free","avoid_when":[],"pairs_with":["REN_VAL_002","REN_TONE_003"]}
```

**Définition.** Sur la planche de l'auteur de référence (ecoloman), les valeurs mesurées sont : pixels sombres
(< 128) **21,7 %**, noirs purs (< 32) **9,5 %**. Les seuils du contrôleur qualité de l'appli (`presets/qc.yaml`)
sont des limites de rejet, pas des cibles.

**Cibles à viser.** 18-25 % de sombre, 8-12 % de noir pur, et **moins de 40 % de blanc pur** (aujourd'hui 60 %).

**Mesure du 13/10/2026, mêmes modèles et même graine.** Prompt d'origine (avant #134) : 23,1 % noir pur, mais
68,5 % de sombre — bouché, trois fois l'étalon. Prompt réécrit par l'appli (cfg 2,5) : 16,1 % de noir pur, blanc
pur 75,1 %. Le même prompt à **cfg 2,0** : 19,5 % de sombre, blanc pur 74,5 % — les blancs restent le seul vrai
écart, ils se corrigent par REN_PAPER_001, pas par le cfg.

**Prompt (EN).** `balanced value masses, large areas of untouched paper, ink blacks kept as accents`

---

### REN_VAL_002 — Aplat noir sur un visage : comment le doser

`path: 14_valeurs_et_masses/face_black_mass.md`

```meta
{"id":"REN_VAL_002","type":"value","agents":["art_director","prompter","qa"],"intent":["shadow","high_contrast"],"monochrome_only":true,"finish":"any","cost":"free","avoid_when":[],"pairs_with":["REN_INK_002","SHOT_CU_001"]}
```

**Définition.** Une moitié de visage dans l'ombre est un grand classique du manga — **à condition de la
hachurer ou de la tramer**. En aplat plein, le modèle la rend comme un bloc noir qui mange la moitié de la
figure ; le lecteur y voit une déformation, pas une intention.

**Règle à appliquer.** Toute consigne d'ombre sur le visage doit dire **le moyen** (hachure, trame, contour) et
pas seulement le résultat (« masse noire »). Et ne jamais empiler « moitié du visage dans le noir » et « grandes
zones blanches » dans la même case : à vrai CFG, les deux poussent du même côté et la figure disparaît.

**Prompt (EN).** `half of the face in shadow, rendered with hatching and screentone, never a solid black mass, the eye stays readable`

---

### REN_VAL_003 — Aplat noir sur un visage : cause racine mesurée (13/10/2026)

`path: 14_valeurs_et_masses/face_black_mass_cause.md`

```meta
{"id":"REN_VAL_003","type":"value","agents":["art_director","qa"],"intent":["shadow","high_contrast"],"monochrome_only":true,"finish":"any","cost":"free","avoid_when":[],"pairs_with":["REN_VAL_002","SHOT_CU_001"]}
```

**Ce qui s'est passé.** La fiche `SHOT_CU_001` du pack de mise en scène demandait, jusqu'au 13/10/2026, une
moitié de visage « dans l'ombre profonde », sans dire comment la rendre. Le rédacteur de prompt l'a suivie à la
lettre et a demandé une masse d'encre noire sur la moitié du visage. (Fragment fautif volontairement non recopié
ici : cette fiche est lue par le rédacteur.)

**Conséquence mesurée** (palier Qualité, cfg 2,5, case du trafiquant) : **31 % de la zone du visage en noir
pur** — la part la plus élevée de tous les essais — et la densité de trait la plus basse (18,5). Un modèle de
vision, sans consigne, décrit « une moitié du visage plongée dans une ombre très dense ». C'est ce que David a
lu comme un visage « déformé ».

**Ce qu'il faut en retenir.** Le pack de mise en scène est la source de la consigne ; une fiche qui demande une
ombre **forte** doit dire comment la rendre (hachure, trame, contour appuyé), sinon le modèle prend le chemin le
plus court : l'aplat. Corrigé dans `SHOT_CU_001` le 13/10/2026 : « half of the face in hatched shadow, never a
flat black fill ».
