# Presets

Tout ce qui évolue (modèles, LoRA, workflows ComfyUI, formats de page, polices,
seuils de QC…) est un **preset**, pas du code. Le moteur les charge au démarrage
et les valide ; un preset invalide est écarté et l'erreur s'affiche dans
`GET /presets` (et le compteur `presets.issues` de `GET /health`).

Après modification d'un preset, redémarre le moteur (`npm run dev`).

## Arborescence

| Fichier | Rôle |
| --- | --- |
| `defaults.yaml` | Format de page, workflow (palier **Qualité**) et style de mise en page (`layout_style`) appliqués aux nouvelles séries ; workflow « avec références » de repli pour un preset qui ne déclare pas `with_references` (`workflow_with_references`) |
| `providers.yaml` | Paramètres des fournisseurs (URL, modèle LLM, timeouts). **Aucune clé d'API ici** : elles vont dans `.env` |
| `page_formats/*.yaml` | Formats de page (dimensions en mm, DPI, marges, gouttières) : A4 (défaut) et B4 JIS à 300 DPI |
| `layout.yaml` | Découpage : taille mini d'une case, taille cible de génération, zones de bulles, seuil de régénération conseillée |
| `layouts/*.yaml` | Bibliothèque de gabarits de planche (arbres de découpes) |
| `layout_styles/*.yaml` | Grammaires de mise en page par série : `sage`, `dynamique` (défaut), `nerveuse` — biais, gouttières, gabarits favoris |
| `prompts/*.yaml` | Prompts des étapes LLM (`script` : découpage d'un chapitre) |
| `image_prompt.yaml` | Construction du prompt final des cases (étape 3) et termes « pas de texte » du prompt négatif |
| `qc.yaml` | Contrôle qualité des cases (étape 4) : poids, seuils de verdict, règles des détecteurs, seuil CCIP, zone de doute de la vision, nouveaux essais automatiques |
| `workflows/*.yaml` + `*.json` | Workflows ComfyUI : le JSON API exporté + le mapping des paramètres |
| `fonts.yaml` + `fonts/` | Polices de lettrage (OFL, licences dans `fonts/OFL*.txt`) et style de texte par type de bulle |
| `lettering.yaml` | Formes et placement des bulles, queues, bordures de case, repères de coupe |
| `agents/*.yaml` | Agents du pipeline (écran « L'équipe ») : nom, rôle, étape et réglages éditables depuis l'UI |

| `knowledge.yaml` | Savoir-faire (RAG local) : découpage des documents, recherche hybride, seuil « petite collection », budget de la bible, collections lues par chaque agent |

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
`dynamique`, `defaults.yaml`). Une page peut imposer le sien (atelier de mise en page). Aucune valeur de
style n'est écrite dans le code : tout est dans ces fichiers, et **tous les champs sont obligatoires**.

| Style | Intention |
| --- | --- |
| `sage` | Découpes droites, gouttières du format, toujours le gabarit le mieux adapté : identique à la mise en page d'avant les styles |
| `dynamique` | Quelques biais sur les cases fortes et les temps d'action, gouttières légèrement variables |
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

### Direction artistique : comment piloter la mise en page

La mise en page est de la **géométrie déterministe** : aucune IA ne dessine les cases. Le LLM du
scénario (`prompts/script.yaml`) et l'agent « Directeur artistique » (`prompts/direction-artistique.yaml`)
ne la pilotent **que** par ces champs structurés, validés par Pydantic :

| Champ | Où | Valeurs | Effet |
| --- | --- | --- | --- |
| `importance` | case | 1 transition, 2 normale, 3 forte | taille de la case (choix du gabarit), règle de biais `by_importance` |
| `intensity` (facultatif) | case | `calme`, `normal`, `choc` | poids de taille (`intensity_weight`), règle de biais `by_intensity` (prioritaire) |
| `rythme` (facultatif) | page | `lent`, `normal`, `rapide` | facteurs de biais et de contraste de la page (`rythme`) |
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
  contre-plongée), `angle`, `cadre` (normal, sans bord, fond perdu, incrustation), `ambiance`, `sfx`
  (onomatopées : texte + intensité).

