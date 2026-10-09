# Presets

Tout ce qui évolue (modèles, LoRA, workflows ComfyUI, formats de page, polices,
seuils de QC…) est un **preset**, pas du code. Le moteur les charge au démarrage
et les valide ; un preset invalide est écarté et l'erreur s'affiche dans
`GET /presets` (et le compteur `presets.issues` de `GET /health`).

Après modification d'un preset, redémarre le moteur (`npm run dev`).

## Arborescence

| Fichier | Rôle |
| --- | --- |
| `defaults.yaml` | Format de page et workflow appliqués aux nouvelles séries |
| `providers.yaml` | Paramètres des fournisseurs (URL, modèle LLM, timeouts). **Aucune clé d'API ici** : elles vont dans `.env` |
| `page_formats/*.yaml` | Formats de page (dimensions en mm, DPI, marges, gouttières) : A4 (défaut) et B4 JIS à 300 DPI |
| `layout.yaml` | Découpage : taille mini d'une case, taille cible de génération, zones de bulles |
| `layouts/*.yaml` | Bibliothèque de gabarits de planche (arbres de découpes) |
| `prompts/*.yaml` | Prompts des étapes LLM (`script` : découpage d'un chapitre) |
| `workflows/*.yaml` + `*.json` | Workflows ComfyUI : le JSON API exporté + le mapping des paramètres |

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
une grille de bandes de 3 cases est générée.

## Prompts (`prompts/*.yaml`)

Gabarits `$variable` (écrire `$$` pour un dollar). `script.yaml` liste ses variables en tête ;
`max_retries` (0 à 2) fixe le nombre de relances après une réponse invalide, `max_previous_chapters`
le nombre de résumés de chapitres précédents envoyés. Le bloc `<contexte>…</contexte>` transmet le
même contexte en JSON (le LLM factice du mode mock s'en sert pour produire un découpage).

## Workflow ComfyUI

1. Dans ComfyUI, construis le workflow puis exporte-le via **Workflow → Export (API)**.
   Copie le JSON dans `presets/workflows/<id>.json`.
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
```

### Mapping des nœuds (`qwen-image-base`)

| Paramètre | Nœud | Type ComfyUI | Entrée | Obligatoire |
| --- | --- | --- | --- | --- |
| `positive_prompt` | `6` | `CLIPTextEncode` | `text` | oui |
| `negative_prompt` | `7` | `CLIPTextEncode` | `text` | oui (défaut fourni) |
| `seed` | `9` | `KSampler` | `seed` | oui (tirée au hasard puis enregistrée si absente) |
| `steps` | `9` | `KSampler` | `steps` | non |
| `cfg` | `9` | `KSampler` | `cfg` | non |
| `width` | `8` | `EmptySD3LatentImage` | `width` | oui |
| `height` | `8` | `EmptySD3LatentImage` | `height` | oui |
| `filename_prefix` | `11` | `SaveImage` | `filename_prefix` | non |

Règles vérifiées au chargement :

- `positive_prompt`, `negative_prompt`, `seed`, `width`, `height` doivent être mappés ;
- chaque `node` doit exister dans le JSON et posséder l'entrée `input` ;
- `output_node` doit exister ;
- chaque clé de `defaults` doit être mappée.

Les noms de fichiers de modèles (`unet_name`, `clip_name`, `vae_name`) vivent
**uniquement** dans le JSON : adapte-les aux fichiers présents dans
`ComfyUI/models/` sur le GX10. Le code Python ne connaît aucun nom de modèle.
