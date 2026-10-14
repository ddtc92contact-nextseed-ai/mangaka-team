# Presets

Tout ce qui évolue (modèles, LoRA, workflows ComfyUI, formats de page, polices,
seuils de QC…) est un **preset**, pas du code. Le moteur les charge au démarrage
et les valide ; un preset invalide est écarté et l'erreur s'affiche dans
`GET /presets` (et le compteur `presets.issues` de `GET /health`).

Après modification d'un preset, redémarre le moteur (`npm run dev`).

## Arborescence

| Fichier | Rôle |
| --- | --- |
| `defaults.yaml` | Format de page, workflow (palier **Rapide**) et style de mise en page (`layout_style`) appliqués aux nouvelles séries ; workflow « avec références » de repli pour un preset qui ne déclare pas `with_references` (`workflow_with_references`) ; palier de « Régénérer en Qualité » (`workflow_quality`) ; palier des fiches de référence et de la planche de style (`workflow_library`, Turbo) ; agrandisseur de la finition d'impression (`upscaler`) et tolérance de dpi (`finishing_tolerance`) ; preset de réparation ciblée de repli (`workflow_inpaint`) ; palier croquis (`sketch_enabled`, `workflow_sketch`) ; planche de style (`style_board`) |
| `providers.yaml` | Paramètres des fournisseurs (URL, modèle LLM, timeouts). **Aucune clé d'API ici** : elles vont dans `.env` |
| `page_formats/*.yaml` | Formats de page (dimensions en mm, DPI, marges, gouttières) : A4 (défaut) et B4 JIS à 300 DPI |
| `cover_formats/*.yaml` | Formats de couverture d'un tome : manga 13 × 18 cm (défaut) et A4 (dimensions reprises de `page_formats/a4-300dpi.yaml`), 300 DPI, fond perdu, marge de sécurité, zones réservées (logo, numéro de tome, auteur) |
| `cover.yaml` | Couverture d'un tome : workflow dédié, taille générée, agrandisseur, rendu couleur (toujours, même en série N&B), phrase d'ouverture et règles du prompt (zone du logo dégagée, aucun texte) |
| `layout.yaml` | Découpage : taille mini d'une case, taille cible de génération, zones de bulles, seuil de régénération conseillée |
| `layouts/*.yaml` | Bibliothèque de gabarits de planche (arbres de découpes) |
| `layout_styles/*.yaml` | Grammaires de mise en page par série : `sage`, `dynamique` (défaut), `nerveuse` — biais, gouttières, gabarits favoris |
| `style_genres/*.yaml` | Packs de style : **genre et public** (shōnen, seinen, shōjo, jeunesse, magical girl, tranche de vie, franco-belge) — mots-clés, mise en page, sens de lecture, polices, consignes LLM, tons autorisés, scène test de la planche de style |
| `style_renderings/*.yaml` | Packs de style : **rendu** (N&B à trames par défaut, N&B encre, couleur, couleur douce) |
| `style_tones/*.yaml` | Packs de style : **ton** (lumineux, neutre par défaut, dark, humour) |
| `style_options.yaml` | Réglages fins bornés du style : trait, trames (N&B seulement), détail des décors, finition (propre, croquis, pinceau nerveux, scan) |
| `style_loras.yaml` | Catalogue des LoRA de style : mots déclencheurs et poids conseillé |
| `camera_loras.yaml` | LoRA Multiple-Angles (« Nouvel angle », « Changer l'angle ») et Cohérence anime, vocabulaire de caméra |
| `prompts/*.yaml` | Prompts des étapes LLM (`script` : découpage d'un chapitre ; `direction-artistique` ; `redacteur-image` : prompt image de chaque case rédigé en un paragraphe ; `redacteur-image-dialogue` : dialogue sur une case dans l'atelier) |
| `image_prompt.yaml` | Construction du prompt final des cases (étape 3) et termes « pas de texte » du prompt négatif |
| `qc.yaml` | Contrôle qualité des cases (étape 4) : poids, seuils de verdict, règles des détecteurs, seuil CCIP, zone de doute de la vision, nouveaux essais automatiques |
| `qc_tonality.yaml` | Mesures de tonalité de chaque image générée (% sombre, % noir, % blanc, saturation, densité de trait) et cible (planche de référence) |
| `journal.yaml` | Journal des générations : raisons d'un rejet (liste fermée), seuil « peu de données » et tranches de longueur de prompt de la page Statistiques |
| `workflows/*.yaml` + `*.json` | Workflows ComfyUI : le JSON API exporté + le mapping des paramètres |
| `upscalers/*.yaml` + `*.json` | Finition d'impression : agrandissement de la version retenue d'une case jusqu'au dpi du format, avant l'assemblage |

| `workflows/*.yaml` + `*.json` | Workflows ComfyUI : le JSON API exporté + le mapping des paramètres (dont les presets de réparation ciblée, bloc `inpaint`) |
| `fonts.yaml` + `fonts/` | Polices de lettrage (OFL, licences dans `fonts/OFL*.txt`) et style de texte par type de bulle |
| `lettering.yaml` | Formes et placement des bulles, queues, bordures de case, repères de coupe |
| `agents/*.yaml` | Agents du pipeline (écran « L'équipe ») : nom, rôle, étape et réglages éditables depuis l'UI |
| `reference_sheets/*.yaml` | Types de fiches de référence de « Créer des références » (portrait, turnaround, expressions, vue 3/4, plan large, autre angle) : gabarit de prompt, taille, workflow facultatif |

| `knowledge.yaml` | Savoir-faire (RAG local) : découpage des documents, recherche hybride, seuil « petite collection », budget de la bible, collections lues par chaque agent |
| `knowledge_packs/*.yaml` + `*.md` | Packs de savoir-faire livrés (fiches de mise en scène manga) : importés au démarrage dans des collections « pack » en lecture seule |

## Format de page

```yaml
id: a4-300dpi            # identifiant unique (minuscules, chiffres, tirets)
name: A4 portrait — 300 DPI
width_mm: 210
height_mm: 297
dpi: 300                 # 72 à 1200
bleed_mm: 3              # fond perdu
margins_mm: { top: 15, bottom: 15, inner: 15, outer: 12 }   # inner = côté reliure
gutters_mm: { horizontal: 6, vertical: 4 }                   # espaces entre cases
```

La taille en pixels est calculée : `round(mm / 25.4 × dpi)` → A4 300 DPI = 2480 × 3508 px.

## Couverture d'un tome (`cover_formats/*.yaml`, `cover.yaml`)

```yaml
id: manga-13x18-300dpi
name: Manga 13 × 18 cm — 300 DPI
default: true            # format des nouveaux tomes
width_mm: 130            # format rogné ; ou `page_format: a4-300dpi` pour reprendre un format de page
height_mm: 180
dpi: 300
bleed_mm: 3              # fond perdu, des quatre côtés
safety_mm: 5             # marge de sécurité : chaque zone doit y tenir (sinon le format est écarté)
zones:                   # en mm depuis le coin haut gauche du format rogné
  - { id: logo, label: Logo et titre, x_mm: 5, y_mm: 5, width_mm: 120, height_mm: 45, clear: true }
```

Image produite : format + fond perdu, au DPI du format (13 × 18 → 1606 × 2197 px). Le flux de `cover.yaml`
(`workflow`, ici `qwen-image-couverture` : Qwen-Image 2.1 Qualité avec images de référence) génère au ratio du
format, plus grand côté `long_side`, puis l'agrandisseur (`upscaler` de cover.yaml, sinon celui de la série,
sinon celui de defaults.yaml) l'amène au DPI réel, et le moteur la recadre au pixel près. Le prompt est rédigé
par le LLM du Dessinateur (`prompts/redacteur-couverture.yaml`) d'après la bible, les personnages choisis et
l'intention de l'auteur ; il est toujours en couleur (`rendering`, un rendu non N&B) et reçoit toujours les
`rules` (zone `clear` dégagée, aucun texte).

## Gabarits de planche (`layouts/*.yaml`)

Un gabarit est un arbre de découpes « guillotine » : `panel` (une case), `{ rows: [poids…] }`
(bandes empilées) ou `{ cols: [poids…] }` (cases côte à côte **dans le sens de lecture**, mises en
miroir automatiquement en manga). `children` absent = uniquement des cases.

```yaml
templates:
  - id: 3-grand-haut
    name: Grande case en haut + deux cases
    tree: { rows: [3, 2], children: [panel, { cols: [1, 1] }] }
```

À nombre de cases égal, le moteur prend le gabarit dont la répartition des surfaces suit le mieux
l'importance (1–3) des cases ; en cas d'égalité, le premier de la liste. Au-delà de la bibliothèque,
une grille de bandes de 3 cases est générée. Le style de mise en page de la série (ci-dessous)
module ce choix.

### Découpes en biais (`slants`)

Une case est un **polygone convexe** : une découpe peut être inclinée. `slants` donne, pour chaque
découpe d'un nœud (une de moins que de poids), le décalage en mm de ses deux extrémités par rapport à
la découpe droite : `[gauche, droite]` pour une découpe entre deux bandes, `[haut, bas]` entre deux
colonnes, dans le sens de lecture (miroir automatique en manga).

```yaml
tree: { rows: [3, 2], slants: [[-4, 4]], children: [panel, { cols: [1, 1], slants: [[3, -3]] }] }
```

La gouttière garde sa largeur, **mesurée perpendiculairement** à la découpe. L'image d'une case en
biais est générée à la taille de sa boîte englobante (mêmes règles que `layout.yaml`), puis découpée au
polygone à l'assemblage (masque anticrénelé, `clipPath` en SVG) ; la bordure suit les bords du polygone
et les bulles restent entièrement dans le polygone. Sans `slants`, une case est exactement le rectangle
d'avant. Les gabarits de la bibliothèque n'ont pas de biais : ce sont les styles qui en ajoutent.

## Styles de mise en page (`layout_styles/*.yaml`)

Chaque série a sa signature de mise en page : le champ « Style de mise en page » de la série (défaut
`dynamique`, `defaults.yaml`). Un genre peut suggérer `dynamique` ou `nerveuse`, jamais `sage` : les
découpes droites restent un choix explicite de la fiche série. Une page peut imposer le sien (atelier de
mise en page). Aucune valeur de
style n'est écrite dans le code : tout est dans ces fichiers, et **tous les champs sont obligatoires**.

| Style | Intention |
| --- | --- |
| `sage` | Découpes droites, gouttières du format, toujours le gabarit le mieux adapté : identique à la mise en page d'avant les styles |
| `dynamique` | Au moins une découpe en biais sur la plupart des pages de 4 cases ou plus (davantage sur les cases fortes et les temps d'action), pages calmes plus posées, gouttières légèrement variables |
| `nerveuse` | Biais fréquents et plus raides, fort contraste de tailles, grilles régulières rares |

```yaml
id: dynamique
name: Dynamique
gutters_mm:                       # null = gouttières du format de page
  horizontal: { min: 4, max: 6 }  # largeur tirée par page, au pas de 0,5 mm
  vertical: { min: 2.5, max: 4 }
size_contrast: 1.3                # poids d'une case = (importance × poids d'intensité) ^ contraste
intensity_weight: { calme: 0.85, normal: 1.0, choc: 1.6 }
size_jitter: 0.08                 # variation aléatoire des proportions de chaque découpe (0 à 0,5)
temperature: 0.03                 # 0 = meilleur gabarit ; plus haut = choix varié parmi les bons
default_template_weight: 1
template_weights: { "*-grille": 0.7, "*-grand-*": 1.3 }   # identifiant ou motif ; 0 = jamais
avoid_repeat: true                # jamais deux pages de suite avec le même gabarit (s'il en existe un autre)
slants:                           # probabilité de biais d'une découpe et angle tiré (degrés)
  by_importance:                  # règle d'une case sans intensité : selon son importance
    3: { probability: 0.55, rows_deg: { min: 2, max: 4 }, cols_deg: { min: 3, max: 6 } }
    # … 1 et 2
  by_intensity:                   # règle d'une case dont le scénario donne l'intensité
    choc: { probability: 0.8, rows_deg: { min: 2.5, max: 5 }, cols_deg: { min: 4, max: 7 } }
    # … calme et normal
rythme:                           # selon le rythme de la page (absent = normal)
  rapide: { slant_factor: 1.6, size_contrast: 1.2 }
  # … lent et normal
page_choc: { slant_factor: 1.3, size_contrast: 1.8 }   # page choc de la direction artistique, en plus du rythme
```

Une découpe passe en biais avec la probabilité de la case voisine la plus « forte » × le
`slant_factor` du rythme ; `rows_deg` s'applique aux découpes entre bandes (presque horizontales),
`cols_deg` aux découpes entre colonnes (presque verticales). L'angle tiré est réduit si une case
voisine passerait sous `min_panel_mm`.

**Graine.** Chaque page stocke sa graine (`layout_seed`) : même graine, même style, mêmes cases →
même mise en page, à chaque recalcul. « Nouvelle mise en page » tire une nouvelle graine (et écarte le
gabarit actuel s'il en existe un autre).

**Retouches à la main.** Dans l'onglet Mise en page, on peut glisser une gouttière (comme avant) ou
une **extrémité de découpe** pour l'incliner (bornée par la taille minimale des cases). Les images
déjà générées sont gardées et simplement recadrées au nouveau polygone ; la régénération n'est
conseillée (« Régénération conseillée ») que si le ratio de la boîte englobante de la case s'écarte de
plus de `regeneration.ratio_threshold` (`layout.yaml`, 15 %) de celui de l'image retenue. « Recalculer »
revient à la mise en page de la graine (retouches perdues, comme pour les gouttières).

### Options de cadre (`frames`)

Chaque case peut être **sans bord** (`frame: none`, image à bord franc ; `fade`, l'image se fond au
papier sur `frames.fade_mm` de `lettering.yaml`), **à fond perdu** (`bleed`) ou **incrustée** (`inset`) :

- **fond perdu** : seulement pour une case posée sur un bord extérieur de la zone utile (haut, bas,
  côté opposé à la reliure). Ces bords avancent jusqu'au bord de la page (et jusqu'au bord du fond
  perdu à l'export « fond perdu ») ; gouttières et biais ne bougent pas, aucune bordure n'est tracée
  le long d'un bord rogné, les repères de coupe restent dans leur bande. Bulles et onomatopées restent
  dans la zone utile (`live_polygon`).
- **incrustation** : petite case (gros plan de réaction) posée dans sa voisine — la précédente, sinon
  la suivante —, en bas côté fin de lecture, à `inset.margin_mm` des bords de l'hôte, sur un liseré
  blanc (`frames.inset_outline_mm`), dessinée après les autres cases. Elle ne prend pas de case dans le
  gabarit (une page de 4 cases dont une incrustée utilise un gabarit de 3 cases).

Les probabilités suivent la même règle que les biais (intensité si donnée, sinon importance) :

```yaml
frames:
  by_importance:
    1: { frameless: 0.03, bleed: 0, inset: 0.12 }
    2: { frameless: 0.05, bleed: 0.08, inset: 0 }
    3: { frameless: 0.1, bleed: 0.35, inset: 0 }
  by_intensity:
    calme: { frameless: 0.12, bleed: 0.05, inset: 0.15 }
    normal: { frameless: 0.04, bleed: 0.08, inset: 0.05 }
    choc: { frameless: 0.08, bleed: 0.5, inset: 0 }
  fade: 0.6          # part des cases sans bord qui se fondent au papier (sinon bord franc)
  inset: { size: 0.4, margin_mm: 3, min_side_mm: 12, max_per_page: 1, min_page_panels: 3,
           shot_types: [gros plan, très gros plan, plan rapproché] }
```

« sage » n'en tire jamais (une page sage reste identique), « dynamique » parfois, « nerveuse » souvent
sur les cases fortes. Les tirages utilisent un générateur à part (`cadres:<graine>`) : gabarit, biais et
gouttières d'une page ne changent pas. Dans l'onglet Mise en page, chaque case a trois menus (Bord, Fond
perdu, Incrustation) : « Auto » = décision du style, sinon option imposée (`PUT /panels/{id}/frame`,
stockée dans `Panel.frame`). Changer le bord ou le fond perdu garde les retouches de gouttières et de
biais ; ajouter ou retirer une incrustation recalcule la page depuis sa graine.

### Direction artistique : comment piloter la mise en page

La mise en page est de la **géométrie déterministe** : aucune IA ne dessine les cases. Le LLM du
scénario (`prompts/script.yaml`) et l'agent « Directeur artistique » (`prompts/direction-artistique.yaml`)
ne la pilotent **que** par ces champs structurés, validés par Pydantic :

| Champ | Où | Valeurs | Effet |
| --- | --- | --- | --- |
| `importance` | case | 1 transition, 2 normale, 3 forte | taille de la case (choix du gabarit), règle de biais `by_importance` |
| `intensity` (facultatif) | case | `calme`, `normal`, `choc` | poids de taille (`intensity_weight`), règle de biais `by_intensity` (prioritaire) |
| `rythme` (facultatif) | page | `lent`, `normal`, `rapide` | facteurs de biais et de contraste de la page (`rythme`) |
| `sfx` (facultatif) | case | `[{text, intensity}]` | onomatopées posées au lettrage (jamais dans la description ni le prompt image) |
| gabarit suggéré (DA) | page | un gabarit au bon nombre de cases | imposé à la page tant qu'il n'est pas écarté par « Nouvelle mise en page » |
| page choc (DA) | page | `pleine page`, `splash` | facteurs `page_choc` du style, en plus du rythme |

…et par le choix du style de la série ou d'une page. Jamais de coordonnées, de polygones ni de dessin
libre : pour un nouvel effet, on ajoute un champ au schéma et une règle au style. Le LLM factice (mode
mock) remplit ces champs. Ils sont modifiables à la main dans le découpage (API `PUT
/chapters/{id}/pages`).

### Agent « Directeur artistique » (`prompts/direction-artistique.yaml`)

Étape LLM entre le scénario et la mise en page, lancée depuis l'onglet **Direction artistique** du
chapitre (tout le chapitre, ou une page avec « Proposer autre chose »). Il reçoit le scénario validé, la
bible et les personnages, le style de mise en page de la série, les choix du chapitre précédent (pour ne
pas se répéter) et son savoir-faire (`knowledge.yaml` › `art_direction`). Il répond en JSON :

- par page : `rythme` (`calme`, `montée`, `climax`, `respiration`), `layout_style` (null ou un style),
  `template` (null ou un gabarit possible), `page_choc` (null, `pleine page`, `splash`), `rationale`
  (justification en français montrée à l'auteur) ;
- par case : `intensity`, `plan` (plan large / moyen / rapproché, gros plan, insert, plongée,
  contre-plongée), `angle`, `cadre` (normal, sans bord, fond perdu, incrustation), `ambiance`, `action`
  (courte phrase en français : le mouvement ou la pose du corps — « bondit par-dessus la rambarde,
  manteau au vent », jamais « regarde » ou « est debout » seuls ; reprise par le rédacteur de prompt),
  `sfx` (onomatopées : texte + intensité).

Réponse invalide (schéma, pages ou cases manquantes, gabarit impossible) → relance avec l'erreur
(`max_retries`, 2 au maximum) → sinon erreur visible sur le job.

**Mise en scène variée (`variety_rules`).** Test réel du 11/10 : 60-70 % des cases montraient un
personnage de face, debout, sans mouvement. La variété ne dépend plus de la bonne volonté du LLM : chaque
réponse est vérifiée contre les seuils du preset (aucun en dur dans le code) :

```yaml
variety_rules:
  max_same_plan_in_a_row: 2       # par page : au plus 2 cases d'affilée au même plan
  max_same_angle_in_a_row: 2      # par page : au plus 2 cases d'affilée au même angle
  max_frontal_share: 0.35         # pages dirigées ensemble : au plus 35 % de cases « de face » (une au moins permise)
  frontal_angles: [de face]
  min_off_eye_level_per_page: 1   # au moins une case hors hauteur d'œil par page…
  off_eye_level_min_panels: 2     # …dès 2 cases
  off_eye_level: [en plongée, en contre-plongée, cadre penché, plongée, contre-plongée]   # angle ou plan
  require_action: true            # `action` obligatoire et non vide
  weak_actions: [regarde, observe, est debout, se tient, …]   # refusés dans une action courte…
  weak_max_words: 4               # …d'au plus 4 mots (« Aiko regarde Kenji »)
  max_wide_medium_share: 0.5      # pages dirigées ensemble : au plus 50 % de plans larges et moyens (une au moins permise)
  wide_medium_plans: [plan large, plan d'ensemble, plan moyen]
  min_tight_per_page: 1           # au moins un plan serré par page…
  tight_min_panels: 3             # …dès 3 cases
  tight_plans: [gros plan, très gros plan, plan rapproché, insert]
  max_wide_in_a_row: 1            # par page : jamais 2 plans larges d'affilée
  wide_plans: [plan large, plan d'ensemble]
```

Retour du 12/10 : un tiers de plans larges, un tiers de plans moyens, personnages en pied. Les trois dernières
règles bornent l'échelle des plans ; le prompt système demande le plan serré pour l'émotion, la révélation et
la réplique clé, et le plan large pour installer un lieu ou suivre une chorégraphie. Les seuils numériques sont
réglables dans « L'équipe » (groupe « Mise en scène » du Directeur artistique).

Une règle enfreinte relance l'agent avec une erreur lisible (« page 2 : cases 1 à 3 au même plan « gros
plan » (2 d'affilée au plus : varie le cadrage) »). Après les relances, la dernière proposition valide est
**gardée** avec ses avertissements, affichés en tête de la page dans l'écran Direction artistique
(`warnings` de la page ; « chapitre : … » pour la part de cases de face ou de plans larges et moyens) ; ils sont recalculés quand
l'auteur retouche la page. Les règles sont aussi écrites en clair dans le prompt (`$variety_rules`). Sans
bloc `variety_rules`, aucune règle. Le LLM factice les respecte (angles en alternance, une action par case, plans larges resserrés). `variety` (sobre, equilibree,
audacieuse) règle l'audace, modifiable dans « L'équipe » (globalement ou par série), comme le modèle, la
température et les consignes.

**Règles par planche (`page_rules`).** Audit du chapitre « vulcano » (13/10) : 65 % de cases « X à gauche / Y à
droite », 0 gros plan, une planche entièrement « choc » et 8 chocs d'affilée, ce qui compte relégué au fond derrière
un héros. Ces règles se jouent à l'échelle de la planche et sont vérifiées **après** la réponse du LLM
(`check_page_rules`), avec les seuils du preset :

```yaml
page_rules:
  min_close_per_page: 1           # au moins un gros plan / très gros plan / insert par page…
  close_min_panels: 3             # …dès 3 cases
  min_calm_per_page: 1            # au moins une case « calme » par page (ou non choc d'une page « respiration »)…
  calm_min_panels: 3              # …dès 3 cases
  no_repeated_composition: true   # jamais deux cases d'affilée au même plan + même angle + même recette gauche/droite
  max_choc_in_a_row: 3            # pages dirigées ensemble : au plus 3 cases « choc » d'affilée
  no_background_subject: true     # pas de « au fond / au loin » derrière un personnage au premier plan ou un spectateur dessiné
  empty_panel_without_names: true # case sans personnage permise : son action ne nomme personne
  targeted_retry: 1               # une relance ciblée, puis avertissement
```

Une règle enfreinte déclenche **une seule relance ciblée** : le LLM reçoit les règles enfreintes et la liste des
seules cases à renvoyer (« page 3 : cases 1, 2, 3, 4 ») ; seules ces cases sont remplacées, et la correction
n'est gardée que si elle enfreint moins de règles. Ce qui reste devient un avertissement de la page (écran
Direction artistique), jamais un blocage — même si le LLM ne répond pas à la relance. Une suite de chocs à
cheval sur plusieurs pages est notée « chapitre : … » sur chacune. Les seuils principaux sont réglables dans
« L'équipe » (groupe « Mise en scène »). Le LLM factice respecte ces règles.

L'auteur corrige n'importe quel champ : il est alors **verrouillé** (🔒) et gardé quand l'agent repropose,
jusqu'à ce qu'il le déverrouille ; une page « acceptée » n'est pas remplacée par une relance de tout le
chapitre. **« Appliquer à la mise en page »** recopie les choix : rythme de la page (calme et respiration →
`lent`, montée → `normal`, climax → `rapide`), style suggéré, intensité des cases, gabarit suggéré et
page choc ; seules les pages dont la mise en page change sont recalculées. Les choix appliqués
alimentent aussi le prompt image (`$plan`, `$angle`, `$ambiance`, `$action`). Le cadre devient une option de cadre
de la case (sans bord → `frame: none`, fond perdu → `bleed`, incrustation → `inset`) et les onomatopées
des `sfx` du lettrage (léger → calme, moyen → normal, fort → choc) ; une option ou une onomatopée
réglée par l'auteur n'est jamais écrasée, celles de l'application précédente sont remplacées. Si le découpage d'une page change, sa direction est marquée « à refaire ».

## Packs de style (`style_genres/`, `style_renderings/`, `style_tones/`)

Le style d'une série se choisit **uniquement dans des listes fermées** : un genre, un rendu, un ton
(obligatoires), puis des réglages fins facultatifs et un LoRA de style. Il n'y a plus de texte libre :
**ajouter un style = ajouter un fichier**, jamais du code. Un pack invalide est écarté au démarrage
avec un message clair dans `GET /presets` (`issues`).

Un seul module (`engine/mangaka_engine/pipeline/style.py`) compose le style d'une série :

- **`$style`** des prompts image (cases, fiches de référence, réparation, croquis et passage au
  propre) = mots déclencheurs du LoRA de style (catalogue), puis mots-clés du **genre**, du **rendu**,
  du **ton** et des **réglages fins** (dans l'ordre de `style_options.yaml`), sans doublon, dans un
  **bloc court** (voir « Bloc Style court ») ;
- **`$style_packs`** et **`$style_guidelines`** des prompts LLM (scénario, direction artistique) : nom
  et description des packs, puis consignes du genre et du ton.

Champs communs : `id` (minuscules, chiffres, tirets), `name` et `description` **en français** (affichés
dans la fiche série), `prompt_keywords` (liste), `lang` (`fr` ou `en`, obligatoire : langue des
mots-clés, voir « Calibrage »), `order` (ordre dans la liste déroulante).

Un mot-clé qui évoque des personnes (« determined young hero », « expression comique »)
s'écrit `{text: smiles, people: true}` dans `prompt_keywords` (réglages fins compris). Il reste dans le
`$style` des cases et des fiches de personnage, mais il est **écarté des fiches d'objet et de décor** :
sinon le modèle y invente un personnage, qui revient ensuite dans chaque case utilisant la fiche. Une description signale une
**dominante** quand le pack prend le pas sur les autres (ex. franco-belge sur le rendu, humour sur le genre).

### Calibrage

Les mots-clés v1 ont été **mesurés le 10/10/2026** sur la machine : Qwen-Image 2.1 Turbo int8, 8 pas,
cfg 1, 832 × 1248, graine fixe, même scène, chaque pack testé en français et en anglais (60 images).
Tout nouveau pack s'écrit selon les mêmes règles, et se mesure de la même façon :

- **Prompt positif uniquement, cfg 1.** Le prompt négatif est quasiment sans effet en Turbo : les
  mots-clés disent ce qu'on veut voir. Une exclusion explicite (« pas de hachures ») est permise
  **en renfort** de mots-clés positifs ; un pack fait uniquement d'exclusions (« no color ») est refusé
  au chargement.
- **Langue** : au calibrage du 10/10, l'anglais marchait mieux pour le trait et les trames, le français
  pour le ton et le décor riche. Depuis le 11/10, tous les packs sont en anglais (voir « Tout en anglais »
  ci-dessous). `lang` documente la langue des mots-clés ; il ne traduit rien.
- **Trames : nommer les points** (« halftone screentone dots », « grey dot pattern ») : « screentone » seul sort des
  hachures.
- **Franco-belge : cumuler** ligne claire + aplats + trait de contour uniforme **et exclure
  explicitement l'anime** (« not Japanese anime style ») ; sans cela le modèle sort de l'anime
  générique.
- **Niveaux « moyen » : nommer la position relative** (« between thin and thick »), sinon ils ne se lisent
  pas.
- Le style ne change pas le temps de génération (médiane 9,7 s par image).

**Tout en anglais (11/10/2026).** Le texte côté image passe en anglais (voir « Prompts en anglais »
ci-dessous) : chaque pack a désormais `lang: en`, avec la traduction fidèle des mots-clés calibrés
(franco-belge : `European ligne claire comic, flat colours, uniform outlines, not Japanese anime
style`, puis `classic Franco-Belgian comic style`). Ces traductions n'ont pas encore été mesurées par un
A/B à graine figée : à refaire sur la machine, comme ci-dessus.

**A/B à référence figée (10/10/2026).** Après la planche de style, chaque pack a été rejoué en français
et en anglais avec la **référence de style de la série figée** (graph `qwen-image-edit-ref-turbo`,
graine 12345, même scène). Avec une référence, la langue pèse peu (1,5 à 15 % de pixels différents).
Seul **N&B à trames** passe en anglais : points de trame plus nets et réguliers, verdict tenu dans les
deux ordres d'affichage. Les autres packs gardent leur langue faute de preuve (jeunesse, seinen et
trames moyennes indécis).

Les accents sont écrits normalement (le modèle les lit comme sans accent).

**Décors simples (10/10/2026).** `detail.simple` disait `simple background, minimal, plain` : cela
contredisait le `Lieu :` décrit de la case (fonds vides). Il dit désormais `uncluttered background, few
details` — moins de détails, mais le lieu reste dessiné.

### Bloc Style court (`style_max_chars` de `image_prompt.yaml`)

Tous les mots-clés des packs mis bout à bout pesaient ~1/3 du prompt d'une case (300 à 400 caractères,
français et anglais mêlés) et noyaient sa description. `$style` est donc plafonné (`style_max_chars`,
240 livré, `null` = sans plafond) :

1. les mots déclencheurs du LoRA de style d'abord ;
2. puis les packs donnent leurs mots-clés **à tour de rôle** : le 1er mot-clé de chaque pack, puis le
   2e, etc., **le rendu en premier à chaque tour** (sans planche de style jointe aux cases, c'est lui
   qui porte trait, encrage et trames : « halftone screentone dots » passe avant le reste) ;
3. un pack s'arrête au premier mot-clé qui ne tient plus ; un mot-clé déjà dit par un pack précédent
   (même texte, ou contenu mot pour mot : « manga » derrière « seinen manga ») est retiré.

L'ordre d'affichage reste l'ordre fixe (LoRA, genre, rendu, ton, réglages fins). **Les mots-clés
calibrés ne changent pas** : seul l'assemblage choisit les premiers de chaque pack. Écrire donc les
mots-clés d'un pack **du plus important au moins important**.

### Ajouter un genre

```yaml
# presets/style_genres/sport.yaml
id: sport
name: Sport
description: Compétition et dépassement — matchs, entraînements, esprit d'équipe.
order: 80
lang: en                      # langue mesurée au calibrage (fr | en)
prompt_keywords: [sports manga style, dynamic athletic poses, motion blur, stadium atmosphere]
layout_style: nerveuse        # facultatif : style suggéré (dynamique | nerveuse ; jamais sage) — absent : defaults.yaml
reading_direction: rtl        # rtl (manga) | ltr (BD)
fonts: { dialogue: baloo2, shout: bowlby-one }   # polices de fonts.yaml
llm_guidelines: >-            # consignes du scénariste et du directeur artistique
  Sport, public adolescent : 4 à 6 cases par page, grandes cases pour les actions décisives…
scene_test: >-                # obligatoire : scène test de la planche de style (français, affichée ; aucun personnage de la série)
  une joueuse anonyme smashe au filet dans un gymnase bondé, ballon flou de vitesse
scene_prompt: >-              # la même en anglais : c'est elle qui entre dans le prompt image (absente : scene_test)
  an anonymous player smashes at the net in a packed gym, ball blurred with speed
allowed_tones: [lumineux, neutre, humour]        # facultatif (absent = tous les tons)
style_lora: encre-seinen_v2.safetensors          # facultatif : LoRA conseillé (catalogue style_loras.yaml)
```

Choisir un genre **pré-remplit** la mise en page, le sens de lecture et les polices de dialogue et de
cris de la série ; ils restent modifiables dans leurs listes. Les polices sont enregistrées comme
réglages de série de l'agent Lettreur (écran « L'équipe »). Un ton absent de `allowed_tones` est grisé
dans la fiche série et refusé par l'API (422). Une référence inconnue (mise en page, police, ton, LoRA)
écarte le genre au chargement.

### Ajouter un rendu

```yaml
# presets/style_renderings/sepia.yaml
id: sepia
name: Sépia
description: Monochrome brun, aspect gravure ancienne.
order: 50
monochrome: true      # noir et blanc : seul à accepter le réglage « trames »
lang: en
prompt_keywords: [sepia toned illustration, engraved hatching]
# default: true       # un seul rendu par défaut (celui des séries d'avant les packs)
```

Tonalité « papier blanc » (facultatif, anglais) : `tonality` est ajouté à la fin du prompt positif de
chaque case du rendu (fragments, prompt rédigé par l'IA ou édité à la main) ; `tonality_negative` est
ajouté au prompt négatif de chaque case (lu seulement à vrai CFG > 1 : palier Qualité). Les rendus N&B livrés en ont
une (« White paper dominant, clean line art, screentone only in the shadows, large white areas, no muddy
grey fill ») : mesurées le 11/10/2026, les cases sortaient grises et bouchées (50 à 83 % de pixels
sombres, contre 21,7 % sur une planche de référence). Le QC vérifie la tonalité (`detectors.tone`).

Phrase de style (`lead`, anglais, vocabulaire du dessin) : début de la phrase qui **ouvre chaque prompt
de case** (fragments `$style_lead` et rédacteur de prompt), complétée du 1er mot-clé du genre par
`style_lead` d'image_prompt.yaml — « Black and white manga panel, hand-drawn inked line art with halftone
screentone shading, seinen manga style. » Sans `lead`, le 1er mot-clé du rendu. Depuis le 12/10/2026 :
seuls les personnages à image de référence sortaient en manga, figurants, lieux et cases sans référence
sortaient en photo. Aucun mot-clé de pack ne doit pousser vers la photo (« realistic » retiré du seinen ;
liste `forbidden_photo_terms`, vérifiée par les tests).

Le rendu remplace toute mention de rendu en dur : `image_prompt.yaml` et les prompts de réparation
ne parlent plus d'« encre » ni de « manga », sinon un rendu couleur serait contredit.

### Ajouter un ton

```yaml
# presets/style_tones/epique.yaml
id: epique
name: Épique
description: Souffle et grandeur — paysages immenses, héroïsme.
order: 50
lang: fr
prompt_keywords: [souffle épique, grande échelle, lumière héroïque]
llm_guidelines: Ton épique ; scènes larges, enjeux qui dépassent les personnages.   # facultatif
```

### Réglages fins (`style_options.yaml`) et catalogue de LoRA (`style_loras.yaml`)

`options` : un réglage (`trait`, `trames`, `detail`…) = `name`, `description`, `choices` (id →
`name` + `lang` + `prompt_keywords`) et `monochrome_only: true` pour un réglage réservé aux rendus N&B (masqué
dans la fiche pour un rendu couleur, 422 à l'API). Un réglage non choisi n'ajoute rien.

**Finition** (`finition`, 13/10/2026) : `piece: finition` envoie les mots-clés du choix dans la pièce
réservée `$finition` d'`image_prompt.yaml`, juste après la phrase de style, dans **chaque** case de la série
(fragments et rédacteur de prompt, donc croquis, Turbo, Qualité et passage au propre) — et **jamais** dans
`$style`, dont le plafond `style_max_chars` la tronquerait en silence. `negative_keywords` d'un choix :
ajoutés au prompt négatif de la case, lu seulement à vrai CFG (cfg > 1, palier Qualité ; ignoré en Turbo,
Rapide et croquis). `propre` (ou « Par défaut ») n'ajoute rien : le prompt est identique, octet pour octet,
à celui d'une série sans finition. Les mots-clés vides et `negative_keywords` ne sont permis qu'avec `piece`.

`loras` : `file` (nom exact listé par ComfyUI, sous-dossier compris), `name`, `trigger_words` (ajoutés
en tête de `$style`) et `weight` (pré-rempli quand on choisit ce LoRA). Le LoRA de style se choisit
dans la liste de ComfyUI ; **les mots déclencheurs ne se tapent plus**. Un LoRA hors catalogue
s'applique sans mots déclencheurs (indice visible dans la fiche série).

### Planche de style (`style_board` de `defaults.yaml`)

Sur la fiche série, « Générer 4 essais » met en file `trials` croquis (palier `workflow_sketch`) de la
**scène test** du genre (`scene_test`, obligatoire : un genre sans scène test est écarté au chargement)
avec le `$style` de la série et une graine différente par essai. Le manager en choisit un (clic ou
touches 1-4) ou relance 4 autres (touche R). L'essai retenu passe au propre (`from_sketch` du palier
des fiches, `workflow_library` : Turbo — sinon de la série —, même graine, même prompt, débruitage de la série ou du preset) à la taille
`width` × `height`, puis devient la **référence de style** de la série (une seule active ; les
précédentes restent dans l'historique et peuvent être reprises).

```yaml
style_board:
  trials: 4                 # essais par demande (1 à 4)
  width: 1024               # taille du propre ; le croquis garde ce ratio (long_side du palier croquis)
  height: 1024
  prompt:                   # morceaux ; variables $scene (scène test du genre, en anglais : scene_prompt) et $style
    - "Style board, test scene: $scene."
    - "Style: $style."
  negative_prompt: "text, speech bubbles"   # ajouté au négatif du workflow
  reference_sheets:         # with_subject | always | never, une valeur pour toutes les sortes ou une par sorte
    character: with_subject
    object: never           # sorte absente = never
    decor: never
  panels: never             # with_subject | free_slot | never : voir « Cases » ci-dessous
```

- **Fiches de référence** (`reference_sheets`, une valeur ou une par sorte de fiche). Livré
  (11/10/2026) : `with_subject` pour les personnages, **`never` pour les objets et les décors** — la
  planche montre des personnages, qui apparaissaient dans la fiche d'objet ou de décor puis dans chaque
  case qui l'utilise comme référence (la même fuite que sur les cases le 10/10).
  - `with_subject` (personnages) : la référence de style n'est jointe que si une image du sujet est déjà
    envoyée (image de départ choisie, ou variante d'« Affiner »), **toujours après elle** et seulement
    s'il reste un emplacement dans le workflow « avec références » du palier. Une fiche créée à
    partir de zéro reste en texte → image : le workflow d'édition traite l'image 1 comme le sujet à
    redessiner, la planche seule en image 1 remplacerait donc la description par son personnage
    (la jeune femme de la scène test). Le style vient alors de `$style` et du LoRA de style.
  - `always` : jointe à chaque fiche (comportement d'avant : seule image sans image de départ,
    workflow « avec références » du palier ; sans pendant « avec références », la fiche se génère
    sans elle).
  - `never` : jamais jointe.

  Quand elle est jointe, le morceau `$style_ref` des types de fiche dit son rôle : référence de
  style uniquement (trait, trames, encrage), sans reprendre son personnage, sa scène ni sa
  composition.
- **Cases** : `never` (livré depuis le 10/10/2026) — la planche de style **n'est jamais jointe à une
  case** (génération, passage au propre, réparation). Mesure A/B à graine figée : jointe en 3e image,
  elle faisait apparaître ses propres sujets dans la case (l'enfant et son chat, le cerf-volant de la
  scène test) malgré la consigne « référence de style seulement » ; sans elle, la case montre la scène
  décrite. Le cadrage des références (#76) corrige les fiches de personnage, pas la planche. Le style
  des cases passe par `$style` (bloc court, rendu prioritaire) et le LoRA de style ; la planche reste
  utilisée pour les fiches de référence (`reference_sheets`).
  Autres réglages possibles — priorité personnages > décor > objets > **style**, la référence de style
  ne prenant qu'un emplacement resté libre une fois toutes les images des fiches servies :
  `with_subject` : **jamais seule** — une case sans image de personnage, de décor ni d'objet
  passe par le workflow texte de son palier, sans référence de style (avec une seule image, le modèle
  d'édition la redessinait telle quelle). `free_slot` : jointe même seule (la case passe alors au
  workflow « avec références »). `never` : jamais.
- Sans planche de style (ou sans bloc `style_board`), les graphes envoyés à ComfyUI sont exactement
  ceux d'avant.

### Séries d'avant les packs

L'ancien texte « Style graphique » est conservé en lecture seule (`legacy_style`) et affiché sur la
fiche série sous le bandeau « Style à choisir dans les listes ». Tant qu'aucun pack n'est choisi, il
tient lieu de genre dans `$style` (avec le rendu par défaut) ; il est ignoré dès qu'un pack est choisi.

## Prompts (`prompts/*.yaml`)

Gabarits `$variable` (écrire `$$` pour un dollar). `script.yaml` liste ses variables en tête ;
`max_retries` (0 à 2) fixe le nombre de relances après une réponse invalide, `max_previous_chapters`
le nombre de résumés de chapitres précédents envoyés. Le bloc `<contexte>…</contexte>` transmet le
même contexte en JSON (le LLM factice du mode mock s'en sert pour produire un découpage).

**Bibliothèque de la série.** Le scénariste (`script.yaml`) et le directeur artistique
(`direction-artistique.yaml`) reçoivent les décors et objets récurrents de la série (`$decors`,
`$objets` : « - id N · nom : description courte », et `decors` / `objets` dans le contexte JSON). Par
case, le scénario donne `decor` (id ou `null`) et `objets` (liste d'ids) à côté de `characters` ; la
direction artistique peut les proposer aussi (`null` = garder ceux du scénario). Un id absent de la
bibliothèque (ou d'une autre sorte) rend la réponse invalide : nouvel essai avec l'erreur (« page 1 ›
case 2 › decor : id 9 inconnu (ids possibles : 3, 4, ou null) »), puis erreur lisible après
`max_retries`. L'auteur corrige le décor et les objets d'une case dans l'écran Scénario. Les décors et
objets figurent aussi dans la bible injectée aux agents. Mode mock : `[mock:id-invalide:N]` dans le
synopsis fait citer un décor inexistant aux N premiers essais.

**Densité des dialogues (`dialogue_rules` de `script.yaml`).** Audit du chapitre 3 « vulcano » (13/10) :
0,75 parole par case contre 1,50 au chapitre 1, cinq cases de combat réduites à leur onomatopée, plus
aucune pensée, voix off ni narration. Chaque réponse valide du scénariste est vérifiée
(`pipeline/dialogues.py`, onomatopées jamais comptées comme répliques) :

- `target_per_panel` répliques visées dans chaque case où un personnage présent peut parler, et au moins
  `min_per_panel` par case sur le chapitre — bornées par la place : `room` donne, selon le nombre de
  cases de la page, les répliques au plus par case (`big_panel_bonus` de plus pour une case
  d'importance 3) ;
- `max_words` mots au plus par réplique, `max_mean_words` en moyenne (on ajoute des bulles, on ne les
  allonge pas) ;
- `action_needs_voice` : une case « choc » (`action_intensities`) ou avec onomatopée porte au moins un
  mot d'un personnage présent (cri, ordre, réaction) ;
- `require_inner_voice` : au moins une réplique de `inner_voice_kinds` (pensée, voix off, narration) par
  chapitre — `false` si l'auteur s'en passe ;
- `check_room` : le découpage est mis en page à blanc et lettré (sans visages) ; chaque bulle doit tenir
  dans la zone de bulles de sa case (`bubble_zone`).

Une règle enfreinte relance le scénariste avec l'erreur (mêmes `max_retries` et gabarit `retry`) ; après
les relances, le découpage est gardé, le job le signale (« avec N avertissements de dialogues ») et
l'écran Scénario affiche la mesure du chapitre et les règles encore enfreintes
(`GET /chapters/{id}/dialogues`, recalculé à chaque retouche). Les règles sont écrites en clair dans le
prompt (`$dialogue_rules`) et réglables dans le profil du Scénariste (groupe « Dialogues »). Sans bloc
`dialogue_rules`, aucune règle. Mode mock : `[mock:dialogues-maigres:N]` dans le synopsis rend les N
premiers découpages maigres (comme le chapitre 3).

La zone de bulles de `layout.yaml` a, en plus de sa fraction de case, un plancher absolu : `bubble_mm2`
par bulle et `char_mm2` par caractère (taille réelle du lettrage, toujours bornée à `max_fraction`) —
sans lui, deux répliques courtes débordaient déjà d'une case d'une planche à 6 cases.

## Workflow ComfyUI

1. Dans ComfyUI, construis le workflow puis exporte-le au format API (**Workflow → Export (API)**,
   « Save (API Format) » selon les versions). Copie le JSON dans `presets/workflows/<id>.json`.
2. Crée `presets/workflows/<id>.yaml` qui décrit comment le moteur remplit ce JSON :

```yaml
id: qwen-image-base
name: Qwen-Image 2.1 — texte → image
workflow_file: qwen-image-base.json   # relatif au YAML
output_node: "11"                     # nœud SaveImage dont on récupère les images
mapping:                              # paramètre moteur → workflow[node].inputs[input]
  positive_prompt: { node: "6", input: text }
  negative_prompt: { node: "7", input: text }
  seed:            { node: "9", input: seed }
  width:           { node: "8", input: width }
  height:          { node: "8", input: height }
defaults:                             # valeurs appliquées si le pipeline ne les fournit pas
  steps: 20
timeout_s: 600                        # durée max d'une génération (sinon interruption + job en échec)
reference_images: []                  # emplacements d'images de référence (voir plus bas)
lora_chain: { … }                     # point d'insertion des LoRA (voir plus bas)
```

### Mapping des nœuds (presets Qwen-Image 2.1)

Les presets texte → image et « avec références » livrés partagent le même graphe et les mêmes numéros de nœuds :

| Paramètre | Nœud | Type ComfyUI | Entrée | Obligatoire |
| --- | --- | --- | --- | --- |
| `positive_prompt` | `6` | `TextEncodeQwenImage21` | `prompt` | oui |
| `negative_prompt` | `6` | `TextEncodeQwenImage21` | `negative_prompt` | oui (défaut fourni) |
| `seed` | `9` | `KSampler` | `seed` | oui (tirée au hasard puis enregistrée si absente) |
| `steps` | `9` | `KSampler` | `steps` | non |
| `cfg` | `9` | `KSampler` | `cfg` | non |
| `width` | `8` | `EmptyLatentImage` | `width` | oui |
| `height` | `8` | `EmptyLatentImage` | `height` | oui |
| `filename_prefix` | `11` | `SaveImage` | `filename_prefix` | non |

Graphe : `1 UNETLoader` → `4 QwenImage21Cache` → `9 KSampler` ; `2 CLIPLoader` (`type: qwen_image`) →
`6 TextEncodeQwenImage21` (sorties 0 = positif, 1 = négatif ; `vae` = `3 VAELoader`) ; `8 EmptyLatentImage` →
`9` → `10 VAEDecode` → `11 SaveImage`. `cfg: 1` est le chemin officiel de Qwen-Image 2.1 : **à cfg 1, ComfyUI
saute la passe négative** et le prompt négatif n'est jamais lu (« négatif inactif », affiché dans la fiche
série et l'atelier). Au-dessus de 1 (vrai CFG), il est lu et chaque étape coûte environ deux fois plus ;
**garder cfg ≤ 3** (au-delà : image trop contrastée, exposition décalée ; cfg 5 la dégrade nettement).

Chaque preset déclare `distilled: true|false`. Un modèle **distillé** (Turbo, croquis) refuse tout cfg
différent de 1, au chargement (`defaults.cfg`) comme à la construction du workflow (`PresetError`, 422
lisible côté API). Le cfg d'un preset non distillé va de 1 à 3. Le réglage « CFG » du dessinateur
(écran « L'équipe ») ne touche jamais les presets distillés.

Règles vérifiées au chargement :

- `positive_prompt`, `negative_prompt`, `seed`, `width`, `height` doivent être mappés ;
- chaque `node` doit exister dans le JSON et posséder l'entrée `input` ;
- `output_node` doit exister ;
- chaque clé de `defaults` et de `trial` doit être mappée ;
- `with_references` doit désigner un workflow chargé qui a des emplacements de référence (sinon
  avertissement dans `GET /presets`, et les cases avec références de ce palier échouent avec un
  message clair : jamais de repli sur un autre palier).

Les noms de fichiers de modèles (`unet_name`, `clip_name`, `vae_name`) vivent
**uniquement** dans le JSON. Le code Python ne connaît aucun nom de modèle.

### Fichiers de la GX10 et paliers Turbo / Rapide / Qualité

Fichiers installés dans `~/ComfyUI/models/` (liens vers le disque T9) et utilisés par les presets :

| Dossier | Qualité max | Qualité et Rapide | Turbo |
| --- | --- | --- | --- |
| `diffusion_models/` | `qwen_image_2.1_bf16.safetensors` (14,2 Go) | `qwen_image_2.1_int8_convrot.safetensors` (7,3 Go) | `qwen_image_2.1_turbo_int8_convrot.safetensors` |
| `text_encoders/` | `qwen3vl_8b_bf16.safetensors` (17,5 Go) | `qwen3vl_8b_int8_convrot.safetensors` (9,4 Go) | idem Rapide |
| `vae/` | `qwen_image_2.1_vae_bf16.safetensors` | idem | idem |

**Paliers (11/10/2026)** — étapes, cfg, prompt négatif lu ou non, et durée attendue d'une case
(`estimated_s`, remplacé par la médiane réelle dès 3 générations) :

| Palier | Presets | Modèle | Étapes | cfg | Négatif actif | Durée (texte / avec réf.) |
| --- | --- | --- | --- | --- | --- | --- |
| Croquis | `qwen-image-croquis` (+ `-edit-ref-croquis`) | Turbo distillé | 6 | 1 | non | 6 s / 10 s |
| Turbo | `qwen-image-turbo` (+ `-edit-ref-turbo`) | Turbo distillé | 8 | 1 | non (jamais) | 20 s / 80 s |
| Rapide | `qwen-image-base-rapide` (+ `-edit-ref-rapide`) | int8, non distillé | 25 | 1 | non | 60 s / 240 s |
| **Qualité** (défaut) | `qwen-image-base-qualite` (+ `-edit-ref-qualite`) | int8, non distillé | 35 | 2,5 | **oui** | 168 s / 672 s |
| Qualité max | `qwen-image-base` (+ `-edit-ref`) | bf16, non distillé | 50 | 1 | non | 70 s / 280 s |

Qualité = mêmes fichiers que Rapide, `euler` / `simple`, mais un vrai CFG : ≈ 2× Rapide par étape
(passe négative en plus), d'où `estimated_s` = Rapide × 2 × 35/25 (passage au propre : 112 / 448 s,
ControlNet : 196 / 700 s). Environ 3 h pour un chapitre de 10 pages au lieu de 3-4 min par page :
accepté pour la qualité. Le cfg se règle par série (fiche série, 1 à 3 ; vide = celui du palier), pour
tous les presets non distillés de la série ; un palier distillé refuse un cfg > 1 (422).

**Prompts négatifs, en anglais, par tâche** (les termes « pas de texte » de `image_prompt.yaml →
forbidden_text_terms` y sont toujours ajoutés, en anglais eux aussi) :

| Tâche | Où | Négatif |
| --- | --- | --- |
| Cases | `defaults.negative_prompt` des presets de case | text, letters, speech bubble, caption, watermark, signature, multiple panels, comic page layout, collage, split screen, character sheet, turnaround, model sheet, white background, duplicate character, extra people, extra limbs, deformed hands, blurry, low quality |
| Réparation | presets `qwen-image-inpaint*` | text, letters, speech bubble, watermark, signature, blurry, deformed hands, extra fingers, low quality |
| Fiche d'objet | `reference_sheets/objet-*.yaml` | person, people, human, character, face, hands, figure, crowd, text (+ cluttered background) |
| Fiche de décor | `reference_sheets/decor-*.yaml` | person, people, human, character, figure, crowd, silhouette, animal, text, close-up |
| Fiche de personnage | `reference_sheets/personnage-*.yaml` | extra characters, background people, text (+ termes propres à la fiche) |

Une fiche de référence envoie **son** négatif, jamais celui des cases (qui exclut justement « character
sheet, white background »).

**Turbo** = version distillée officielle de Qwen-Image 2.1, publiée par Qwen dans le dépôt
`Comfy-Org/Qwen-Image-2.1` (`diffusion_models/`) : la distillation est déjà fusionnée dans les poids,
donc ni LoRA d'accélération ni nœud personnalisé — même graphe que les autres paliers, seul le fichier
du modèle et l'échantillonnage changent. **Alternative bf16** (pas un 4ᵉ palier) : remplacer `unet_name`
par `qwen_image_2.1_turbo_bf16.safetensors` (et, au besoin, `clip_name` par `qwen3vl_8b_bf16.safetensors`)
dans `qwen-image-turbo.json` et `qwen-image-edit-ref-turbo.json`, puis régénérer les JSON de référence
des tests (`UPDATE_GOLDEN=1`).

Échantillonnage Turbo livré : 8 étapes, cfg 1, `euler` + `simple`, denoise 1 — **à confirmer** avec
le vrai export ComfyUI du manager (`~/mangaka-comfy-exports/`). Une correction ne touche que les deux
presets Turbo (YAML `defaults` + JSON nœud 9), jamais le code. Attention : un réglage « Étapes » modifié
dans l'écran « L'équipe » (dessinateur) s'applique à **tous** les workflows, Turbo compris.

Les fichiers int8 « convrot » se chargent avec les nœuds standard (`UNETLoader` `weight_dtype: default`,
`CLIPLoader` `type: qwen_image`), comme dans le workflow de référence du manager
(`~/ComfyUI/user/default/workflows/image_qwen_image_2_1_image_edit.json`).

| Preset | Palier | Usage | Étapes | Délai max | `estimated_s` |
| --- | --- | --- | --- | --- | --- |
| `qwen-image-turbo` | Turbo (fiches de référence, planche de style) | texte → image | 8 | 5 min | 20 |
| `qwen-image-edit-ref-turbo` | Turbo | avec images de référence | 8 | 10 min | 80 |
| `qwen-image-base-rapide` | Rapide | texte → image | 25 | 10 min | 60 |
| `qwen-image-edit-ref-rapide` | Rapide | avec images de référence | 25 | 15 min | 240 |
| `qwen-image-base-qualite` | Qualité (défaut des nouvelles séries, vrai CFG 2,5) | texte → image | 35 | 30 min | 168 |
| `qwen-image-edit-ref-qualite` | Qualité | avec images de référence | 35 | 45 min | 672 |
| `qwen-image-base` | Qualité max (bf16, finitions, « Régénérer en Qualité ») | texte → image | 50 | 20 min | 70 |
| `qwen-image-edit-ref` | Qualité max | avec images de référence | 50 | 25 min | 280 |

Le palier se choisit avec le **workflow de la série** (liste « Palier de génération » de la fiche
série : « Turbo (production en volume, ~35 s par case) », « Rapide (~1 min par case, négatif inactif) »,
« Qualité (recommandé, négatif actif, ~3 min par case) », « Qualité max (bf16, 50 étapes, finitions) »).
Les séries existantes gardent leur preset (et leur cfg : vide) ; une série restée sous le palier par
défaut voit dans sa fiche un bouton « Passer en Qualité » (puis Enregistrer).

**Quel palier pour quelle tâche (10/10/2026)** :

| Tâche | Palier | Pourquoi |
| --- | --- | --- |
| Cases (génération, passage au propre) — avant le 11/10/2026 | Rapide | Mesure en génération libre avec références : 8 pas (Turbo) contre 25 pas changent ~60 % de l'image, au profit de 25 pas — le réglage du workflow officiel « Image Edit (Qwen Image 2.1) » (int8, 25 pas, cfg 1, euler/simple). ~35 s → ~60 s par case, accepté : la qualité prime. L'encodeur de texte n'y est pour rien (int8 contre bf16 : 0,1 % des pixels changés). |
| Croquis | croquis (`workflow_sketch`, modèle Turbo, 6 pas) | Tri rapide des compositions. |
| Fiches de personnage, propre de la planche de style | **Turbo** (`workflow_library`) | Images de travail, refaites souvent ; « Qualité » reste proposé par fiche. |
| Cases (génération, passage au propre), depuis le 11/10/2026 | **Qualité** (`defaults.workflow`, `workflow_with_references`) | Vrai CFG 2,5 : le négatif (texte, collage, personnages en trop) est enfin lu. La réparation reste celle de Rapide (mêmes fichiers). |
| Fiches d'objet et de décor | **Qualité** (`workflow` du type de fiche) | Le négatif « person, people… » doit être lu : aucune personne dans la fiche. |
| Finitions | Qualité max (`workflow_quality`) | « Régénérer en Qualité » des cases importantes (bf16, 50 pas). |

Chaque preset déclare son palier :

```yaml
tier:
  name: Turbo                            # affiché sur chaque version de case (atelier)
  choice: "Turbo (production en volume, ~35 s par case)"   # libellé de la fiche série ; absent = pas proposé
  order: 1                               # ordre dans la liste
estimated_s: 20                          # s / case tant qu'il y a moins de 3 générations réelles
```

**Régénérer en Qualité** (atelier, par case) : met en file une nouvelle version de cette seule case
avec `defaults.workflow_quality` (ou son `with_references` si un personnage de la case a une planche
de référence), même prompt, nouvelle seed. Les autres versions (et la version choisie) ne bougent pas.

**Temps estimé** (en-tête du chapitre et de la série) : cases sans version choisie × durée par case de
leur preset = médiane des 20 dernières générations réussies de ce preset dès qu'il y en a 3, sinon
`estimated_s` (libellé « estimation »). API : `GET /chapters/{id}/estimate`, `GET /projects/{id}/estimate`.
Chaque preset texte → image déclare son pendant « avec références » du même palier :

```yaml
with_references: qwen-image-edit-ref-rapide   # dans qwen-image-base-rapide.yaml
```

Une case dont un personnage a une planche de référence prend donc `qwen-image-edit-ref-rapide` dans une
série Rapide, `qwen-image-edit-ref` dans une série Qualité. `defaults.yaml → workflow_with_references`
ne sert plus qu'aux presets sans `with_references`. La taille de génération reste celle de la mise en page
(≈ 1 Mpx, `layout.yaml`) pour tous les paliers, cases avec références comprises.

### Palier croquis et passage au propre

Montrer **toute la page en brouillon en quelques secondes**, laisser l'auteur trier, et ne payer la
version propre que pour les compositions retenues — sans que le passage au propre change la composition.

| Preset | Rôle | Usage | Taille | Étapes | `estimated_s` |
| --- | --- | --- | --- | --- | --- |
| `qwen-image-croquis` | `croquis` | brouillon texte → image (modèle Turbo) | `long_side: 512` | 6 | 6 |
| `qwen-image-edit-ref-croquis` | `croquis` | brouillon avec images de référence | `long_side: 512` | 6 | 10 |
| `qwen-image-turbo-from-sketch` | `propre` | Turbo depuis le croquis validé | mise en page | 8 | 15 |
| `qwen-image-edit-ref-turbo-from-sketch` | `propre` | idem, avec références | mise en page | 8 | 55 |
| `qwen-image-base-rapide-from-sketch` (+ `qwen-image-edit-ref-rapide-from-sketch`) | `propre` | Rapide depuis le croquis | mise en page | 25 | 40 / 160 |
| `qwen-image-base-qualite-from-sketch` (+ `qwen-image-edit-ref-qualite-from-sketch`) | `propre` | Qualité depuis le croquis (cfg 2,5, défaut) | mise en page | 35 | 112 / 448 |
| `qwen-image-base-from-sketch` (+ `qwen-image-edit-ref-from-sketch`) | `propre` | Qualité max depuis le croquis | mise en page | 50 | 50 / 190 |

Champs propres à ce palier (vérifiés au chargement, erreurs dans `GET /presets`) :

```yaml
role: croquis                  # generation (défaut, palier de série) | croquis | propre
long_side: 512                 # croquis : grand côté en px ; l'autre suit le ratio de la case (multiple de layout.yaml)
from_sketch: qwen-image-turbo-from-sketch   # palier de série → son « propre depuis croquis » (même palier)
source_image: { node: "30", input: image }  # propre : LoadImage qui reçoit le croquis validé
mapping:
  denoise: { node: "9", input: denoise }    # propre : obligatoire (débruitage partiel)
defaults:
  denoise: 0.65                # propre : 0 = croquis inchangé, 1 = image neuve (composition perdue)
```

- **Croquer** (onglet **Croquis** du chapitre, ou `POST /pages/{id}/sketch`, `/chapters/{id}/sketch`,
  `/panels/{id}/sketch`) : un croquis par case **non encore validée** (ni version propre choisie, ni
  croquis validé), avec `defaults.workflow_sketch` — ou son `with_references` si un personnage, le décor
  ou un objet de la case a une image de référence. Mêmes LoRA (série, fiches) et mêmes références que la
  version propre. File ComfyUI habituelle (une génération à la fois), progression en direct.
- Un croquis est une version de case (`PanelImage`) marquée **`kind: croquis`** : jamais choisie (pas
  même la 1re version d'une case), jamais assemblée, lettrée, exportée, ni contrôlée par le QC
  automatique. Une case qui n'a que des croquis reste « à générer ».
- **Trier** (écran Croquis, entièrement au clavier) : `V`/`Entrée` valide la composition et passe à la
  case suivante, `R` re-croque (nouvelle graine ; retire la validation), `E` modifie la description puis
  re-croque (`Ctrl+Entrée`), `U` retire la validation, `←`/`→` changent de case, `C` croque la page.
  API : `POST /panels/{id}/sketch/validate` (`image_id` facultatif), `DELETE` pour retirer.
- **Passer au propre** (case, page, chapitre : `POST /panels|pages|chapters/{id}/clean`) : version
  finale au palier de la série (`from_sketch` du preset de la case ou de la série, puis son
  `with_references` si besoin) en **image → image** : le croquis validé est envoyé à ComfyUI, agrandi à
  la taille finale (`ImageScale`), encodé (`VAEEncode`) et débruité partiellement, **même graine et même
  prompt** que le croquis. La version produite garde sa source dans `params.composition`
  (`source`, `image_id`, `version`, `method: img2img`, `denoise`). Mode du passage au propre (fiche
  série, `clean_mode`) : `img2img` (défaut, ci-dessus) ou `controlnet` — voir « Verrouillage de
  composition » ci-dessous. Une composition n'est passée au propre qu'une fois
  (re-croquer et valider à nouveau pour recommencer). La 1re version propre est choisie d'office ;
  « Régénérer en Qualité » est inchangé.
- **Débruitage** : demande > case (atelier, `PATCH /panels/{id}` `sketch_denoise`) > série (fiche
  série, `sketch_denoise`) > `defaults.denoise` du preset `propre`. Plus bas = plus fidèle au croquis.
- **Activation** : `defaults.yaml → sketch_enabled` (vrai) pour les nouvelles séries ; case « Croquer
  les pages avant de les produire » de la fiche série pour le désactiver (l'onglet Croquis disparaît).
- **Estimation** : l'écran affiche « croquis de la page » et « passage au propre des cases validées »
  (`GET /pages/{id}/sketch-estimate`, `/chapters/{id}/sketch-estimate`), même calcul que le temps
  estimé (médiane réelle dès 3 générations du preset, sinon `estimated_s`).
- Le réglage « Étapes » du dessinateur (écran « L'équipe ») ne s'applique **pas** aux presets croquis :
  ils gardent leurs quelques étapes.
- Graphes provisoires construits avec des nœuds natifs (nœuds `30` LoadImage → `31` ImageScale → `32`
  VAEEncode → latent du KSampler `9`, `8 EmptyLatentImage` retiré) : **à remplacer** par les exports
  réels de Morigane (`~/mangaka-comfy-exports/`) — seuls les JSON et le mapping changent, puis
  `UPDATE_GOLDEN=1 npm run test:engine`. Le ComfyUI factice simule les deux : crayonné gris pour un
  croquis, croquis « encré » à la taille finale pour un passage au propre.

### Verrouillage de composition (ControlNet Union, patch de modèle)

Sans ControlNet, la composition est *demandée* par le texte ; avec, elle est **imposée** par une image
guide : le passage au propre et les régénérations gardent exactement le cadrage et les poses.

Modèle : **Qwen-Image-2.1-Fun-Controlnet-Union** (Alibaba PAI), fichier
`qwen_image_2.1_fun_controlnet_union_int8_convrot.safetensors` (3,78 Go), **un seul fichier** pour
toutes les conditions (trait, profondeur, pose, scribble, Canny…). Ce n'est **pas** un ControlNet
classique mais un **patch de modèle** : dossier `ComfyUI/models/model_patches/`, chargé par
`ModelPatchLoader` et appliqué au modèle par `QwenImageDiffsynthControlnet` (modèle, patch, VAE, image
de contrôle, `strength`, masque optionnel). Ne pas utiliser `ControlNetLoader` / `ControlNetApply`.
Prétraitements : `comfyui_controlnet_aux` (`LineArtPreprocessor`, `DepthAnythingV2Preprocessor`,
`DWPreprocessor`, `ScribblePreprocessor`) et le nœud natif `Canny`.

| Preset | Pendant ControlNet de | `estimated_s` |
| --- | --- | --- |
| `qwen-image-turbo-controlnet` (+ `qwen-image-edit-ref-turbo-controlnet`) | Turbo | 25 / 90 |
| `qwen-image-base-rapide-controlnet` (+ `qwen-image-edit-ref-rapide-controlnet`) | Rapide | 70 / 250 |
| `qwen-image-base-qualite-controlnet` (+ `qwen-image-edit-ref-qualite-controlnet`) | Qualité | 196 / 700 |
| `qwen-image-base-controlnet` (+ `qwen-image-edit-ref-controlnet`) | Qualité max | 85 / 300 |

Même graphe que le palier, **mêmes ids** (`1` modèle, `2` encodeur, `6` prompts, `8` latent, `9`
échantillonneur, `11` sortie) ; nœuds ajoutés : `40` ModelPatchLoader, `41` LoadImage (image guide), `42`
prétraitement (remplacé selon le type), `43` ImageScale (carte à la taille de la case), `44`
QwenImageDiffsynthControlnet (entre le modèle et le cache `4` → échantillonneur `9`), `45` SaveImage de
la carte (aperçu seulement, retiré du graphe de génération). Les **LoRA sont chaînés avant le patch**
(`lora_chain.model_from` = nœud `1`, consommé par `44`).

```yaml
# Palier de série → son pendant ControlNet (même palier ; with_references du pendant pour les références)
with_control: qwen-image-turbo-controlnet
# Preset ControlNet
role: controle
control:
  patch: { node: "40", input: name }        # chargeur du patch : fichier vérifié par « Tester la connexion »
  apply: { node: "44", input: strength }    # nœud qui applique le patch, entrée de la force
  image: { node: "41", input: image }       # LoadImage qui reçoit l'image guide envoyée à ComfyUI
  preprocessor: "42"                        # nœud remplacé par le prétraitement du type choisi
  resize: "43"                              # reçoit width / height de la case
  map_output: "45"                          # SaveImage de la carte (aperçu de l'atelier)
  default_type: lineart
  default_strength: 1.0                     # 0 = contrôle ignoré, 1 = composition tenue, jusqu'à 2
  types:
    lineart:
      name: Trait
      class_type: LineArtPreprocessor
      inputs: { coarse: disable, resolution: 1024 }
      post:                                 # post-traitements de la carte, entre `preprocessor` et `resize`
        - { class_type: ImageInvert, name: Inversion }
    carte: { name: Carte déjà prête }       # sans class_type : l'image guide est déjà une carte
```

**Pourquoi « Trait » inverse sa carte** (`post: ImageInvert`, mesuré le 10/10 sur la GX10, ComfyUI 0.39) :
`LineArtPreprocessor` rend un **trait blanc sur fond noir**, et le ControlNet Union de Qwen-Image 2.1
**encode la carte avec le VAE** (contrairement à un ControlNet classique) : le modèle recopiait ce fond
noir et la case sortait **en négatif** (88 % de noir, luminance moyenne 17). Inversée — trait noir sur fond
clair — la case est correcte (moyenne 237, 11-13 s à chaud). Les autres types (Profondeur, Pose, Croquis à
la main, Contours nets) marchent tels quels, et « Carte déjà prête » n'est jamais retouchée : aucun `post`.
Le constructeur insère chaque nœud de `post` (ids après ceux du JSON : `46` pour l'inversion) entre le
prétraitement `42` et la mise à la taille `43` ; l'aperçu de l'atelier (`map_output`) montre donc la carte
réellement envoyée au modèle. « Tester la connexion » vérifie aussi ces nœuds dans `/object_info` : s'il
en manque un, seul le type concerné est masqué, comme pour un prétraitement absent.

Types livrés : **Trait** (`lineart`, défaut), **Profondeur** (`depth`), **Pose** (`pose`), **Croquis à
la main** (`scribble`), **Contours nets** (`canny`), **Carte déjà prête** (`carte`, sans prétraitement).
Un type se règle ou s'ajoute dans le YAML (classe, entrées constantes, `image_input`, `post`, `order`),
jamais dans le code.

- **Verrouiller** (atelier, bloc « Composition » d'une case) : source = croquis validé, n'importe quelle
  version de la case (propre ou croquis) ou image importée (croquis à la main, photo de pose) ; type ;
  force. API : `POST /panels/{id}/composition-lock` (`source: croquis|version`, `image_id`, `type`,
  `strength`), `POST /panels/{id}/composition-lock/import` (multipart `file`, `type`, `strength`),
  `PATCH` (type, force), `DELETE` (déverrouiller). Un aperçu de la **carte de contrôle** est calculé
  dans la file ComfyUI (job `control_map` : image guide → prétraitement → carte, sans modèle) et
  affiché dans l'atelier (`GET /panels/{id}/composition-lock/preview`) ; changer de type le recalcule.
- **Tant que la case est verrouillée**, toute génération (Générer, variantes, Même seed, Régénérer en
  Qualité, essais automatiques du QC) passe par le pendant `with_control` du palier demandé, avec l'image
  guide. Badge « composition verrouillée » sur la case. La version produite note sa source et son
  contrôle : `params.composition` (`method: controlnet`, `source`, `image_id`/`path`, `type`,
  `strength`, `locked`) et `params.control` (type, prétraitement, fichier du patch, force).
- **Passage au propre par ControlNet** (fiche série, « Passage au propre : ControlNet », `clean_mode:
  controlnet`, type `clean_control`) : le croquis validé est l'image guide, même graine et même prompt,
  pas de débruitage. `img2img` reste le défaut.
- Supprimer la version qui sert d'image guide déverrouille la case (jamais de case cassée).
- **Disponibilité** : `GET /comfyui/control` (gardé 30 s, rafraîchi par « Tester la connexion ») dit si
  `ModelPatchLoader`, `QwenImageDiffsynthControlnet` et le fichier du patch figurent dans
  `/object_info`, et quels prétraitements sont installés. Sinon : message clair en français, l'atelier
  et la fiche série masquent l'option, verrouiller est refusé, une case déjà verrouillée refuse d'être
  régénérée (« déverrouille la case »), « Générer la page » la laisse de côté — les autres paliers et
  les autres cases marchent normalement. Avec le ComfyUI factice (mock), tout est disponible : la carte
  simulée est le contour de l'image guide, la version « CONTROLNET » repart de l'image guide.
- Installation (mise à jour de ComfyUI + téléchargement du patch) : en attente du feu vert du manager ;
  le code ne dépend que des presets. Graphes à confronter à l'export réel de Morigane puis
  `UPDATE_GOLDEN=1 npm run test:engine`.

### Case d'essai (`trial`)

Le bloc `trial` d'un preset donne les paramètres de « Générer une case d'essai » (tableau de bord) :
prompt d'essai, petite taille, peu d'étapes. Une seule vraie génération, qui passe par la file ComfyUI ;
l'image et sa durée en secondes s'affichent sous le bouton.

### Tester la connexion

`GET /comfyui/check` (bouton « Tester la connexion » du tableau de bord) interroge `/system_stats` et
`/object_info` du vrai ComfyUI et liste, par preset : les nœuds inconnus (« nœud inconnu : … ») et les
valeurs fixes absentes des listes de ComfyUI (« modèle introuvable dans ComfyUI : x.safetensors — à
placer dans ComfyUI/models/diffusion_models/ », encodeur, VAE, échantillonneur…), puis les LoRA saisis dans les séries et les fiches absents de `models/loras/`.
Les presets ControlNet (`role: controle`) sont **optionnels** : s'il manque `QwenImageDiffsynthControlnet`,
`ModelPatchLoader` (« ComfyUI à mettre à jour ») ou le fichier du patch (« à placer dans
ComfyUI/models/model_patches/ »), ils sont signalés mais le test reste bon ; la section « Verrouillage de
composition » du rapport (`control`) explique pourquoi l'option est masquée dans l'atelier.
Avec `COMFYUI_PROVIDER=mock`, il répond « ComfyUI simulé ».

## Images de référence et LoRA (étape 3)

Les presets acceptent des LoRA ; tous les presets « avec images de référence » (edit-ref de chaque palier :
Turbo, Rapide, Qualité, Qualité max, croquis, passage au propre, ControlNet ; et les réparations) ont
**5 emplacements**, branchés sur `images.image_1…5` de `TextEncodeQwenImage21`. L'encodeur en accepte
jusqu'à 16 (entrée `images` de type autogrow, `image_1` à `image_16` dans
`engine/tests/fixtures/comfyui/object_info.json`) : 5 couvre une case à 4-5 personnages sans alourdir
l'encodage (chaque image ajoute ses latents à la séquence). `test_workflow_build.py` vérifie que tous
les presets avec références déclarent le même nombre d'emplacements, dans la limite de l'encodeur
(Qwen-Image 2.1 : l'édition / la référence est intégrée au modèle, pas de modèle « edit » séparé). Ils sont
choisis automatiquement (selon le palier de la série) quand un personnage, le décor ou un objet de la
case a une image de référence (bibliothèque de la série : onglets Personnages / Objets / Décors).

### Emplacements de référence (`reference_images`)

Liste **ordonnée** d'emplacements, chacun étant un nœud qui charge une image (`LoadImage`) :

```yaml
reference_images:
  - { node: "20", input: image }   # 1er emplacement → images.image_1 de l'encodeur (nœud 6)
  - { node: "21", input: image }
  - { node: "22", input: image }
  - { node: "23", input: image }
  - { node: "24", input: image }   # 5e emplacement → images.image_5
  # avec un redimensionnement propre à l'emplacement : { node: "20", input: image, remove: ["30"] }
```

- Le moteur envoie les images de référence de la case à ComfyUI (`POST /upload/image`,
  sous-dossier `input/mangaka/`) et écrit le nom obtenu dans `workflow[node].inputs[input]`.
  **Priorité (par importance)** : une fiche par personnage de la case — ceux qui **parlent** d'abord
  (ordre des bulles), puis l'ordre de la case —, puis son décor et ses objets, puis la planche de
  style si elle est jointe aux cases. Un personnage présent n'est jamais écarté tant qu'un décor, un
  objet ou le style occupe un emplacement. Les fiches qui avaient une image mais n'ont pas eu
  d'emplacement sont notées sur le job et la version (`params.dropped_references` : sorte, id, nom) et
  l'atelier affiche « Référence non envoyée : … » sous « Références utilisées ». Les emplacements se remplissent par tours : 1re image de chaque fiche dans cet ordre, puis
  2e image de chacune, etc. Exemple à 3 emplacements avec Aiko (2 images), le labo (2 images) et le
  robot (1 image) : Aiko n° 1, labo n° 1, robot n° 1 ; sans le robot : Aiko n° 1, labo n° 1, Aiko n° 2.
  `panel_references` de `defaults.yaml` : `principale` (livré) = un seul tour, l'**image principale**
  de chaque fiche (la 1re de sa galerie, à choisir parmi ses vues simples : une planche multi-poses
  est recopiée telle quelle par le modèle) ; `toutes` = tours successifs comme ci-dessus.
  Le prompt envoyé nomme chaque image dans l'ordre des emplacements (`references` de
  `image_prompt.yaml`, voir « Prompt final des cases »).
  Les emplacements retenus sont notés sur le job (`params.references` : emplacement, sorte, fiche,
  image) et sur la version produite (`params.reference_images`) : l'atelier les affiche
  (« Références utilisées »).
- Un emplacement **inutilisé est retiré** : son nœud et ceux listés dans `remove` (ex. son
  redimensionnement) sont supprimés, puis toute entrée d'un autre nœud qui pointait vers un nœud
  retiré est effacée. Exemple : avec une seule référence, `images.image_2` à `images.image_5` disparaissent
  de l'encodeur `TextEncodeQwenImage21` (entrées optionnelles). L'encodeur redimensionne lui-même les
  références (`resolution: 1024`), d'où l'absence de nœud de redimensionnement.
- `remove` doit donc lister **tous** les nœuds propres à l'emplacement : une entrée obligatoire
  qui pointerait encore vers un nœud retiré ferait refuser le workflow par ComfyUI.
- Vérifié au chargement : chaque nœud existe, l'entrée existe, et aucun nœud mappé (prompt,
  seed, sortie…) n'est retiré.

### Chaîne LoRA (`lora_chain`)

```yaml
lora_chain:
  class_type: LoraLoaderModelOnly          # classe du chargeur (aucun nom codé dans le moteur)
  model_from: { node: "1", output: 0 }     # sortie MODEL après laquelle insérer la chaîne
  model_input: model                       # entrée MODEL du chargeur
  name_input: lora_name                    # entrée « nom du fichier »
  strength_input: strength_model           # entrée « poids »
  # Optionnel, pour un chargeur qui modifie aussi l'encodeur (ex. LoraLoader) :
  # clip_from: { node: "2", output: 0 }
  # clip_input: clip
  # clip_strength_input: strength_clip
  # clip_output: 1
  # extra_inputs: {}                       # entrées constantes du chargeur
```

LoRA appliqués, dans l'ordre : **LoRA de style de la série**, puis **LoRA d'identité de chaque
personnage** de la case, puis le LoRA de son **décor** et de chacun de ses **objets** (nom de fichier +
poids choisis dans la série / la fiche ; un même fichier n'est chargé qu'une fois). Chaque LoRA
devient un nœud `class_type` (identifiant numérique après le plus grand du JSON) :
`model_from → LoRA 1 → LoRA 2 → …`, et tous les nœuds qui consommaient `model_from` (ici le nœud
`4`, `QwenImage21Cache`) reçoivent la sortie du dernier LoRA. Sans LoRA, le workflow est
inchangé. Un preset sans `lora_chain` refuse une génération qui demande des LoRA (message lisible).

Les fichiers LoRA vont dans `ComfyUI/models/loras/` ; le nom saisi doit être exactement celui que
ComfyUI liste (sous-dossier compris, ex. `mangaka/aiko-v3.safetensors`).

### Ré-exporter un workflow depuis ComfyUI

Les JSON livrés ont été construits d'après le sous-graphe « Image Edit (Qwen Image 2.1) » du workflow de
référence de la GX10, puis validés contre le ComfyUI 0.37 de la machine. Pour repartir d'un export :

1. Ouvre le workflow dans ComfyUI. S'il contient un **sous-graphe**, déplie-le (clic droit → « Unpack
   subgraph ») : le format API exporte les nœuds réels. Vérifie qu'il tourne (avec 5 `LoadImage` branchés
   sur `images.image_1…5` de `TextEncodeQwenImage21` pour les presets « avec références ») et retire les
   LoRA (le moteur les insère).
2. Exporte-le au **format API** (« Workflow → Export (API) », « Save (API Format) » selon les versions)
   et remplace `presets/workflows/<id>.json`. Pour l'autre palier, change seulement `unet_name`,
   `clip_name` et `steps` (le graphe doit rester identique : `test_workflow_golden.py` le vérifie).
3. Dans `presets/workflows/<id>.yaml`, mets à jour les numéros de nœuds :
   - `mapping` : prompts (`prompt` / `negative_prompt` de `TextEncodeQwenImage21`), `KSampler`
     (`seed`, `steps`, `cfg`), taille (`EmptyLatentImage`) et `SaveImage` (`filename_prefix`) ;
   - `output_node` : le `SaveImage` ;
   - `reference_images` : les `LoadImage` dans l'ordre, avec dans `remove` les nœuds qui ne servent
     qu'à cet emplacement ;
   - `lora_chain.model_from` : la sortie du chargeur de modèle (`UNETLoader`).
4. Redémarre le moteur : `GET /presets` affiche les erreurs de mapping éventuelles ; puis « Tester la
   connexion » et « Générer une case d'essai » sur le tableau de bord.
5. Régénère les JSON de référence des tests : `UPDATE_GOLDEN=1 npm run test:engine`, relis le diff.

## Finition d'impression (`upscalers/*.yaml`)

Les cases sont générées à ≈ 1 Mpx (`layout.yaml`) alors que la zone utile A4 300 dpi fait 2161 × 3154 px :
imprimée, une case pleine page sort à ≈ 115 dpi, une bande sur deux à ≈ 164 dpi. La **finition** agrandit la
version **retenue** avec un modèle (quelques secondes, composition gardée) au lieu de la régénérer en Qualité
(≈ 280 s, composition qui peut changer).

### Facteur calculé par case

- **Boîte imprimée** : la boîte de la case en px du format (dpi du format de page), **fond perdu compris**
  (+ `bleed_mm` sur chaque bord posé au bord de la page, comme à l'export « fond perdu »).
- **Dpi effectif** = dpi du format ÷ max(largeur boîte ÷ largeur image, hauteur boîte ÷ hauteur image) (l'image
  est posée « au remplissage », recadrée au centre).
- Sous `finishing_tolerance` × dpi cible (`defaults.yaml`, 0,9 → 270 dpi pour 300 dpi), la case est à finaliser ;
  le **facteur** est celui qui amène l'image au dpi cible (jamais un ×3 fixe) et la **taille finale exacte** est
  `ceil(image × facteur)` : un côté tombe juste sur la boîte, l'autre la couvre.

### Quand

- **« Finaliser la page »** (atelier) : met en file la finition des cases dont la version retenue est sous le
  seuil ; **« Finaliser cette case »** (panneau de la case) ; **« Finaliser le chapitre pour l'impression »**
  (Lettrage › Export). API : `POST /pages/{id}/finish`, `POST /panels/{id}/finish`, `POST /chapters/{id}/finish`,
  `GET /pages/{id}/finishing`, `GET /presets/upscalers`.
- Les finitions passent dans **la même file** que les générations (job `finishing`) : une seule tâche ComfyUI à
  la fois.
- Le résultat est un **dérivé de la version** (`PanelImage.finish`), pas une nouvelle version de composition. Il
  est réutilisé tant que la version reste retenue ; retenir une autre version de la case efface la finition des
  autres versions **de cette case seulement** (fichier compris).
- **Assemblage** (rendu PNG / SVG, export ZIP) : image finalisée si elle existe, sinon la version retenue (comme
  avant). L'aperçu écran reste sur l'image légère. L'export signale les cases encore sous le seuil.
- **Indicateur** : chaque case de l'atelier affiche son dpi (« 115 dpi → 300 dpi après finition ») avec un badge
  d'alerte sous le seuil, vert au dpi cible ou une fois finalisée.

### Presets livrés

| Preset | Modèle (`ComfyUI/models/…`) | Usage |
| --- | --- | --- |
| `realesrgan-x4plus-anime-6b` (**défaut**) | `upscale_models/RealESRGAN_x4plus_anime_6B.pth` | Meilleur pour le trait encré et les aplats |
| `ultrasharp-4x` | `upscale_models/4x-UltraSharp.pth` | Plus de micro-détail (peut durcir les trames) |
| `remacri-4x` | `upscale_models/4x_foolhardy_Remacri.pth` | Rendu doux : lavis, couleur directe |
| `seedvr2-7b` (haute fidélité) | `diffusion_models/seedvr2_7b_int8_convrot.safetensors` + `vae/seedvr2_ema_vae_fp16.safetensors` | Restauration par diffusion (nœuds SeedVR2 natifs de ComfyUI), bien plus lente : jamais par défaut |

Tous sont déjà sur la GX10 : rien à télécharger. L'agrandisseur par défaut est `upscaler` dans `defaults.yaml` ;
chaque série peut choisir le sien (fiche série › « Agrandisseur (finition d'impression) », champ `upscaler` de
`PATCH /projects/{id}`, `null` = celui de `defaults.yaml`).

```yaml
id: realesrgan-x4plus-anime-6b
name: Real-ESRGAN x4plus anime 6B
workflow_file: realesrgan-x4plus-anime-6b.json
output_node: "5"                       # SaveImage
model_scale: 4                         # facteur natif du modèle (informatif)
high_fidelity: false                   # true : option lente, signalée dans la fiche série
timeout_s: 300
estimated_s: 6                         # durée estimée dans la file tant qu'il n'y a pas de mesures
mapping:                               # obligatoires : image, width, height
  image: { node: "1", input: image }   # LoadImage : la version retenue, envoyée par le moteur (/upload/image)
  width: { node: "4", input: width }   # taille finale exacte, calculée par case
  height: { node: "4", input: height }
  filename_prefix: { node: "5", input: filename_prefix }
```

Graphe ESRGAN : `1 LoadImage` → `3 ImageUpscaleWithModel` (modèle `2 UpscaleModelLoader`, ×4) → `4 ImageScale`
(lanczos, taille finale exacte, sans recadrage) → `5 SaveImage`. Graphe SeedVR2 (repris du workflow « Upscale
planche - SeedVR2 7B » de la GX10) : `1 LoadImage` → `3 ImageScale` (taille finale) → `4 SeedVR2Preprocess` →
`5 VAEEncodeTiled` → `7 SeedVR2Conditioning` + `9 KSampler` (1 étape) → `10 VAEDecodeTiled` →
`11 SeedVR2PostProcessing` (recalé sur `3`) → `12 SaveImage`.

Comme pour les workflows, les noms de modèles vivent **uniquement** dans les JSON : le moteur n'en connaît aucun.
« Tester la connexion » vérifie aussi les agrandisseurs (nœuds inconnus, « modèle introuvable dans ComfyUI : … — à
placer dans ComfyUI/models/upscale_models/ »). En mode mock, le ComfyUI factice agrandit l'image envoyée avec
Pillow (aucune GPU).


## Réparation ciblée (inpainting)

Une case réussie à 90 % avec une main ou un visage raté ne se régénère plus entièrement : dans
l'atelier, « Réparer cette main / ce visage » (panneau Contrôle qualité, depuis les boîtes du QC
stockées dans `PanelImage.detections`) ou « Réparer une zone… » (fenêtre d'une version : rectangle,
pinceau, gomme) ouvre la fenêtre de réparation. Échap annule, Ctrl + Entrée lance.

**Presets.** Un workflow qui a un bloc `inpaint` est un preset de réparation : il n'est jamais
proposé pour générer une case (ni dans la liste « Workflow » de l'atelier, ni comme palier). Un par
palier, avec les mêmes fichiers de modèle que le palier :

| Preset | Palier | Étapes | `estimated_s` |
| --- | --- | --- | --- |
| `qwen-image-inpaint-turbo` | Turbo (`workflow_inpaint` de `defaults.yaml`) | 8 | 40 |
| `qwen-image-inpaint-rapide` | Rapide | 25 | 120 |
| `qwen-image-inpaint` | Qualité | 50 | 140 |

Chaque workflow de génération désigne le sien (`inpaint_with: qwen-image-inpaint-rapide`) ; le
moteur prend celui du workflow **de la version réparée**, sinon celui du workflow de la série, sinon
`defaults.workflow_inpaint`. Vérifié au chargement : `inpaint_with` / `workflow_inpaint` doivent
désigner un preset chargé qui a un bloc `inpaint` (sinon avertissement dans `GET /presets`).

Graphe (nœuds natifs, mêmes numéros que les autres presets) : `30 LoadImage` (version source) →
`32 VAEEncode` → `33 SetLatentNoiseMask` (← `31 LoadImageMask`, canal rouge, blanc = à repeindre) →
`9 KSampler` (`denoise` partiel) → `10 VAEDecode` → `11 SaveImage`. Pas d'`EmptyLatentImage` : la
taille est celle de la version. Références (`20`–`22`) et chaîne LoRA comme le preset « avec
références » du palier. **À confirmer** sur la GX10 avec un vrai essai (comme l'échantillonnage Turbo).

```yaml
mapping:                      # positive_prompt, negative_prompt, seed et denoise obligatoires
  denoise: { node: "9", input: denoise }      # pas de width / height
defaults:
  denoise: 0.45               # 0,3 = retouche légère ; 0,6 = zone redessinée franchement
inpaint:
  source_image: { node: "30", input: image }  # LoadImage : la version à réparer
  mask_image: { node: "31", input: image }    # LoadImageMask : masque agrandi et adouci par le moteur
  grow_px: 24                 # marge ajoutée autour de la zone (réglable dans l'atelier)
  feather_px: 16              # bords fondus (réglable)
  prompt_parts:               # prompt prérempli ; un morceau dont une variable est vide est omis
    - "$target."              # texte de `targets` selon la zone choisie
    - "Character: $character."    # personnage concerné : description, mots-clés, mots déclencheurs du LoRA
    - "Panel: $description."
    - "Style: $style."
  targets: { face: "…", hand: "…", zone: "…" }
```

Un preset de réparation n'a ni `trial`, ni `with_references`, ni `inpaint_with`, ni `tier.choice`.

**Masque et recollage.** Le masque brut (rectangles + masque peint) est gardé dans `data/`
(`params.repair.mask_path`), agrandi de `grow_px` puis adouci sur `feather_px` (flou gaussien borné :
au-delà de zone + marge + adoucissement, il vaut exactement 0). ComfyUI repeint ; le moteur **recolle
ensuite seulement la zone masquée** sur l'original (`pipeline/inpaint.py`) : hors de cette limite, les
pixels sont ceux de l'original au pixel près, même si l'aller-retour VAE a légèrement changé toute
l'image. Une image renvoyée un peu plus petite (côtés arrondis au multiple du VAE) est replacée au
centre.

**Résultat.** Une nouvelle version de la case, liée à sa source (`params.repair` : `source_image_id`,
`source_version`, zone, personnage, réglages), qui passe par la file unique (progression en direct) et
par le QC ; elle n'est pas choisie d'office (sauf si la case n'a aucune version choisie) et un rejet du
QC ne relance rien automatiquement (« à revoir ») : l'auteur la retient ou non. LoRA : style de la
série puis LoRA d'identité du personnage concerné ; images de référence du personnage concerné (sinon
celles de la case). Les versions du palier croquis (`params.kind: croquis`) ne se réparent pas.

API : `GET /panel-images/{id}/repair?target=hand&character_id=…` (préremplissage : preset, marge,
adoucissement, denoise, prompt) et `POST /panel-images/{id}/repair` (`regions` en px de l'image — une
boîte de `detections` peut être renvoyée telle quelle —, `mask_png` en data URL, `target`,
`character_id`, `prompt`, `grow_px`, `feather_px`, `denoise`, `seed`). ComfyUI factice : renvoie la
source légèrement modifiée partout et la zone masquée remplie d'une couleur hachurée.

**Plus tard (pas en v1)** : FaceDetailer (Impact Pack) + SAM `sam_vit_b_01ec64`, déjà installés sur la
GX10, pour un détourage plus fin qu'un rectangle — ce sera un autre preset `inpaint`, sans changer le moteur.

## Fiches de référence (`reference_sheets/*.yaml`)

Sur chaque fiche de la bibliothèque (personnage, objet, décor), le panneau **« Créer des références »**
génère des variantes d'un type de fiche dans la file ComfyUI (même progression, même annulation que
les cases), à partir de la description visuelle, des mots-clés, du LoRA de style de la série et du
LoRA de la fiche. **Par défaut, la fiche part de zéro** : texte → image au palier des fiches (`workflow_library` : Turbo ;
sinon celui de la série — Qualité sur demande), aucune image envoyée — même si la série a une référence de style.
**« Image de départ (facultatif) »** : une des images de référence de la fiche (ou une nouvelle, par
exemple la photo d'un croquis à la main, rangée avec les autres) part en image 1 du workflow
« avec références » du palier ; le morceau `$start` dit d'en garder le sujet, la silhouette et la pose.
**« Affiner »** repart d'une variante, envoyée en image 1 (workflow « avec références » du même
palier), avec une consigne (« cheveux plus courts »). La référence de style de la série ne vient
qu'après l'image du sujet (voir « Planche de style », `style_board.reference_sheets`). **« Garder comme
référence »** copie la variante parmi les images de référence de la fiche (8 au plus) ; la première
image est la référence principale, servie en premier quand les emplacements d'une case manquent.

**Fiches d'objet et de décor : personne dedans** (11/10/2026 — des personnages inventés apparaissaient
dans ces fiches, puis dans chaque case qui les recevait en référence) :

- jamais de planche de style jointe (`style_board.reference_sheets` : `object: never`, `decor: never`) ;
- palier Qualité imposé (`workflow: qwen-image-base-qualite` du type de fiche, son `with_references`
  pour « Affiner » ou une image de départ) : vrai CFG, donc leur négatif « person, people… » est lu ;
- `$style` sans les mots-clés marqués `people` des packs ;
- après chaque génération, le détecteur de visages du contrôle qualité (couche « détecteurs », seuil
  `detectors.face.min_confidence` de `qc.yaml`) passe sur l'image (`params.people_check`). Un visage
  trouvé : avertissement sur la variante (« Personnage détecté dans la fiche : régénérer avant de
  l'utiliser ») et **« Garder comme référence » refusé** (409) — la variante ne peut donc pas servir
  de référence aux cases. On la régénère, ou on l'accepte à la main (« Garder quand même »,
  `POST /reference-variants/{id}/keep` avec `{"accept_people": true}`, noté sur la variante).
  Détecteurs absents ou en erreur : rien n'est bloqué.

Un type de fiche = un fichier ; en ajouter un ne demande aucun code (il est validé au démarrage, une
erreur apparaît dans `GET /presets` et `GET /health`) :

```yaml
id: objet-eclate                 # unique, minuscules et tirets
name: Vue éclatée                # libellé de la liste déroulante
description: "Pièces séparées, alignées sur un axe."
kinds: [object]                  # character | object | decor (plusieurs possibles)
order: 30                        # ordre dans la liste
folder: eclate                   # facultatif : sous-dossier de la bibliothèque lisible
                                 # (objets/<nom>/eclate/) ; absent : l'id sans la sorte (`eclate`) ;
                                 # `angles` et `imports` sont réservés
width: 1024                      # multiples de 8, 256 à 2048
height: 768
workflow: null                   # null : `workflow_library` (Turbo), sinon palier de la série, ou Qualité si demandé ;
                                 # un id de workflows/ l'impose (le choix du palier est alors ignoré)
prompt:                          # morceaux assemblés ; un morceau dont une variable est vide est omis
  - "Exploded view of $name."     # en anglais, comme tout le texte côté image
  - "$description."
  - "Details: $keywords."        # mots-clés + mots déclencheurs du LoRA de la fiche
  - "Requested change: $instruction."   # consigne d'« Affiner » (omis sinon)
  - "$start is the starting image: keep the object and its silhouette."   # « <image1> » si une image de départ est choisie
  - "Style: $style."             # packs de style de la série + mots déclencheurs du LoRA de style
  - "The last image ($style_ref) is a style reference only."   # « <imageN> » si la référence de style est jointe
negative_prompt: "person, people, text"   # en anglais ; remplace le négatif du workflow (termes « pas de texte » toujours ajoutés)
large_build_keywords: [grand, géant, trapu, tall, stocky]   # facultatif : mots entiers (sans casse) cherchés dans la
                                 # description et les mots-clés de la fiche ; ceux trouvés remplissent $large_build
```

**Plein pied (`personnage-turnaround`)** (12/10/2026 — un personnage grand et trapu était coupé aux genoux en
16:9) : toile 4:3 de 1328×992 (même budget de pixels que 1536×864, 15 % de hauteur en plus, une colonne
≈ 443×992 par figure), morceau de cadrage « de la tête aux semelles, marge au-dessus et en dessous, figures
mises à l'échelle de la hauteur », négatif « cropped legs, cut-off feet, out of frame… », et morceau
`$large_build` pour un personnage décrit grand, géant, trapu, costaud… (figures réduites pour tenir en entier).

## Angles de caméra et cohérence anime (`camera_loras.yaml`)

Deux LoRA Qwen-Image 2.1 (apache-2.0), vérifiés sur la GX10 le 11/10/2026 (ComfyUI 0.39.0, base
`qwen_image_2.1_bf16` non distillée, `LoraLoaderModelOnly` à 1,0 : 192 patchs chacun, aucune clé ignorée,
aucune conversion). 40 pas en 1024² avec une référence ≈ 57 à 66 s.

| `id` | Fichier | Rôle | Mot déclencheur | Poids |
|---|---|---|---|---|
| `mva-v2` (défaut) | `Qwen21_Multiple-Angles_v2_000001500.safetensors` | angles (rang 64) : tourne nettement le sujet, jusqu'au dos | `<mva>` | 1,0 |
| `mva-v1` | `Qwen21_Multiple-Angles_v1_step1000.safetensors` | angles (rang 32), repli : garde l'identité | `<mva>` | 1,0 |
| `anime-consistency` | `Qwen2.1_Anime_consistency.safetensors` | identité, interrupteur de la série | — | 1,0 |

- **Paliers** (`tiers`) : nom du palier sans accent, en minuscules (`qualite`, `qualite-max`…). Turbo et
  Rapide ne sont pas testés : le LoRA n'y est jamais ajouté, et l'UI affiche « Disponible en palier Qualité »
  au lieu d'ignorer l'option en silence (la version note la raison dans `params.camera.skipped`).
- **Mot déclencheur** : `<mva>` ouvre le prompt, suivi du vocabulaire de caméra de la fiche du modèle
  (`angles[].camera` : « front-right quarter view, eye-level shot », « right side view, elevated shot »…).
  Le premier morceau de `prompts.sheet` / `prompts.panel` doit commencer par `$trigger`.
- **Poids** : modifiable dans l'UI à chaque génération ; la fiche du modèle conseille 0,8 si l'image recopie
  la référence sans tourner.
- **« Nouvel angle »** (fiche personnage, objet ou décor) : une vue de la fiche (la principale par défaut) en
  image 1, au `workflow` du catalogue (Qualité avec références) et à ses `steps`, quel que soit le palier de
  la série. La vue produite est une **candidate** de l'historique, comme toute fiche (12/10/2026 — elle se
  rangeait d'office) : **« Valider »** (`POST /reference-variants/{id}/keep`) la range parmi les images de
  référence, **étiquetée par son angle** (colonne `angle` des images, migration v23) ; refusé si un
  personnage est détecté dans un objet ou un décor (sauf « Valider quand même ») ou si la fiche est pleine ;
  les autres vues s'étiquettent à la main sous chaque image.
- **Vue servie à une case** : la vue étiquetée la plus proche de l'angle de la direction artistique (`angle`,
  et `plan` pour plongée / contre-plongée, table `direction_angles` ; le côté gauche/droite ne compte pas).
  Sans angle demandé ou sans vue étiquetée : la vue principale (angle supposé : `main_view`).
- **« Changer l'angle »** (atelier) : une nouvelle version de la case, la version choisie en image 1, même
  palier que « Nouvel angle » ; les autres versions ne bougent pas, la file reste une génération à la fois.
  Le verrou de composition est ignoré pour cette version (l'angle change la composition).
- **« Cohérence anime »** (fiche série, non par défaut) : le LoRA d'identité est chaîné après ceux de la
  série et des fiches dans chaque génération dont le palier le permet (cases, fiches de référence).

## Prompt final des cases (`image_prompt.yaml`)

### Prompts en anglais

Qwen-Image 2.1 est réglé pour l'anglais : son enhancer officiel écrit toujours le prompt texte → image
en anglais (édition : anglais ou chinois, jamais une autre langue), et la doc et les exemples ComfyUI
sont en anglais. Depuis le 11/10/2026, **tout le texte côté image est en anglais** : mots-clés des packs
de style et des réglages fins (`lang: en`), gabarits de `image_prompt.yaml` (`parts`, `references`,
`forbidden_text_terms`), fiches de référence, planche de style (`scene_prompt` des genres), réparation
(`prompt_parts`, `targets`), prompts négatifs des workflows, et le paragraphe du rédacteur de prompt.
**Ce que lit l'auteur reste en français** : interface, scénario, dialogues, lettrage, noms et
descriptions des packs, scène test affichée (`scene_test`). Un test (`tests/test_english_prompts.py`)
refuse tout mot français ou accent dans ces presets (seul « ligne claire », terme d'art, est admis).

Le prompt par fragments (repli du rédacteur) a des gabarits anglais et des plans / angles traduits par
`camera_terms` (« contre-plongée » → `low-angle shot`, « cadre penché » → `dutch angle (tilted
frame)`…), mais la description, le lieu, la mise en scène et l'ambiance y entrent tels que le scénario
les a écrits : seul le LLM traduit.

`parts` est une liste de morceaux `string.Template` assemblés dans l'ordre (`$plan` = plan de la
direction artistique appliquée, sinon celui du scénario, `$angle`, `$ambiance` et `$action` de la
direction artistique, `$shot` = plan du scénario — plans et angles traduits par `camera_terms` —,
`$description`, `$setting` (lieu de la case donné par le scénario : lieu, moment, éléments du décor —
présent même sans décor de la bibliothèque), `$staging` (mise en scène : qui fait quoi, où dans le
cadre), `$character_count` (« One character », « Two characters »…), `$characters`, `$decor` et `$objects` = décor et objets de la bibliothèque cités par la
case (présentés comme les personnages), `$style` (packs de style, voir « Packs de style »), `$bible` = notes de la bible sur les personnages de la
case, `$savoir_faire` = passages du savoir-faire de l'agent `image_prompt`) ; un morceau dont une
variable est vide est omis.
`character` met en forme un personnage (`$name`, `$details` = description visuelle + mots-clés).
`forbidden_text_terms` est toujours ajouté au prompt négatif du workflow (le texte est posé au
lettrage, jamais dessiné par le modèle), `negative_photo_terms` aussi (contre le photoréalisme :
« photorealistic, photograph, 3d render… »), `$style_lead` (phrase de style de la série, `style_lead`)
ouvre le prompt, suivi de `$finition` (mots-clés de la finition de la série, `style_options.yaml › finition`), et `strip_quotes` retire les répliques entre guillemets
de la description. Le prompt est stocké sur la case ; une édition manuelle est conservée jusqu'à
« reconstruire le prompt ».

**Série en noir et blanc** (`monochrome: true` du pack de rendu) : les lignes des images de référence
viennent de `references.monochrome` (« keep the face, hair and outfit », sans « colours ») ; les termes de
`monochrome_forbidden_terms` (noms de couleur, « colorful », « pastel »…) sont retirés du prompt positif **au
moment de l'envoi à ComfyUI** — prompts déjà stockés compris : « the thick green liquid » devient « the
thick liquid » — et refusés dans le paragraphe du rédacteur de prompt (règle `monochrome_writer_rule`,
`$palette_rule`) ; `monochrome_negative_terms` (« color, colored, colorful ») rejoint le prompt négatif.
Une série en couleur garde son prompt tel quel.

**Ambiance de la case contre ton de la série** (`mood_conflicts`) : quand l'ambiance de la direction
artistique d'une case contient l'un des `moods` d'une règle (peur, tension, tristesse, colère, menace…),
les mots-clés `drop` (« bright joyful atmosphere », « warm light », « smiles »…) sont retirés du style de
cette case et du prompt envoyé : l'ambiance de la case gagne toujours.

`references` cadre les images de référence dans le prompt **envoyé** à un workflow avec références
(au moment de la génération, le prompt stocké sur la case ne change pas ; la version garde les deux :
`params.prompt` envoyé, `params.panel_prompt` de la case) :

```yaml
references:   # syntaxe Qwen-Image 2.1 Edit : <image1>, <image2>…, rôle de chaque image défini en tête
  character: "<image$slot> is the identity reference for $name: keep the face, hair, outfit and colours; ignore its pose, framing and background."
  decor: "<image$slot> is the location reference for $name: keep its layout, architecture and materials; …"
  object: "<image$slot> is the design reference for the object $name: …"
  style: "<image$slot> is a style reference only (…): do not copy its characters, scene or composition."
  separator: " "
  before: ["$images"]           # avant le prompt de la case ($images : les lignes, $count : nombre d'images)
  after: ["Use the reference images for identity and design only (…): draw a new scene with new poses, a new camera angle (…). Exactly one continuous scene in a single panel: not a character sheet, not a turnaround, not a collage (…)"]
```

Un modèle d'édition recopie la pose et le cadrage de la référence si on ne lui dit pas le contraire (une
fiche de face donne des cases de face) : d'où « ignore its pose, framing and background » et « one
continuous scene, not a character sheet ». Il recopie aussi la **mise en page des planches** (grille de
poses, règles, étiquettes, fond blanc) : `references.sorting` donne pour chaque image envoyée, selon sa
sorte (`character`, `decor`, `object`, `style`), ce qu'il faut en prendre (« From <image1> take only the
face, hair, body and outfit of Kaï; ignore its layout, pose grid, rules, labels and white background. »).
Ces consignes entrent par `$sorting` dans `after` : elles sont donc ajoutées même à un prompt rédigé par
l'IA. Une sorte sans consigne (vide) n'en reçoit aucune ; aucun texte n'est codé dans le moteur. Un prompt qui **commence** par `<image1>` et cite exactement
les images envoyées, dans l'ordre (prompt rédigé par l'IA), ne reçoit pas les lignes de rôle une 2e fois,
seulement `after`. Un ancien prompt (français, « Image 1 : … », ou édité à la main) est toujours envoyé,
avec les lignes de rôle anglaises en tête.

Exemple (deux personnages, une image principale chacun, prompt par fragments) : « <image1> is the
identity reference for Kaï: … <image2> is the identity reference for Lina: … Wide shot. … Setting: …
Staging: … Two characters: Kaï (…); Lina (…). Style: … Use the reference images for identity and design
only … no plain white background. »

### Rédacteur de prompt (`prompts/redacteur-image.yaml`)

Qwen-Image 2.1 (encodeur Qwen3-VL) suit mieux **un paragraphe descriptif cohérent** que des fragments
étiquetés. Pour une série en « Prompt rédigé par l'IA » (fiche série ; **oui** pour les nouvelles
séries, `enabled` de ce fichier, réglable dans « L'équipe » › Dessinateur ; les séries d'avant la
migration v21 restent en fragments), le LLM texte de l'agent Dessinateur (DeepSeek par défaut, factice
en mode mock) écrit le prompt de chaque case :

- il reçoit les données structurées de la case (en français) : plan et angle, et leurs termes de
  cadrage anglais (`$camera`, via `camera_terms`), **action** de la direction artistique (`$action`),
  description, lieu, mise en scène, ambiance, personnages et leurs traits (description visuelle +
  mots-clés + déclencheurs LoRA), figurants sans fiche, personnages de la série **absents** (à ne jamais
  nommer), décor, objets, images de référence et leur rôle (« - <image1> is the identity reference for
  Aiko… », `$image_tags`), `$style` (bloc court), repères de la bible et savoir-faire — les répliques
  entre guillemets en sont retirées ;
- il **traduit** et écrit un long paragraphe anglais (180 à 320 mots ; l'enhancer officiel écrit ~20
  phrases), mis en scène comme une case de manga dessinée (raccourcis, lignes de fuite, traits de
  vitesse, épaisseur d'encre, trames, blancs — jamais d'objectif ni de profondeur de champ : un terme de
  `forbidden_photo_terms` fait refuser la réponse, en français, puis redemander) et dans cet ordre :
  phrase de style de la série (`$style_lead`, remise en tête par le moteur si elle manque), rôles des images de référence d'abord
  (`<image1> is the identity reference for Aiko: keep her face, hair, outfit and colours; ignore its
  pose, framing and background.`) → sujet avec un verbe d'action et la pose du corps (poids, membres,
  mouvement, geste), place de chacun dans le cadre, regard et expression → caméra en termes de cinéma
  (low-angle, over-the-shoulder, dutch angle, bird's-eye…) avec focale et profondeur → décor parcouru
  avec des repères de position (foreground / background, left / right…) → une phrase de lumière (source,
  direction, ombres) → une phrase de composition et d'ambiance, puis les mots-clés de style. Règles
  dures : exactement les personnages de la case, « a single continuous scene, one panel », aucun texte
  ni bulle ; jamais redécrire ce que montre une référence : la citer par `<imageN>` ;
- il rend un objet JSON `{"prompt", "language", "notes"}` validé par Pydantic puis contre la case :
  chaque personnage de la case nommé, aucun personnage absent nommé, chaque image envoyée citée par
  `<imageN>` et aucune autre, langue du preset (en anglais : pas de paragraphe resté en français —
  6 mots-outils français et plus de 4 % des mots), longueur plausible (entre 60 % de `min_words` et
  150 % de `max_words`). Invalide → un nouvel essai avec l'erreur (`max_retries: 1`, donc 2 tentatives
  au plus), puis **repli par fragments** avec un avertissement visible sur la case (« Prompt rédigé par
  l'IA indisponible (…) ») ;
- le paragraphe est nettoyé (guillemets et répliques retirés, une seule ligne) ; les mots-clés de
  style y sont ajoutés tels quels s'il ne les contient pas déjà.

`language` (`en` par défaut, ou `fr`) et `min_words` / `max_words` (180 à 320) sont des réglages du
preset (« L'équipe » › Dessinateur). Le prompt rédigé est stocké sur la case (`prompt_source: ia`)
**une fois par case** : une nouvelle génération (variantes, « Régénérer en Qualité ») le reprend tel
quel. Il n'est redemandé que sur « Reconstruire le prompt » ou quand les données de la case changent
(description, lieu, mise en scène, personnages, direction artistique, style, images de référence,
langue ; la bible et le savoir-faire n'y comptent pas) — les prompts rédigés en français avant le
passage à l'anglais sont donc réécrits à la génération suivante de leur case. Une édition manuelle est
conservée jusqu'à « Reconstruire le prompt ». La consigne `references.after` et les termes « pas de
texte » du prompt négatif sont ajoutés à l'envoi à ComfyUI, comme pour les fragments (les lignes de
rôle ne sont pas répétées : le paragraphe les définit déjà).
La rédaction a lieu dans le job de génération (message « Rédaction du prompt par l'IA… »), hors de
toute transaction ; « Reconstruire le prompt » l'attend (le proxy web laisse 3 min à cette route).

Repasser une série à « non » remet ses prompts rédigés (non retouchés) en fragments. Mode mock :
`[mock:prompt-invalide:N]` dans la description d'une case rend les N premiers essais invalides,
`[mock:prompt-intrus:N]` leur fait nommer un personnage absent. En anglais, le LLM factice n'écrit
que des phrases anglaises (rôles `<imageN>`, poses tirées d'une liste, caméra, lumière) : il ne sait pas
traduire, la description française de la case reste dans `notes`. L'essai du Dessinateur montre le
prompt rédigé à côté du prompt par fragments.

### Dialogue sur une case (`prompts/redacteur-image-dialogue.yaml`)

Dans l'atelier, « Demander à l'IA pour cette case » envoie une consigne en français (« plus serré, gros
plan sur le visage de Lucius, en contre-plongée », « Stan doit être en train de courir », « enlève le
décor, fond blanc ») au LLM du Dessinateur, avec le contexte de la case (scénario, direction artistique
appliquée, personnages, images envoyées, prompt actuel), les images de référence au choix par personnage
et l'historique des échanges sur la case. Réponse JSON validée (`max_retries`, puis erreur lisible ; la
case ne change pas) : `prompt` (mêmes contrôles que le rédacteur), `direction` facultative (`plan` et
`angle` parmi les valeurs de la direction artistique, `action`, `ambiance`), `references` facultatives
(`{"character", "image_id"}` parmi les images gardées de la fiche) et `explanation` (une phrase en
français). L'auteur voit l'ancien et le nouveau prompt et les champs changés, puis « Appliquer »,
« Appliquer et générer » (une nouvelle version de cette case seulement) ou « Annuler ». Appliqué, le
prompt est gardé comme une édition à la main et la direction / la référence restent propres à la case,
jusqu'à « Reconstruire le prompt » (qui accepte aussi une consigne : même gabarit, sans historique).
Variables : celles de `redacteur-image.yaml`, plus `$instruction`, `$current_prompt`,
`$current_direction`, `$plans`, `$angles`, `$camera_terms`, `$reference_options`, `$history`.

## Lettrage (étape 5)

Le texte n'est **jamais** dessiné par le modèle d'image : il est posé au lettrage, en vectoriel.

- `fonts.yaml` : `fonts` (id → fichier + nom) et `styles` par type de bulle (`speech`, `thought`,
  `shout`, `narration`, `"off"` — entre guillemets, sinon YAML lit un booléen) : police, graisse
  (polices variables), taille en **points** (`size_pt`), taille minimale lisible (`min_size_pt`), plafond
  (`max_size_pt`), pas de réduction, interligne, capitales. `hyphenation` règle la césure française
  (pyphen). Faute de place à la taille minimale, la bulle garde tout son texte et la case affiche un
  avertissement. Une bulle dont le cadre est ajusté à la main (écran Lettrage) prend la plus grande
  taille qui remplit ce cadre, **en proportion** (les marges grandissent avec le texte : cadre ×2 → texte
  ×2, même retour à la ligne), entre `min_size_pt` et `max_size_pt` (absent : `size_pt` ; garde-fou
  livré ≈ ×5 la taille normale, au plus 72 pt) ; une taille
  saisie dans le panneau de la bulle l'emporte jusqu'au retour en « auto ». Pendant le glissé de la
  poignée, l'écran demande au moteur le texte exact du cadre (`POST /bubbles/{id}/fit`, rien
  d'enregistré) : la taille ne saute pas au lâcher, même quand le texte se remet à la ligne.
- `lettering.yaml` : marges intérieures par type, forme de la parole (ellipse / rectangle arrondi),
  nuage, pointes du cri, queue (longueur, base, direction par défaut sans visage détecté), écarts
  bulle ↔ bulle / bord de case / visage, couleurs, bordure des cases, repères de coupe.
- Fond perdu : `bleed_mm` du format de page. Feuille = `round((mm + 2 × fond perdu) / 25,4 × dpi)`
  → A4 300 DPI + 3 mm = 2551 × 3579 px.
- Visages : le lettrage évite les boîtes de visages enregistrées par le QC sur la version retenue
  (`PanelImage.detections.faces`, à défaut `PanelImage.params` : `faces`, `qc.faces`…, en px de l'image).
- Les SVG exportés embarquent un sous-ensemble renommé (`mk-…`) de chaque police (clause 3 de l'OFL).

### Onomatopées (type `sfx`)

« CLIC », « BIIIP ! », « VROUM ! » : grand texte sans bulle, lui aussi vectoriel (jamais dessiné par
le modèle d'image : « onomatopoeia » est dans `forbidden_text_terms` et le texte n'entre pas dans le
prompt de la case).

- `fonts.yaml` → `sfx` : police par intensité (`by_intensity` : Lilita One / Titan One / Bowlby One) et
  polices proposées dans l'écran Lettrage (`choices`), capitales, interligne.
- `lettering.yaml` → `sfx` : taille de base par intensité pour une case de `reference_panel_mm`
  (facteur borné par `scale_min` / `scale_max`, puis `min_size_pt` / `max_size_pt`, réduite si plus large
  que `max_width` × la case), remplissage, contour épais (`outline_pt`) et halo blanc (`halo_pt`),
  plages d'angle et de cisaillement (tirage déterministe, graine = l'onomatopée), **débordement
  maximal** hors de la case (`max_overflow_mm`, mesuré perpendiculairement à chaque bord : une
  onomatopée peut chevaucher une bordure), écarts avec les visages, bulles et autres onomatopées.
- Placement automatique après toutes les bulles de la page : en bas côté fin de lecture si possible,
  jamais sur un visage (QC), une bulle, une autre onomatopée ou une incrustation tant qu'il y a de la
  place (sinon avertissement). Placée à la main, elle est gardée, ramenée vers la case seulement si elle
  dépasse la limite.
- Écran Lettrage : « Onomatopées » pour en ajouter une ; sur la planche, glisser pour déplacer, rond
  bleu pour tourner, carré rose pour la taille (clavier : flèches, Alt + ←/→ tourner, Alt + ↑/↓ taille) ;
  le panneau règle texte, intensité, police, taille, angle et italique. API : `POST /panels/{id}/sfx`,
  `PATCH /bubbles/{id}` (`sfx` : `x`, `y`, `size_pt`, `angle`, `skew`, `font`, `intensity` ; `null` =
  automatique), `DELETE /bubbles/{id}`.
- Export : PNG (halo, contour, remplissage, transformés) et SVG (`<g transform="translate rotate
  skewX">` + `<text>` : le texte reste sélectionnable, police réduite embarquée).

### Polices disponibles

| Id | Nom | Fichiers | Graisse / italique |
| --- | --- | --- | --- |
| `baloo2` | Baloo 2 | `Baloo2.ttf` (variable) | `weight` 400 → 800 |
| `fredoka` | Fredoka | `Fredoka.ttf` (variable) | `weight` 300 → 700 |
| `bowlby-one` | Bowlby One | `BowlbyOne.ttf` | une seule graisse |
| `titan-one` | Titan One | `TitanOne.ttf` | une seule graisse |
| `lilita-one` | Lilita One | `LilitaOne.ttf` | une seule graisse |
| `comic-neue` | Comic Neue | `ComicNeue-Regular/Bold/Italic/BoldItalic.ttf` (famille statique) | `weight` ≥ 600 → Bold ; `italic: true` → Italic (Bold Italic si les deux) |

Une famille statique se déclare avec un fichier par variante (`file` = regular, `bold`, `italic`,
`bold_italic`, tous facultatifs sauf `file`). `italic: true` sur un style dont la police n'a pas de
fichier italique rend `fonts.yaml` invalide (pas de faux italique). Licences : `fonts/OFL.txt` et
`fonts/OFL-ComicNeue.txt`.

### Changer la police d'un style

Les styles par défaut ne changent pas (parole en Baloo 2). Pour passer un type de bulle en Comic
Neue, modifie son bloc dans `styles` de `fonts.yaml`, puis redémarre le moteur :

```yaml
styles:
  speech:            # parole en Comic Neue Bold
    font: comic-neue
    weight: 700      # ≥ 600 → ComicNeue-Bold.ttf ; 400 ou absent → ComicNeue-Regular.ttf
    size_pt: 9
    min_size_pt: 6.5
    line_height: 1.0
  thought:           # pensée en Comic Neue Italic
    font: comic-neue
    italic: true     # → ComicNeue-Italic.ttf
    size_pt: 8.5
    min_size_pt: 6.5
    line_height: 1.1
```

L'écran Lettrage affiche le nom de la police de la bulle sélectionnée (« Parole · Comic Neue · 9 pt »)
et `GET /presets` liste les polices déclarées (`fonts`). Le lettrage est recalculé avec la nouvelle
police (taille du texte réajustée) ; relance ensuite le rendu ou l'export de la page.

## Contrôle qualité (`qc.yaml`)

Tous les seuils du QC vivent ici (aucun n'a de valeur par défaut dans le code : une clé manquante
rend le fichier invalide et le QC indisponible, erreur visible dans `GET /presets`). Le fichier
commenté sert de référence ; l'essentiel :

| Clé | Rôle |
| --- | --- |
| `auto_after_generation` | QC automatique après chaque génération |
| `max_auto_retries` | Nouveaux essais (nouvelle seed) après un rejet automatique, avant « à revoir » |
| `verdict.ok_min` / `verdict.reject_below` | Score combiné ≥ `ok_min` → ok ; < `reject_below` → rejet ; entre les deux → à revoir |
| `weights` | Poids des couches `detectors` / `identity` / `vision` (renormalisés sur celles qui ont tourné) |
| `detectors.face\|hand\|text` | `min_confidence` (boîtes ignorées en dessous), `options` passées au détecteur deepghs, vérifiées au chargement (`level` : `n` ou `s` pour visages et mains ; `text.model` : modèle publié par deepghs ; liste dans `engine/mangaka_engine/providers/qc/dghs.py`) ; `hand.suspect_below` |
| `detectors.rules` | `missing_face`, `extra_face` (+ `tolerance`), `text`, `suspect_hand` (+ `max_penalty`), `too_dark` (facultative) : `penalty` (points retirés) et `at_least` (`review` / `reject` : verdict minimal imposé) |
| `detectors.face_count_ignored_for_shots` | Types de plan où le nombre de visages n'est pas vérifié (insert…) |
| `detectors.tone` | Tonalité (numpy sur l'image, CPU, sans modèle) : `dark_below` / `black_below` (niveaux de gris d'un pixel sombre / noir pur), `max_dark` / `max_black` (parts maximales, 0,45 / 0,25 au départ), `monochrome_only` (rendus N&B seulement), `skip_ambiance_keywords` (ambiance de la DA d'une scène de nuit ou sombre : non vérifiée). Au-delà, la règle `detectors.rules.too_dark` s'applique (« Case trop sombre : 68 % de pixels sombres, cible ≤ 45 % ») ; les deux parts s'affichent dans le panneau QC de l'atelier. Absent = jamais vérifiée |
| `identity` | `min_similarity` (1 − différence CCIP), règle `below`, `max_references`, `crop_scale` |
| `vision` | `mode` (`never` / `on_doubt` / `always`), `doubt_band` (score des couches 1-2 où la vision tranche), `max_retries`, `wait_idle_s`, `max_reasons`, `prompt` (`$description`, `$characters`, `$shot`) |
| `bench` | Banc d'essai : `target_recall` (part des mauvaises cases que le QC doit attraper ; base du seuil suggéré), `annotation_goal.min` / `.max` (taille visée de l'ensemble annoté) |

« Appliquer les seuils suggérés » (écran Banc d'essai QC) réécrit seulement `verdict.ok_min` (et
`verdict.reject_below` s'il dépassait le nouveau `ok_min`) et `identity.min_similarity`, sur leur ligne,
commentaires conservés ; le fichier est revalidé avant écriture puis rechargé à chaud. Ces clés doivent
donc rester écrites sur une ligne à part (`ok_min: 70`), pas en style `{ ... }`.

Installation des vraies couches sur la GX10 : `engine/.venv/bin/pip install -e "engine[qc]"` (détecteurs
et CCIP deepghs) et `ollama pull qwen3-vl:4b` (vision), puis `QC_DETECTORS_PROVIDER=dghs`,
`QC_IDENTITY_PROVIDER=dghs`, `VISION_PROVIDER=ollama` dans `.env`.

## L'équipe : agents du pipeline (`agents/*.yaml`)

Le pipeline reste du Python simple ; un « agent » n'est qu'une déclaration : nom, rôle, étape et
liste de réglages, chacun pointant vers le preset qui livre sa valeur. L'écran « L'équipe » en tire
une carte et un formulaire : **un nouvel agent (ex. Directeur artistique) = un nouveau YAML**, sans
code d'interface (un essai « Essayer » demande en plus une fonction dans
`engine/mangaka_engine/agents/trials.py`).

```yaml
id: scenariste
name: Scénariste
icon: "✒️"
role: Découpe chaque chapitre en pages puis en cases…
step: 1
step_label: Scénario
providers: [llm]                     # état « prêt / fournisseur injoignable / mal configuré »
llm: { provider: provider, model: model }
job_steps: [script]                  # jobs comptés comme « dernier passage »
summary: [provider, model]           # « modèle utilisé » sur la carte
trial: script                        # essai disponible (agents/trials.py)
secrets: [{ env: DEEPSEEK_API_KEY, label: Clé d'API DeepSeek }]   # seulement « présente / absente »
settings:
  - key: temperature
    label: Température
    group: Modèle
    type: number                     # text, longtext, prompt, prompt_list, number, integer, boolean, choice, list, yaml
    min: 0
    max: 2
    source: prompts/script.yaml#temperature
  - key: system
    label: Consignes système
    type: prompt
    source: prompts/script.yaml#system
    variables: [series_title, synopsis]   # toute autre $variable est refusée
```

`source` : `fichier.yaml#chemin.dans.le.fichier` (`defaults`, `providers`, `layout`, `image_prompt`,
`qc`, `fonts`, `lettering`, `prompts/<id>`), `workflows/*.yaml#…` (appliqué à chaque workflow qui
mappe le paramètre), `layouts/*.yaml#templates` (toute la bibliothèque de gabarits), `env:VARIABLE`
(choix fait dans `.env`, ex. `LLM_PROVIDER`) ou `profile` (stocké dans le profil seulement). Options :
`choices` / `choices_from` (`fonts`, `workflows`, `page_formats`), `nullable`, `env_override`,
`fallback`, `global_only` (réglage commun à toutes les séries). Un secret (`…KEY`, `…TOKEN`…) ne peut
jamais être un réglage. Chaque agent a en plus un « Savoir-faire » (noms de collections de la
bibliothèque + top-k) ; `knowledge_role` le relie à son rôle dans `knowledge.yaml` (valeur livrée), et
le profil prime sur ce fichier.

**Où vivent les réglages.** Les valeurs livrées restent dans les presets. Les modifications faites
dans l'UI sont des profils versionnés en SQLite (`agent_profiles`, `agent_profile_versions`) : un
profil global et, au besoin, une surcharge « pour cette série seulement ». Le pipeline applique
**série > profil global > presets** ; le résultat est revalidé par les mêmes schémas que le
chargeur (un réglage invalide est refusé avec un message lisible). Chaque modification crée une
version (auteur, date, différences) ; « Revenir à cette version » et « Revenir aux réglages
d'origine » créent une nouvelle version. « Exporter en YAML » donne le contenu complet des fichiers
presets de l'agent, à recopier dans `presets/` pour en faire les valeurs livrées.

## Savoir-faire et bible de série (`knowledge.yaml`)

Les fiches de méthode (synthèses et notes personnelles, pas des livres entiers) sont rangées dans
la **Bibliothèque de savoir-faire** (menu « Savoir-faire ») : collections globales ou rattachées à
une série, documents `.md` / `.txt` / `.pdf` (texte extrait par pypdf) ou texte collé.

- **Découpage** (`chunking`) : aux titres Markdown d'abord (un passage ne mélange jamais deux
  sections), puis aux paragraphes, phrases et mots pour tenir dans `max_tokens`. Jetons estimés à
  ≈ 4 caractères. Une **fiche d'un pack** est un seul passage tant qu'elle tient dans `fiche_max_tokens`
  (800) ; au-delà seulement elle est coupée aux paragraphes, et son fragment « Prompt (EN) » reste dans le
  dernier passage, précédé du titre de la fiche. Un découpage changé est refait au prochain import des
  packs (ou par « Réindexer »), sans doublon.
- **Index** : chaque passage a un vecteur (float32 en BLOB dans SQLite) et une entrée dans l'index
  plein texte FTS5. La comparaison des vecteurs se fait en **numpy** (force brute) : sqlite-vec
  n'est pas utilisé — aux volumes visés (quelques milliers de passages) c'est instantané, et cela
  évite de charger une extension SQLite dans chaque connexion. Modifier un document le réindexe.
- **Recherche hybride** (`retrieval`) : score = `vector_weight` × cosinus + `keyword_weight` ×
  BM25 normalisé (le meilleur passage par mots-clés vaut 1), `top_k` passages au plus, dans le
  `budget_tokens` de l'agent. Une collection de moins de `small_collection_tokens` jetons est
  injectée **entière**, sans recherche — sauf si l'agent la cite dans `searched_collections` : elle est
  alors cherchée comme une grande (le rédacteur de prompt y met « Rendu · Valeurs et masses », ≈ 680 jetons,
  qui avec Pont ComfyUI mangerait sinon tout son budget de 1 200 jetons).
- **Agents** (`agents`) : `script` (étape 1, variable `$savoir_faire` de `prompts/script.yaml`),
  `art_direction` (`prompts/direction-artistique.yaml`) et `image_prompt` (étape 3, voir ci-dessous).
  Collections par nom (casse ignorée) ; `series_collections: true` ajoute celles de la série du
  chapitre — jamais celles d'une autre série. Le champ « Savoir-faire » d'un profil d'agent (écran
  « L'équipe », `knowledge_role` de `agents/*.yaml`) prime sur cette liste, sur `top_k` et sur le
  budget de jetons, surcharge de série comprise (`KnowledgeBase.profile_lookup` / `profile_top_k` /
  `profile_budget`). Budget valide : 0 à 16 000 jetons (sinon 422 en français) ; champ vidé = valeur
  de ce fichier.
- **Deux budgets pour une case** (`image_prompt`). Une seule recherche par case, puis deux sélections
  dans le même classement :
  - **rédacteur de prompt** (LLM : rédaction automatique et « Dialogue », `$savoir_faire` / `$bible`
    de `prompts/redacteur-image*.yaml`) : `writer_budget_tokens` (1 200), `writer_top_k` (5),
    `writer_bible_max_tokens` (400). Les passages arrivent **entiers, numérotés avec leur source**
    (« [1] « Titre » — section (collection) », comme pour le scénariste et le DA) : un LLM qui écrit
    un paragraphe de 180 à 320 mots lit sans peine 1 à 2 k jetons de fiches de cadrage, d'angles, de
    gestuelle… C'est ce budget (et ce top-k) que règle « L'équipe » › Dessinateur ;
  - **prompt par fragments** (`$savoir_faire` / `$bible` d'`image_prompt.yaml`, et repli quand le
    rédacteur est désactivé ou en panne) : `budget_tokens` (160), `top_k` (2), `bible_max_tokens`
    (120), comme avant — une **note courte en une ligne**, car ce texte est collé tel quel dans le
    prompt du modèle d'image : de la théorie en français y nuirait.

  La requête d'une case reprend le plan du scénario, la direction artistique appliquée (plan, angle,
  ambiance, action : un « gros plan » en « contre-plongée » retrouve les fiches qui en parlent), la
  description, les personnages, le décor et les objets. `series_collections: true` : les collections
  rattachées à la série de la case s'ajoutent.

  **Pas de redondance** : une fiche n'est servie qu'une fois (une collection injectée entière, comme
  « Pont ComfyUI », n'est jamais reprise par la recherche) ; **une seule fiche de plan** (`SHOT_*`) et **une
  seule fiche d'angle** (`ANG_*`) d'un pack par case — la fiche de référence du plan / de l'angle de la case
  (`vocabulary.primary` du manifeste : « plan moyen » → SHOT_MS_001, « gros plan » → SHOT_CU_001), servie
  en premier même si son score est bas. Case sans plan (ou angle) connu : la mieux classée seulement ; angle
  sans fiche (« de face ») : aucune. Les autres familles (émotions, action, corps…) gardent leur classement,
  et le budget libéré va aux passages suivants. « Sources utilisées » cite chaque fiche une fois et signale
  celles écartées comme redondantes. L'atelier (« Savoir-faire de la case », sous le prompt
  final ; `GET /panels/{id}/knowledge`) montre ce que reçoit chacun, avec les jetons.
- **Bible de série** (page de la série) : univers, ton, règles, gags et motifs, notes par fiche
  personnage, et le résumé de chaque chapitre passé à « Prêt » ou « Publié ». Toujours injectée
  dans les agents de sa série (`$bible`), coupée à `bible_max_tokens` en retirant d'abord les plus
  anciens résumés.
- Chaque appel du LLM garde les passages et la bible reçus (table `llm_runs`) : l'écran Scénario
  les affiche sous « Sources utilisées ». Le panneau « Tester la recherche » montre le classement
  avec les scores (vecteurs, mots-clés, hybride).

### Packs de savoir-faire (`knowledge_packs/`)

Un pack est un gros fichier Markdown de fiches livré avec l'appli, et un manifeste YAML qui le range en
collections. Deux packs livrés : `manga_visual_knowledge` (cadrages, angles, corps et gestes, action,
composition, découpage, émotions, anti-répétition, exemples analysés), qui donne 13 collections
« Mise en scène · … » et environ 70 documents, et `manga_rendering_knowledge` (13/10/2026 : encrage, trames,
papier et impression, finitions, valeurs et masses), qui donne 5 collections « Rendu · … » et 17 fiches.
Un pack ne recopie jamais un preset (pas de collection « Pont presets ») : les mots-clés d'une finition
vivent dans `style_options.yaml`, une copie dériverait.

**Format du fichier** (`manga_visual_knowledge.md`) : une section par `## titre` ; dans une section, une
fiche par `### ID — titre`, qui commence par une ligne `` `path: …` `` et un bloc ```` ```meta ```` en JSON
(`id`, `type`, `intent`, `shot_scale`, `camera_angle`, `pairs_with`…).

**Manifeste** (`manga_visual_knowledge.yaml`) :

```yaml
id: manga_visual_knowledge          # identifiant du pack (minuscules, chiffres, _ et -)
file: manga_visual_knowledge.md     # à côté du manifeste
collections:                        # sections `##` → collection ; `sections` : début du titre de la section
  - name: Mise en scène · Cadrages
    sections: ["01_cadrages"]
  - name: Mise en scène · Vocabulaire
    sections: ["0.B", "0.C"]        # plusieurs sections dans une collection
skip: ["0.A", "0.D", "Annexe C"]    # sections volontairement ignorées
vocabulary:                         # pont de vocabulaire : code du meta → terme de l'appli
  shot_scale: { close_up: gros plan, extreme_close_up: gros plan, detail: insert }
  camera_angle: { low: en contre-plongée, dutch: cadre penché }
  primary: { gros plan: close_up }  # fiche de référence d'un terme donné par plusieurs codes
```

**Ce que fait l'import** (au démarrage du moteur, et bouton « Mettre à jour les packs » de l'écran
Savoir-faire, `POST /knowledge/packs/update`) :

- une fiche `###` = un document, titré par le titre de la fiche (`SHOT_CU_001 — Gros plan (visage)`) ; une
  section sans fiche (annexes, vocabulaire) = un document ;
- le bloc meta et la ligne `path:` sont **retirés du texte** découpé, vectorisé et injecté ; leurs champs sont
  gardés sur le document (page du document) et donnent ses étiquettes (id, type, plan, angle, intentions).
  Un autre bloc JSON (exemple de format, section 0.C) devient une liste « champ : valeur » : aucun JSON
  n'arrive dans un prompt ;
- **pont de vocabulaire** : les codes `shot_scale` / `camera_angle` d'une fiche sont traduits dans les
  termes de la direction artistique (`plan large`, `gros plan`, `en contre-plongée`, `vue subjective`…, liste
  validée contre `art_direction.PLANS` / `ANGLES`) et ajoutés, avec le titre, aux **mots-clés** du document :
  colonne `keywords` de l'index FTS (poids ×4), jamais dans le texte injecté. Chaque terme est aussi indexé en
  un seul jeton (`grosplan`, `contreplongee`) que retrouvent les bigrammes de la requête : une case « gros
  plan » « en contre-plongée » remonte SHOT_CU_001 et ANG_LOW_001 avant les fiches qui disent juste « plan » ;
- **idempotent** : un fichier inchangé ne change rien ; une fiche modifiée est seule réécrite et réindexée ;
  une fiche ou une collection retirée disparaît. Les collections et documents du pack sont marqués « pack »
  et sont **en lecture seule** dans l'UI et l'API (409) ; les collections et documents de l'utilisateur ne
  sont jamais touchés (une collection créée à la main avec le nom d'une collection du pack la bloque : le pack
  le signale et n'y verse rien) ;
- **non importés** : l'en-tête YAML et le chapeau `#` du fichier, le chapeau d'une section à fiches (texte
  avant la première `###`), les sections de `skip` (mode d'emploi de l'indexation, index des fiches, sources),
  et toute section que le manifeste ne cite pas (signalée dans le compte rendu de l'import) ;
- les fiches d'un pack vont au scénariste, au DA et au **rédacteur** de prompt, jamais dans la note courte du
  prompt par fragments (collée telle quelle dans le prompt du modèle d'image). Les fiches citent des champs que
  l'appli n'a pas (`narrative_role`, `variation_reason`, `panel_weight`…) : les prompts du DA et du rédacteur
  précisent qu'elles sont des conseils et qu'il faut répondre dans le format demandé.

**Mettre à jour le pack** : remplace `manga_visual_knowledge.md` (même structure), ajuste le manifeste si une
section change de nom, puis « Mettre à jour les packs » (ou redémarre le moteur). Embeddings indisponibles
pendant l'import : les fiches sont cherchables par mots-clés et signalées « à réindexer ». `KNOWLEDGE_PACKS=false`
dans `.env` désactive l'import au démarrage (les tests du moteur l'ont désactivé par défaut).

Collections lues par défaut (`knowledge.yaml`, « L'équipe » prime toujours) : scénariste + Fondamentaux,
Émotions, Exemples ; DA + Fondamentaux, Cadrages, Angles, Action, Composition, Découpage, Émotions,
Anti-répétition, Exemples (budget de 3 500 jetons, fiches cherchées **page par page** : la requête de chaque
page est son scénario — descriptions, gestes, personnages, répliques —, sans doublon, au plus `top_k` fiches
par page ; une petite collection d'un pack n'y est jamais injectée entière). Vocabulaire et Checklist décrivent
le format d'un storyboarder (champs que l'appli n'a pas) : lues par aucun agent, toujours cherchables dans
Savoir-faire. « Sources utilisées » de l'écran Direction artistique liste les fiches de chaque page.
Rédacteur de prompt + Cadrages, Angles,
Corps et gestes, Action, Composition, Émotions, Pont ComfyUI (≈ 420 jetons, entière).
Pack rendu, branchement étroit (le budget du rédacteur est déjà plein) : DA + Rendu · Valeurs et masses et
Rendu · Encrage ; rédacteur + Rendu · Valeurs et masses **seulement** ; scénariste : rien. Trames, Papier et
impression, Finitions : cherchables dans Savoir-faire, lues par aucun agent.

### Embeddings : mode réel

Par défaut (`EMBEDDING_PROVIDER` vide ou `mock`), les vecteurs sont factices et déterministes (sac
de mots haché) : aucun appel réseau, c'est le mode de la CI et de la QA. En réel :

```bash
ollama pull bge-m3            # suggestion : multilingue, bon en français (≈ 1,2 Go) — à valider avant
```

puis `EMBEDDING_PROVIDER=ollama` dans `.env` ; le modèle se règle dans `providers.yaml`
(`ollama.embedding_model`, contexte `ollama.embedding_num_ctx: 8192`, le maximum de bge-m3). Rien n'est téléchargé automatiquement. Après un changement de modèle,
les passages déjà indexés sont signalés « à réindexer » : bouton « Réindexer » de la bibliothèque
(ou `POST /knowledge/reindex`). Ollama éteint : les documents s'enregistrent quand même (recherche
par mots-clés seule), avec l'erreur affichée sur le document.