Réponse invalide (schéma, pages ou cases manquantes, gabarit impossible) → relance avec l'erreur
(`max_retries`, 2 au maximum) → sinon erreur visible sur le job. `variety` (sobre, equilibree,
audacieuse) règle l'audace, modifiable dans « L'équipe » (globalement ou par série), comme le modèle, la
température et les consignes.

L'auteur corrige n'importe quel champ : il est alors **verrouillé** (🔒) et gardé quand l'agent repropose,
jusqu'à ce qu'il le déverrouille ; une page « acceptée » n'est pas remplacée par une relance de tout le
chapitre. **« Appliquer à la mise en page »** recopie les choix : rythme de la page (calme et respiration →
`lent`, montée → `normal`, climax → `rapide`), style suggéré, intensité des cases, gabarit suggéré et
page choc ; seules les pages dont la mise en page change sont recalculées. Les choix appliqués
alimentent aussi le prompt image (`$plan`, `$angle`, `$ambiance`). Le cadre et les onomatopées sont
conservés pour le lettrage. Si le découpage d'une page change, sa direction est marquée « à refaire ».

## Prompts (`prompts/*.yaml`)

Gabarits `$variable` (écrire `$$` pour un dollar). `script.yaml` liste ses variables en tête ;
`max_retries` (0 à 2) fixe le nombre de relances après une réponse invalide, `max_previous_chapters`
le nombre de résumés de chapitres précédents envoyés. Le bloc `<contexte>…</contexte>` transmet le
même contexte en JSON (le LLM factice du mode mock s'en sert pour produire un découpage).

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

Les quatre presets livrés partagent le même graphe et les mêmes numéros de nœuds :

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
`9` → `10 VAEDecode` → `11 SaveImage`. `cfg: 1` est le chemin officiel de Qwen-Image 2.1 : à cfg 1 le prompt
négatif est ignoré par le modèle (le monter n'a de sens qu'avec un prompt négatif utile, et double le coût).

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

### Fichiers de la GX10 et paliers Qualité / Rapide

Fichiers installés dans `~/ComfyUI/models/` (liens vers le disque T9) et utilisés par les presets :

| Dossier | Qualité | Rapide |
| --- | --- | --- |
| `diffusion_models/` | `qwen_image_2.1_bf16.safetensors` (14,2 Go) | `qwen_image_2.1_int8_convrot.safetensors` (7,3 Go) |
| `text_encoders/` | `qwen3vl_8b_bf16.safetensors` (17,5 Go) | `qwen3vl_8b_int8_convrot.safetensors` (9,4 Go) |
| `vae/` | `qwen_image_2.1_vae_bf16.safetensors` | idem |

Les fichiers int8 « convrot » se chargent avec les nœuds standard (`UNETLoader` `weight_dtype: default`,
`CLIPLoader` `type: qwen_image`), comme dans le workflow de référence du manager
(`~/ComfyUI/user/default/workflows/image_qwen_image_2_1_image_edit.json`).

| Preset | Palier | Usage | Étapes | Délai max |
| --- | --- | --- | --- | --- |
| `qwen-image-base` | Qualité (défaut des séries) | texte → image | 50 | 20 min |
| `qwen-image-edit-ref` | Qualité | avec images de référence | 50 | 25 min |
| `qwen-image-base-rapide` | Rapide | texte → image | 25 | 10 min |
| `qwen-image-edit-ref-rapide` | Rapide | avec images de référence | 25 | 15 min |

Le palier se choisit avec le **workflow de la série** (liste « Workflow ComfyUI » de la fiche série).
Chaque preset texte → image déclare son pendant « avec références » du même palier :

```yaml
with_references: qwen-image-edit-ref-rapide   # dans qwen-image-base-rapide.yaml
```

Une case dont un personnage a une planche de référence prend donc `qwen-image-edit-ref-rapide` dans une
série Rapide, `qwen-image-edit-ref` dans une série Qualité. `defaults.yaml → workflow_with_references`
ne sert plus qu'aux presets sans `with_references`. La taille de génération reste celle de la mise en page
(≈ 1 Mpx, `layout.yaml`) pour les deux paliers.

### Case d'essai (`trial`)

Le bloc `trial` d'un preset donne les paramètres de « Générer une case d'essai » (tableau de bord) :
prompt d'essai, petite taille, peu d'étapes. Une seule vraie génération, qui passe par la file ComfyUI ;
l'image et sa durée en secondes s'affichent sous le bouton.

### Tester la connexion

`GET /comfyui/check` (bouton « Tester la connexion » du tableau de bord) interroge `/system_stats` et
`/object_info` du vrai ComfyUI et liste, par preset : les nœuds inconnus (« nœud inconnu : … ») et les
valeurs fixes absentes des listes de ComfyUI (« modèle introuvable dans ComfyUI : … », encodeur, VAE,
échantillonneur…), puis les LoRA saisis dans les séries et les fiches absents de `models/loras/`.
Avec `COMFYUI_PROVIDER=mock`, il répond « ComfyUI simulé ».

## Images de référence et LoRA (étape 3)

Les quatre presets acceptent des LoRA ; les deux presets « avec images de référence » ont 3 emplacements
(Qwen-Image 2.1 : l'édition / la référence est intégrée au modèle, pas de modèle « edit » séparé). Ils sont
choisis automatiquement (selon le palier de la série) quand un personnage de la case a une planche de
référence.

### Emplacements de référence (`reference_images`)

Liste **ordonnée** d'emplacements, chacun étant un nœud qui charge une image (`LoadImage`) :

```yaml
reference_images:
  - { node: "20", input: image }   # 1er emplacement → images.image_1 de l'encodeur (nœud 6)
  - { node: "21", input: image }
  - { node: "22", input: image }
  # avec un redimensionnement propre à l'emplacement : { node: "20", input: image, remove: ["30"] }
```

- Le moteur envoie les images de référence des personnages de la case à ComfyUI
  (`POST /upload/image`, sous-dossier `input/mangaka/`) et écrit le nom obtenu dans
  `workflow[node].inputs[input]`. Ordre : 1re image de chaque personnage (dans l'ordre de la
  case), puis 2e image de chacun, etc., jusqu'à remplir les emplacements.
- Un emplacement **inutilisé est retiré** : son nœud et ceux listés dans `remove` (ex. son
  redimensionnement) sont supprimés, puis toute entrée d'un autre nœud qui pointait vers un nœud
  retiré est effacée. Exemple : avec une seule référence, `images.image_2`/`images.image_3` disparaissent
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

LoRA appliqués, dans l'ordre : **LoRA de style de la série** puis **LoRA d'identité de chaque
personnage** de la case (nom de fichier + poids saisis dans la série / la fiche). Chaque LoRA
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
   subgraph ») : le format API exporte les nœuds réels. Vérifie qu'il tourne (avec 3 `LoadImage` branchés
   sur `images.image_1…3` de `TextEncodeQwenImage21` pour les presets « avec références ») et retire les
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

## Prompt final des cases (`image_prompt.yaml`)

`parts` est une liste de morceaux `string.Template` assemblés dans l'ordre (`$plan` = plan de la
direction artistique appliquée, sinon celui du scénario, `$angle` et `$ambiance` de la direction
artistique, `$shot` = plan du scénario,
`$description`, `$characters`, `$style`, `$bible` = notes de la bible sur les personnages de la
case, `$savoir_faire` = passages du savoir-faire de l'agent `image_prompt`) ; un morceau dont une
variable est vide est omis.
`character` met en forme un personnage (`$name`, `$details` = description visuelle + mots-clés).
`forbidden_text_terms` est toujours ajouté au prompt négatif du workflow (le texte est posé au
lettrage, jamais dessiné par le modèle) et `strip_quotes` retire les répliques entre guillemets
de la description. Le prompt est stocké sur la case ; une édition manuelle est conservée jusqu'à
« reconstruire le prompt ».

## Lettrage (étape 5)

Le texte n'est **jamais** dessiné par le modèle d'image : il est posé au lettrage, en vectoriel.

- `fonts.yaml` : `fonts` (id → fichier + nom) et `styles` par type de bulle (`speech`, `thought`,
  `shout`, `narration`, `"off"` — entre guillemets, sinon YAML lit un booléen) : police, graisse
  (polices variables), taille en **points** (`size_pt`), taille minimale lisible (`min_size_pt`),
  pas de réduction, interligne, capitales. `hyphenation` règle la césure française (pyphen).
  Faute de place à la taille minimale, la bulle garde tout son texte et la case affiche un
  avertissement.
- `lettering.yaml` : marges intérieures par type, forme de la parole (ellipse / rectangle arrondi),
  nuage, pointes du cri, queue (longueur, base, direction par défaut sans visage détecté), écarts
  bulle ↔ bulle / bord de case / visage, couleurs, bordure des cases, repères de coupe.
- Fond perdu : `bleed_mm` du format de page. Feuille = `round((mm + 2 × fond perdu) / 25,4 × dpi)`
  → A4 300 DPI + 3 mm = 2551 × 3579 px.
- Visages : le lettrage évite les boîtes de visages enregistrées par le QC sur la version retenue
  (`PanelImage.detections.faces`, à défaut `PanelImage.params` : `faces`, `qc.faces`…, en px de l'image).
- Les SVG exportés embarquent un sous-ensemble renommé (`mk-…`) de chaque police (clause 3 de l'OFL).

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
| `detectors.rules` | `missing_face`, `extra_face` (+ `tolerance`), `text`, `suspect_hand` (+ `max_penalty`) : `penalty` (points retirés) et `at_least` (`review` / `reject` : verdict minimal imposé) |
| `detectors.face_count_ignored_for_shots` | Types de plan où le nombre de visages n'est pas vérifié (insert…) |
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
  ≈ 4 caractères.
- **Index** : chaque passage a un vecteur (float32 en BLOB dans SQLite) et une entrée dans l'index
  plein texte FTS5. La comparaison des vecteurs se fait en **numpy** (force brute) : sqlite-vec
  n'est pas utilisé — aux volumes visés (quelques milliers de passages) c'est instantané, et cela
  évite de charger une extension SQLite dans chaque connexion. Modifier un document le réindexe.
- **Recherche hybride** (`retrieval`) : score = `vector_weight` × cosinus + `keyword_weight` ×
  BM25 normalisé (le meilleur passage par mots-clés vaut 1), `top_k` passages au plus, dans le
  `budget_tokens` de l'agent. Une collection de moins de `small_collection_tokens` jetons est
  injectée **entière**, sans recherche.
- **Agents** (`agents`) : `script` (étape 1, variable `$savoir_faire` de `prompts/script.yaml`) et
  `image_prompt` (étape 3, `$savoir_faire` / `$bible` de `image_prompt.yaml`). Collections par nom
  (casse ignorée) ; `series_collections: true` ajoute celles de la série du chapitre — jamais
  celles d'une autre série. Le champ « Savoir-faire » d'un profil d'agent (écran « L'équipe »,
  `knowledge_role` de `agents/*.yaml`) prime sur cette liste et sur `top_k`, surcharge de série comprise
  (`KnowledgeBase.profile_lookup`).
- **Bible de série** (page de la série) : univers, ton, règles, gags et motifs, notes par fiche
  personnage, et le résumé de chaque chapitre passé à « Prêt » ou « Publié ». Toujours injectée
  dans les agents de sa série (`$bible`), coupée à `bible_max_tokens` en retirant d'abord les plus
  anciens résumés.
- Chaque appel du LLM garde les passages et la bible reçus (table `llm_runs`) : l'écran Scénario
  les affiche sous « Sources utilisées ». Le panneau « Tester la recherche » montre le classement
  avec les scores (vecteurs, mots-clés, hybride).

### Embeddings : mode réel

Par défaut (`EMBEDDING_PROVIDER` vide ou `mock`), les vecteurs sont factices et déterministes (sac
de mots haché) : aucun appel réseau, c'est le mode de la CI et de la QA. En réel :

```bash
ollama pull bge-m3            # suggestion : multilingue, bon en français (≈ 1,2 Go) — à valider avant
```

puis `EMBEDDING_PROVIDER=ollama` dans `.env` ; le modèle se règle dans `providers.yaml`
(`ollama.embedding_model`). Rien n'est téléchargé automatiquement. Après un changement de modèle,
les passages déjà indexés sont signalés « à réindexer » : bouton « Réindexer » de la bibliothèque
(ou `POST /knowledge/reindex`). Ollama éteint : les documents s'enregistrent quand même (recherche
par mots-clés seule), avec l'erreur affichée sur le document.
