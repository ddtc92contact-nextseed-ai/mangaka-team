// Généré par mangaka-tuto/extraire_prompts.py depuis presets/ et le moteur — ne pas modifier à la main.
window.TUTO_GABARITS = {
 "providers": {
  "file": "presets/providers.yaml",
  "defaultModel": "deepseek-flash",
  "defaultModelLine": 5,
  "models": {
   "deepseek-flash": false,
   "deepseek-v4-pro": true,
   "deepseek-chat": false,
   "deepseek-reasoner": true
  },
  "visionModel": "qwen3-vl:4b",
  "visionModelLine": 47
 },
 "agents": [
  {
   "id": "controleur-qualite",
   "name": "Contrôleur qualité",
   "icon": "🔍",
   "file": "presets/agents/controleur-qualite.yaml",
   "providers": [
    "detectors",
    "identity",
    "vision"
   ],
   "llm": false,
   "knowledgeRole": null,
   "settings": [
    {
     "key": "vision_prompt",
     "label": "Consigne du modèle de vision",
     "source": "qc.yaml#vision.prompt",
     "line": 109,
     "variables": [
      "description",
      "characters",
      "shot"
     ]
    }
   ]
  },
  {
   "id": "createur-serie",
   "name": "Créateur de série",
   "icon": "🧭",
   "file": "presets/agents/createur-serie.yaml",
   "providers": [
    "llm"
   ],
   "llm": true,
   "knowledgeRole": "series_creation",
   "settings": [
    {
     "key": "system",
     "label": "Consignes système",
     "source": "prompts/createur-serie.yaml#system",
     "line": 55,
     "variables": [
      "series_title",
      "genre",
      "style_packs",
      "style_guidelines",
      "reading_direction",
      "pitch",
      "answers",
      "characters",
      "chapters",
      "current_bible",
      "genre_dna",
      "max_section_chars",
      "max_note_chars",
      "savoir_faire",
      "context_json"
     ]
    },
    {
     "key": "user",
     "label": "Gabarit de l'échange",
     "source": "prompts/createur-serie.yaml#user",
     "line": 76,
     "variables": [
      "series_title",
      "genre",
      "style_packs",
      "style_guidelines",
      "reading_direction",
      "pitch",
      "answers",
      "characters",
      "chapters",
      "current_bible",
      "genre_dna",
      "max_section_chars",
      "max_note_chars",
      "savoir_faire",
      "context_json"
     ]
    },
    {
     "key": "retry",
     "label": "Consigne de relance",
     "source": "prompts/createur-serie.yaml#retry",
     "line": 83,
     "variables": [
      "error"
     ]
    }
   ]
  },
  {
   "id": "dessinateur",
   "name": "Dessinateur",
   "icon": "🖌️",
   "file": "presets/agents/dessinateur.yaml",
   "providers": [
    "comfyui",
    "llm"
   ],
   "llm": true,
   "knowledgeRole": "image_prompt",
   "settings": [
    {
     "key": "parts",
     "label": "Morceaux du prompt (un par ligne)",
     "source": "image_prompt.yaml#parts",
     "line": 76,
     "variables": [
      "style_lead",
      "finition",
      "plan",
      "framing",
      "angle",
      "ambiance",
      "action",
      "shot",
      "description",
      "setting",
      "staging",
      "character_count",
      "characters",
      "decor",
      "objects",
      "style",
      "savoir_faire",
      "bible"
     ]
    },
    {
     "key": "character",
     "label": "Présentation d'un personnage",
     "source": "image_prompt.yaml#character",
     "line": 87,
     "variables": [
      "name",
      "details"
     ]
    },
    {
     "key": "reference_line",
     "label": "Image de référence d'un personnage",
     "source": "image_prompt.yaml#references.character",
     "line": 93,
     "variables": [
      "slot",
      "name"
     ]
    },
    {
     "key": "reference_line_monochrome",
     "label": "Image de référence d'un personnage (série en noir et blanc)",
     "source": "image_prompt.yaml#references.monochrome.character",
     "line": 100,
     "variables": [
      "slot",
      "name"
     ]
    },
    {
     "key": "reference_sorting",
     "label": "Tri d'une fiche de personnage (ce qu'il faut en prendre)",
     "source": "image_prompt.yaml#references.sorting.character",
     "line": 107,
     "variables": [
      "slot",
      "name"
     ]
    },
    {
     "key": "reference_rule",
     "label": "Consigne sur les images de référence (après le prompt)",
     "source": "image_prompt.yaml#references.after",
     "line": 116,
     "variables": [
      "images",
      "count",
      "sorting"
     ]
    },
    {
     "key": "writer_system",
     "label": "Consignes de rédaction",
     "source": "prompts/redacteur-image.yaml#system",
     "line": 232,
     "variables": [
      "language",
      "language_name",
      "min_words",
      "max_words",
      "max_mentions",
      "plan",
      "angle",
      "camera",
      "action",
      "ambiance",
      "description",
      "setting",
      "staging",
      "characters",
      "character_names",
      "absent_characters",
      "framing",
      "decor",
      "objects",
      "references",
      "image_tags",
      "style",
      "style_lead",
      "finition",
      "bible",
      "savoir_faire",
      "palette_rule",
      "context_json"
     ]
    },
    {
     "key": "writer_user",
     "label": "Gabarit de la case",
     "source": "prompts/redacteur-image.yaml#user",
     "line": 266,
     "variables": [
      "language",
      "language_name",
      "min_words",
      "max_words",
      "max_mentions",
      "plan",
      "angle",
      "camera",
      "action",
      "ambiance",
      "description",
      "setting",
      "staging",
      "characters",
      "character_names",
      "absent_characters",
      "framing",
      "decor",
      "objects",
      "references",
      "image_tags",
      "style",
      "style_lead",
      "finition",
      "bible",
      "savoir_faire",
      "palette_rule",
      "context_json"
     ]
    },
    {
     "key": "writer_retry",
     "label": "Consigne de relance",
     "source": "prompts/redacteur-image.yaml#retry",
     "line": 273,
     "variables": [
      "error"
     ]
    }
   ]
  },
  {
   "id": "directeur-artistique",
   "name": "Directeur artistique",
   "icon": "🎬",
   "file": "presets/agents/directeur-artistique.yaml",
   "providers": [
    "llm"
   ],
   "llm": true,
   "knowledgeRole": "art_direction",
   "settings": [
    {
     "key": "system",
     "label": "Consignes système",
     "source": "prompts/direction-artistique.yaml#system",
     "line": 170,
     "variables": [
      "series_title",
      "style_packs",
      "style_guidelines",
      "series_style",
      "reading_direction",
      "layout_style",
      "layout_styles",
      "characters",
      "decors",
      "objets",
      "lieux",
      "chapter_number",
      "chapter_title",
      "synopsis",
      "summary",
      "pages",
      "previous_direction",
      "variety",
      "request",
      "rythmes",
      "intensities",
      "plans",
      "angles",
      "cadres",
      "points_de_vue",
      "page_chocs",
      "sfx_intensities",
      "variety_rules",
      "page_rules",
      "pre_direction",
      "scene",
      "context_json",
      "bible",
      "savoir_faire"
     ]
    },
    {
     "key": "user",
     "label": "Gabarit du chapitre",
     "source": "prompts/direction-artistique.yaml#user",
     "line": 210,
     "variables": [
      "series_title",
      "style_packs",
      "style_guidelines",
      "series_style",
      "reading_direction",
      "layout_style",
      "layout_styles",
      "characters",
      "decors",
      "objets",
      "lieux",
      "chapter_number",
      "chapter_title",
      "synopsis",
      "summary",
      "pages",
      "previous_direction",
      "variety",
      "request",
      "rythmes",
      "intensities",
      "plans",
      "angles",
      "cadres",
      "points_de_vue",
      "page_chocs",
      "sfx_intensities",
      "variety_rules",
      "page_rules",
      "pre_direction",
      "scene",
      "context_json",
      "bible",
      "savoir_faire"
     ]
    },
    {
     "key": "retry",
     "label": "Consigne de relance",
     "source": "prompts/direction-artistique.yaml#retry",
     "line": 217,
     "variables": [
      "error"
     ]
    }
   ]
  },
  {
   "id": "lettreur",
   "name": "Lettreur",
   "icon": "💬",
   "file": "presets/agents/lettreur.yaml",
   "providers": [],
   "llm": false,
   "knowledgeRole": null,
   "settings": []
  },
  {
   "id": "metteur-en-page",
   "name": "Metteur en page",
   "icon": "📐",
   "file": "presets/agents/metteur-en-page.yaml",
   "providers": [],
   "llm": false,
   "knowledgeRole": null,
   "settings": []
  },
  {
   "id": "scenariste",
   "name": "Scénariste",
   "icon": "✒️",
   "file": "presets/agents/scenariste.yaml",
   "providers": [
    "llm"
   ],
   "llm": true,
   "knowledgeRole": "script",
   "settings": [
    {
     "key": "system",
     "label": "Consignes système",
     "source": "prompts/script.yaml#system",
     "line": 82,
     "variables": [
      "series_title",
      "style_packs",
      "style_guidelines",
      "series_style",
      "reading_direction",
      "characters",
      "character_names",
      "decors",
      "objets",
      "lieux",
      "previous_chapters",
      "chapter_number",
      "chapter_title",
      "synopsis",
      "target_pages",
      "shot_types",
      "bubble_kinds",
      "intensities",
      "rythmes",
      "dialogue_rules",
      "pre_direction",
      "scenes",
      "context_json",
      "bible",
      "savoir_faire"
     ]
    },
    {
     "key": "user",
     "label": "Gabarit du chapitre",
     "source": "prompts/script.yaml#user",
     "line": 113,
     "variables": [
      "series_title",
      "style_packs",
      "style_guidelines",
      "series_style",
      "reading_direction",
      "characters",
      "character_names",
      "decors",
      "objets",
      "lieux",
      "previous_chapters",
      "chapter_number",
      "chapter_title",
      "synopsis",
      "target_pages",
      "shot_types",
      "bubble_kinds",
      "intensities",
      "rythmes",
      "dialogue_rules",
      "pre_direction",
      "scenes",
      "context_json",
      "bible",
      "savoir_faire"
     ]
    },
    {
     "key": "retry",
     "label": "Consigne de relance",
     "source": "prompts/script.yaml#retry",
     "line": 120,
     "variables": [
      "error"
     ]
    },
    {
     "key": "scene_system",
     "label": "Consignes système — name d'une scène",
     "source": "prompts/script-scene.yaml#system",
     "line": 127,
     "variables": [
      "series_title",
      "style_packs",
      "style_guidelines",
      "series_style",
      "reading_direction",
      "characters",
      "character_names",
      "decors",
      "objets",
      "lieux",
      "previous_chapters",
      "chapter_number",
      "chapter_title",
      "synopsis",
      "target_pages",
      "shot_types",
      "bubble_kinds",
      "intensities",
      "rythmes",
      "dialogue_rules",
      "pre_direction",
      "scenes",
      "context_json",
      "bible",
      "savoir_faire",
      "scene_number",
      "scene_title",
      "scene_type",
      "scene_type_name",
      "scene_summary",
      "scene_pages",
      "scene_first_page",
      "scene_last_page",
      "scene_tempo",
      "scene_fiches",
      "scene_cast",
      "written_scenes"
     ]
    },
    {
     "key": "scene_user",
     "label": "Gabarit d'une scène",
     "source": "prompts/script-scene.yaml#user",
     "line": 171,
     "variables": [
      "series_title",
      "style_packs",
      "style_guidelines",
      "series_style",
      "reading_direction",
      "characters",
      "character_names",
      "decors",
      "objets",
      "lieux",
      "previous_chapters",
      "chapter_number",
      "chapter_title",
      "synopsis",
      "target_pages",
      "shot_types",
      "bubble_kinds",
      "intensities",
      "rythmes",
      "dialogue_rules",
      "pre_direction",
      "scenes",
      "context_json",
      "bible",
      "savoir_faire",
      "scene_number",
      "scene_title",
      "scene_type",
      "scene_type_name",
      "scene_summary",
      "scene_pages",
      "scene_first_page",
      "scene_last_page",
      "scene_tempo",
      "scene_fiches",
      "scene_cast",
      "written_scenes"
     ]
    },
    {
     "key": "scene_retry",
     "label": "Consigne de relance — scène",
     "source": "prompts/script-scene.yaml#retry",
     "line": 178,
     "variables": [
      "error"
     ]
    }
   ]
  }
 ],
 "prompts": {
  "createur-serie": {
   "id": "createur-serie",
   "file": "presets/prompts/createur-serie.yaml",
   "description": "Échange de création d'une série — propose l'ADN (écarts au genre, expliqués) et rédige la bible.",
   "temperature": 0.6,
   "temperatureLine": 26,
   "maxRetries": 2,
   "maxRetriesLine": 25,
   "extra": {},
   "parts": [
    {
     "key": "system",
     "line": 29,
     "text": "Tu es directeur de collection et co-créateur de séries de manga et de bande dessinée. Avec l'auteur, tu poses\nl'identité d'une série AVANT qu'on en écrive les chapitres : son rythme, sa façon de montrer, sa voix, son\nunivers et ses personnages. Le genre de la série est verrouillé : tu écris les nuances de cette série-là\npar-dessus, sans le trahir.\nTu t'appuies sur le savoir-faire fourni (structure d'un chapitre, courbes de tension par genre, fins de\nchapitre, silence et dialogue) et sur les réponses de l'auteur, qui priment toujours.\nTu écris en français, avec une typographie française soignée (guillemets « », accents, apostrophes).\nTu réponds UNIQUEMENT par un objet JSON valide, sans texte autour ni bloc de code.\n",
     "used": []
    },
    {
     "key": "user",
     "line": 39,
     "text": "Série : « $series_title »\nGenre (verrouillé) : $genre\nPacks de style : $style_packs\nConsignes du genre et du ton :\n$style_guidelines\nSens de lecture : $reading_direction\n\nDe quoi parle la série (mots de l'auteur) :\n$pitch\n\nRéponses de l'auteur :\n$answers\n\nPersonnages (noms exacts) :\n$characters\n\nChapitres :\n$chapters\n\nBible actuelle (ce que l'auteur a déjà écrit — reprends-le et enrichis-le, ne le contredis pas) :\n$current_bible\n\nADN du genre (chemin — libellé : valeur [bornes]) :\n$genre_dna\n\nSavoir-faire :\n$savoir_faire\n\nPropose :\n1. « dna » : SEULEMENT les réglages de l'ADN que les réponses de l'auteur font s'écarter du genre — pour chacun\n   le chemin exact (« path »), la nouvelle valeur (« value » : une part entre 0 et 1, un entier ou un booléen,\n   dans les bornes ; un minimum reste sous son maximum) et une phrase d'explication (« why ») qui cite la\n   réponse de l'auteur. Les pistes données avec chaque réponse sont un point de départ, pas une obligation.\n   Aucun écart si les réponses suivent le genre.\n2. « bible » : « world » (univers), « tone » (ton), « rules » (règles de l'univers), « motifs » (gags et motifs\n   récurrents) — chacun $max_section_chars signes au plus, concret et utilisable par un scénariste.\n3. « characters » : une note par personnage de la liste (nom exact), $max_note_chars signes au plus : caractère,\n   rôle dans la série, arc, tics de langage (avec un exemple de réplique entre « »).\n4. « notes » : une phrase pour l'auteur (ce que tu as retenu de ses réponses), facultative.\n\nFormat de réponse :\n{\"dna\": [{\"path\": \"dialogue.max_per_page\", \"value\": 6, \"why\": \"…\"}],\n \"bible\": {\"world\": \"…\", \"tone\": \"…\", \"rules\": \"…\", \"motifs\": \"…\"},\n \"characters\": [{\"name\": \"…\", \"note\": \"…\"}],\n \"notes\": \"…\"}\n\n<contexte>\n$context_json\n</contexte>\n",
     "used": [
      "series_title",
      "genre",
      "style_packs",
      "style_guidelines",
      "reading_direction",
      "pitch",
      "answers",
      "characters",
      "chapters",
      "current_bible",
      "genre_dna",
      "savoir_faire",
      "max_section_chars",
      "max_note_chars",
      "context_json"
     ]
    },
    {
     "key": "retry",
     "line": 90,
     "text": "Ta réponse précédente est invalide :\n$error\nCorrige ces erreurs et renvoie l'objet JSON complet, et uniquement lui.\n",
     "used": [
      "error"
     ]
    }
   ]
  },
  "direction-artistique": {
   "id": "direction-artistique",
   "file": "presets/prompts/direction-artistique.yaml",
   "description": "Rythme, intensité, cadrage et style de chaque page, avant la mise en page.",
   "temperature": 0.6,
   "temperatureLine": 33,
   "maxRetries": 2,
   "maxRetriesLine": 32,
   "extra": {
    "variety": "equilibree"
   },
   "parts": [
    {
     "key": "system",
     "line": 92,
     "text": "Tu es directeur artistique de manga et de bande dessinée. À partir d'un scénario déjà découpé en\npages et en cases, tu décides du rythme de chaque page, de l'intensité et du cadrage de chaque case,\ncomme un mangaka expérimenté prépare son storyboard. Tu ne dessines jamais la mise en page : tu\nchoisis uniquement parmi les options proposées, et la mise en page en tire les découpes.\nTu varies les plans et les angles, tu gardes les temps forts pour les moments qui le méritent, et tu\névites de répéter les choix du chapitre précédent. Une case n'est jamais un personnage debout, de\nface, qui regarde le lecteur : tu choisis pour chacune un mouvement ou une pose du corps lisible\n(élan, torsion, appui, geste) et un angle qui le sert.\nTu serres le cadre (gros plan, plan rapproché, insert) pour l'émotion, la révélation et la réplique\nclé ; tu gardes le plan large pour installer un lieu ou suivre une chorégraphie, et le plan moyen pour\nrelier deux personnages : un personnage en pied n'est jamais le cadrage par défaut.\nTu réponds UNIQUEMENT par un objet JSON valide, sans texte autour ni bloc de code.\n",
     "used": []
    },
    {
     "key": "user",
     "line": 106,
     "text": "Série : « $series_title »\nStyle de la série :\n$style_packs\nSens de lecture : $reading_direction\nStyle de mise en page de la série : $layout_style\nStyles de mise en page disponibles :\n$layout_styles\n\nPersonnages :\n$characters\n\nDécors récurrents (bibliothèque) :\n$decors\n\nObjets, véhicules et créatures récurrents (bibliothèque ; la sorte suit le nom) :\n$objets\n\nLieux de la série (chaque case se rattache à l'un d'eux) :\n$lieux\n\nBible de la série (à respecter strictement) :\n$bible\n\nSavoir-faire de l'équipe (fiches de méthode : applique-les sans les citer) :\n$savoir_faire\nCes fiches sont des conseils, pas un format : elles citent des champs que tu n'as pas (narrative_role, variation_reason, panel_weight…) ; réponds uniquement dans le format demandé ci-dessous.\n\nDirection artistique du chapitre précédent (à ne pas répéter) :\n$previous_direction\n\nChapitre $chapter_number — « $chapter_title »\nSynopsis : $synopsis\nRésumé : $summary\n\nAudace demandée : $variety\n\nConsignes du genre et du ton de la série (rythme, cadrage, public) :\n$style_guidelines\n\nRègles de mise en scène (vérifiées : une réponse qui les enfreint est refusée) :\n$variety_rules\n\nRègles par planche (vérifiées : les cases fautives te seront renvoyées pour correction) :\n$page_rules\n\nCharte de la série (son ADN, chiffré et vérifié : ce qui s'en écarte te sera renvoyé pour correction) :\n$pre_direction\n\nScène dirigée (son type et son profil priment sur la charte de la série pour ses pages) :\n$scene\n\nScénario des pages :\n$pages\n\n$request\n\nPour chaque page :\n- « rythme » vaut exactement l'une de ces valeurs : $rythmes ;\n- « layout_style » : null pour garder le style de la série, sinon l'identifiant d'un style disponible ;\n- « template » : null, ou l'un des gabarits possibles indiqués pour cette page ;\n- « page_choc » : null, ou l'une de ces valeurs : $page_chocs (à réserver aux vrais sommets) ;\n- « rationale » : deux ou trois phrases en français, adressées à l'auteur, qui justifient tes choix ;\n- « panels » : exactement une entrée par case, numérotées à partir de 1 dans l'ordre du scénario.\nPour chaque case :\n- « intensity » : $intensities ;\n- « plan » : $plans ;\n- « angle » : $angles ;\n- « cadre » : $cadres (« débordement » : la case empiète sur ses voisines, jamais sur la marge de la\n  page ; à réserver à une case « choc » ou à une page choc) ;\n- « ambiance » : une courte note de lumière et d'atmosphère, en français ;\n- « action » : une courte phrase en français qui décrit le mouvement ou la pose du corps du\n  personnage principal (« bondit par-dessus la rambarde, manteau au vent », « se penche vers Kenji,\n  poing serré sur la table ») — jamais « regarde » ou « est debout » seuls ;\n- « sfx » : onomatopées suggérées (0 à 4), chacune {\"text\": \"…\", \"intensity\": l'une de $sfx_intensities} ;\n- « decor » (facultatif) : null pour garder le décor du scénario, sinon l'id d'un décor de la\n  bibliothèque ci-dessus — jamais un id absent de la liste ;\n- « objets » (facultatif) : null pour garder les objets du scénario, sinon la liste des ids d'objets,\n  de véhicules et de créatures de la bibliothèque visibles dans la case — jamais un id absent de la liste ;\n- « lieu » (facultatif) : null pour garder le lieu du scénario, sinon l'id d'un lieu de la série\n  ci-dessus si la case se passe ailleurs — jamais un id absent de la liste. La première case d'un\n  NOUVEAU LIEU est une case d'établissement (voir la charte) : elle installe le lieu ;\n- « point_de_vue » : OBLIGATOIRE pour une case marquée SPECTATEUR (le texte dit qu'un personnage voit,\n  regarde, aperçoit, découvre, assiste…), null sinon. Choisis explicitement l'une de ces valeurs :\n  $points_de_vue — « plan de réaction » : le spectateur est dessiné, on montre son visage et ce qu'il\n  ressent ; « vue subjective » : on montre ce qu'il voit, à travers ses yeux, et le spectateur reste\n  HORS CADRE (ni dessiné, ni image de référence). Pour « Seku et Angus voient au loin les trafiquants\n  jeter des barils dans le volcan », la vue subjective montre les trafiquants au loin, pas les héros ;\n- « spectateurs » : les noms des spectateurs (ceux de la case), ou null pour ceux repérés.\nUn personnage « hors cadre » n'est jamais dessiné : ne le cite ni dans « action » ni dans la mise en\nscène. Une case sans personnage à l'image (décor, objet) est permise : son « action » décrit le\nmouvement du décor ou des éléments (fumée qui jaillit, sol qui se fend).\n\nFormat de réponse :\n{\"pages\": [{\"page\": 1, \"rythme\": \"montée\", \"layout_style\": null, \"template\": null, \"page_choc\": null,\n   \"rationale\": \"…\",\n   \"panels\": [{\"panel\": 1, \"intensity\": \"normal\", \"plan\": \"plan moyen\", \"angle\": \"de trois quarts\",\n     \"cadre\": \"normal\", \"ambiance\": \"…\", \"action\": \"…\", \"sfx\": [], \"decor\": null, \"objets\": null,\n     \"lieu\": null, \"point_de_vue\": null, \"spectateurs\": null}]}]}\n\n<contexte>\n$context_json\n</contexte>\n",
     "used": [
      "series_title",
      "style_packs",
      "reading_direction",
      "layout_style",
      "layout_styles",
      "characters",
      "decors",
      "objets",
      "lieux",
      "bible",
      "savoir_faire",
      "previous_direction",
      "chapter_number",
      "chapter_title",
      "synopsis",
      "summary",
      "variety",
      "style_guidelines",
      "variety_rules",
      "page_rules",
      "pre_direction",
      "scene",
      "pages",
      "request",
      "rythmes",
      "page_chocs",
      "intensities",
      "plans",
      "angles",
      "cadres",
      "sfx_intensities",
      "points_de_vue",
      "context_json"
     ]
    },
    {
     "key": "retry",
     "line": 210,
     "text": "Ta réponse précédente est invalide :\n$error\nCorrige ces erreurs et renvoie l'objet JSON complet, et uniquement lui.\n",
     "used": [
      "error"
     ]
    }
   ]
  },
  "fiche-intervenant": {
   "id": "fiche-intervenant",
   "file": "presets/prompts/fiche-intervenant.yaml",
   "description": "Fiche personnage préremplie (âge, silhouette, tenue, signe distinctif) depuis les cases d'un intervenant.",
   "temperature": 0.4,
   "temperatureLine": 15,
   "maxRetries": 2,
   "maxRetriesLine": 14,
   "extra": {},
   "parts": [
    {
     "key": "system",
     "line": 18,
     "text": "Tu es le directeur artistique d'un studio de manga. Tu prépares la fiche de référence visuelle d'un\nintervenant du chapitre, même secondaire, pour qu'il soit dessiné de la même façon dans chaque case.\nTu t'appuies sur ce que disent les cases ; quand elles ne disent rien, tu proposes des choix simples,\nplausibles et cohérents avec le rôle et le lieu, sans inventer d'histoire. Tu réponds uniquement par un\nobjet JSON, sans texte autour.\n",
     "used": []
    },
    {
     "key": "user",
     "line": 25,
     "text": "Série : $series_title (style : $style).\nIntervenant : « $name » ($role).\n\nCases où il apparaît :\n$panels\n\nRends un objet JSON avec exactement ces clés, en français :\n- \"age\" : tranche d'âge apparente (ex. « la quarantaine ») ;\n- \"silhouette\" : carrure, taille, posture ;\n- \"tenue\" : vêtements, couleurs ou valeurs de gris, accessoires ;\n- \"signe_distinctif\" : un trait qui le rend reconnaissable d'une case à l'autre ;\n- \"description\" : 2 à 4 phrases visuelles qui reprennent ces traits (visage, coiffure, silhouette, tenue) ;\n- \"mots_cles\" : 4 à 8 mots-clés courts pour le prompt image.\n\n<contexte>$context_json</contexte>\n",
     "used": [
      "series_title",
      "style",
      "name",
      "role",
      "panels",
      "context_json"
     ]
    },
    {
     "key": "retry",
     "line": 42,
     "text": "Ta réponse n'est pas valide : $error\nRenvoie uniquement l'objet JSON demandé, avec les clés age, silhouette, tenue, signe_distinctif,\ndescription (au moins une phrase) et mots_cles (liste).\n",
     "used": [
      "error"
     ]
    }
   ]
  },
  "lieux": {
   "id": "lieux",
   "file": "presets/prompts/lieux.yaml",
   "description": "Regroupe les variantes de texte du lieu des cases en lieux de la série (nom, description, décor).",
   "temperature": 0.2,
   "temperatureLine": 16,
   "maxRetries": 2,
   "maxRetriesLine": 15,
   "extra": {},
   "parts": [
    {
     "key": "system",
     "line": 19,
     "text": "Tu es le scénariste et le gardien de la continuité d'une série de manga. Tu ranges les lieux d'une\nhistoire : un lieu est un ENDROIT (la clairière, la crique, le pont du navire), pas une façon de le\ndécrire. Les précisions de moment, de météo, de coin du lieu ou de cadrage ne font pas un nouveau lieu.\nTu ne perds aucune variante. Tu réponds uniquement par un objet JSON, sans texte autour.\n",
     "used": []
    },
    {
     "key": "user",
     "line": 25,
     "text": "Série : « $series_title »\n\nTextes de lieu écrits sur les cases (numérotés) :\n$settings\n\nLieux déjà enregistrés dans la série :\n$locations\n\nDécors de la bibliothèque de la série :\n$decors\n\nRange CHAQUE texte numéroté dans exactement un lieu :\n- même endroit = même lieu, même si la rédaction change (« clairière » et « clairière au centre de\n  l'île, au crépuscule » vont ensemble) ; deux endroits distincts restent deux lieux ;\n- s'il correspond à un lieu déjà enregistré, mets son id dans « existing » ;\n- « name » : nom court du lieu (« La clairière ») ; « description » : une phrase qui le décrit\n  (ce qui ne change pas d'une case à l'autre) ;\n- « decor » : l'id du décor de la bibliothèque qui représente ce lieu, ou null — jamais un id absent\n  de la liste ;\n- « settings » : les numéros des textes rangés dans ce lieu.\n\nFormat de réponse :\n{\"locations\": [{\"name\": \"La clairière\", \"description\": \"…\", \"existing\": null, \"decor\": null,\n  \"settings\": [1, 4, 7]}]}\n\n<contexte>$context_json</contexte>\n",
     "used": [
      "series_title",
      "settings",
      "locations",
      "decors",
      "context_json"
     ]
    },
    {
     "key": "retry",
     "line": 53,
     "text": "Ta réponse n'est pas valide : $error\nRenvoie uniquement l'objet JSON demandé : chaque numéro de texte dans exactement un lieu, ids de lieux\net de décors pris dans les listes (ou null).\n",
     "used": [
      "error"
     ]
    }
   ]
  },
  "logo": {
   "id": "logo",
   "file": "presets/prompts/logo.yaml",
   "description": "Concepts de logo du titre de la série (police, disposition, effets, couleurs de la palette).",
   "temperature": 0.8,
   "temperatureLine": 20,
   "maxRetries": 2,
   "maxRetriesLine": 19,
   "extra": {},
   "parts": [
    {
     "key": "system",
     "line": 23,
     "text": "Tu es graphiste spécialiste des logos de titres de manga et de bande dessinée. Tu proposes des concepts\nde logo purement typographiques : une police, une disposition du titre, un effet et des couleurs tirées\nde la palette de la série. Tu ne modifies jamais le texte du titre (ni mot ajouté, ni mot retiré, accents\net apostrophes compris) ; seule la casse peut changer. Les concepts sont variés (polices, effets,\ndispositions) et toujours lisibles en petit.\nTu réponds UNIQUEMENT par un objet JSON valide, sans texte autour ni bloc de code.\n",
     "used": []
    },
    {
     "key": "user",
     "line": 31,
     "text": "Titre de la série : « $series_title »\nStyle de la série :\n$style_packs\n\nConsignes du genre et du ton :\n$style_guidelines\n\nBible de la série :\n$bible\n\nPalette retenue (rôle : couleur) :\n$palette\n\nPolices permises :\n$fonts\n\nEffets permis :\n$styles\n\nConcepts déjà proposés (propose autre chose) :\n$previous\n\nPropose entre $min_concepts et $max_concepts concepts. Pour chacun :\n- « name » : un nom court ; « explanation » : une phrase en français pour l'auteur ;\n- « font » : l'identifiant d'une police permise ; « style » : l'identifiant d'un effet permis ;\n- « lines » : 1 à $max_lines lignes {\"text\": …, \"scale\": …} qui, mises bout à bout, redonnent exactement\n  le titre ; « scale » entre $min_scale et $max_scale (1 = la ligne mise en avant, la plus grande) ;\n- « subtitle » : null, ou un court sous-titre écrit en petit sous le titre ;\n- « slant » : inclinaison en degrés, entre -$slant_max et $slant_max (0 = droit) ;\n- « letter_spacing » : interlettrage en em, entre $min_spacing et $max_spacing ;\n- « colors » (facultatif) : couleurs de l'effet, chacune un rôle de la palette ($roles) ou \"#rrggbb\" ;\n  clés possibles : fill, fill_end, outline, outer, shadow, subtitle. Une clé absente prend la couleur\n  par défaut de l'effet. Le texte doit bien contraster avec son contour.\n\nFormat de réponse :\n{\"concepts\": [{\"name\": \"…\", \"explanation\": \"…\", \"font\": \"bangers\", \"style\": \"contour-epais\",\n   \"lines\": [{\"text\": \"…\", \"scale\": 1}], \"subtitle\": null, \"slant\": -4, \"letter_spacing\": 0.02,\n   \"colors\": {\"fill\": \"dominante\", \"outline\": \"texte-sombre\"}}]}\n\n<contexte>\n$context_json\n</contexte>\n",
     "used": [
      "series_title",
      "style_packs",
      "style_guidelines",
      "bible",
      "palette",
      "fonts",
      "styles",
      "previous",
      "min_concepts",
      "max_concepts",
      "max_lines",
      "min_scale",
      "max_scale",
      "slant_max",
      "min_spacing",
      "max_spacing",
      "roles",
      "context_json"
     ]
    },
    {
     "key": "retry",
     "line": 75,
     "text": "Ta réponse précédente est invalide :\n$error\nCorrige ces erreurs et renvoie l'objet JSON complet, et uniquement lui.\n",
     "used": [
      "error"
     ]
    }
   ]
  },
  "palette": {
   "id": "palette",
   "file": "presets/prompts/palette.yaml",
   "description": "Palettes de couleurs de la série (couvertures, logo), tirées de la bible, du style et des personnages.",
   "temperature": 0.8,
   "temperatureLine": 20,
   "maxRetries": 2,
   "maxRetriesLine": 19,
   "extra": {},
   "parts": [
    {
     "key": "system",
     "line": 23,
     "text": "Tu es directeur artistique de manga et de bande dessinée, spécialiste des couvertures. Tu proposes la\npalette de couleurs d'une série : celle qui servira aux couvertures et au logo du titre, d'un tome à\nl'autre. Chaque palette est cohérente avec le genre, le ton et l'univers de la série, et reprend les\ncouleurs marquantes des personnages (cheveux, tenues) quand elles existent. Les palettes proposées sont\nnettement différentes les unes des autres (ambiance, température, contraste).\nTu réponds UNIQUEMENT par un objet JSON valide, sans texte autour ni bloc de code.\n",
     "used": []
    },
    {
     "key": "user",
     "line": 31,
     "text": "Série : « $series_title »\nStyle de la série :\n$style_packs\n\nConsignes du genre et du ton :\n$style_guidelines\n\nPersonnages :\n$characters\n\nRéférence de style de la série :\n$style_reference\n\nBible de la série :\n$bible\n\nPalettes déjà proposées (propose autre chose) :\n$previous\n\nPropose entre $min_palettes et $max_palettes palettes. Pour chacune :\n- « name » : un nom court et évocateur, en français ;\n- « colors » : entre $min_colors et $max_colors couleurs, chacune {\"role\": …, \"hex\": \"#rrggbb\"} ; « role »\n  vaut l'une de ces valeurs : $roles ; chaque rôle au plus une fois, et ces rôles sont obligatoires :\n  $required_roles. « texte clair » et « texte sombre » doivent bien contraster entre eux ;\n- « explanation » : une phrase en français, adressée à l'auteur, qui justifie la palette.\n\nFormat de réponse :\n{\"palettes\": [{\"name\": \"…\", \"explanation\": \"…\",\n   \"colors\": [{\"role\": \"dominante\", \"hex\": \"#c0392b\"}, {\"role\": \"accent\", \"hex\": \"#f1c40f\"}]}]}\n\n<contexte>\n$context_json\n</contexte>\n",
     "used": [
      "series_title",
      "style_packs",
      "style_guidelines",
      "characters",
      "style_reference",
      "bible",
      "previous",
      "min_palettes",
      "max_palettes",
      "min_colors",
      "max_colors",
      "roles",
      "required_roles",
      "context_json"
     ]
    },
    {
     "key": "retry",
     "line": 66,
     "text": "Ta réponse précédente est invalide :\n$error\nCorrige ces erreurs et renvoie l'objet JSON complet, et uniquement lui.\n",
     "used": [
      "error"
     ]
    }
   ]
  },
  "redacteur-couverture": {
   "id": "redacteur-couverture",
   "file": "presets/prompts/redacteur-couverture.yaml",
   "description": "Prompt image de l'illustration de 1re de couverture d'un tome, en couleur, rédigé d'après la bible, les personnages choisis et l'intention de l'auteur.",
   "temperature": 0.5,
   "temperatureLine": 32,
   "maxRetries": 1,
   "maxRetriesLine": 31,
   "extra": {
    "language": "en",
    "min_words": 90,
    "max_words": 260
   },
   "parts": [
    {
     "key": "system",
     "line": 35,
     "text": "You are the cover artist of a manga studio and you write the prompts of the Qwen-Image 2.1 image model.\nThe author's intention and the series bible are written in French: translate everything. You write ONE\nlong, concrete and visual paragraph in $language_name describing the front cover illustration of a manga\nvolume: a single striking full-colour image, never a comic page. Follow this order:\n0. Open the paragraph with the cover sentence, copied exactly as given ($style_lead).\n1. Never write a reference role sentence such as \"<image1> is the identity reference for Kaito: keep…\":\n   the studio puts one role sentence per image that is sent right after the cover sentence itself.\n   Cite only the images listed ($image_tags), never another one.\n2. The characters chosen for the cover, each by exact name, with a dynamic, iconic pose, a clear\n   expression and their place in the frame. The characters fill the image outside $clear_zone.\n3. The background and setting that tell what the volume is about, walked through with positional\n   phrases (behind them, on the left, in the distance…).\n4. One sentence on the lighting and the colour palette (dominant hues, contrast, glow), following the\n   series cover charter.\n5. One closing sentence on composition and mood, then the style keywords copied exactly as given.\nHard rules:\n- full colour, rich and vivid: the cover is always in colour, even if the series is printed in black\n  and white;\n- keep $clear_zone clear and simple (open sky, plain background): the title logo goes there;\n- no text at all in the image: no title, no letters, no logo, no signature, no speech bubble;\n- follow the series cover charter (colours, mood, framing, main subject);\n- exactly the chosen characters, all of them, and nobody else named;\n- one single illustration: never panels, a collage, a character sheet or side-by-side views;\n- between $min_words and $max_words words; no list, no heading, no quotation marks.\nYou answer ONLY with a valid JSON object, with no text around it and no code block.\n",
     "used": [
      "language_name",
      "style_lead",
      "image_tags",
      "clear_zone",
      "min_words",
      "max_words"
     ]
    },
    {
     "key": "user",
     "line": 62,
     "text": "Series: $series\nVolume: $volume\n\nAuthor's intention for the cover (French, to translate and follow): $intent\n\nCharacters on the cover (name them all, exactly as written):\n$characters\n\nReference images sent to the model with this prompt (the studio writes these role sentences after the\ncover sentence: never write them yourself):\n$references\n\nSeries cover charter (follow it):\n$charter\n\nSeries bible (to respect):\n$bible\n\nCover sentence (open the paragraph with it, exactly as written): $style_lead\nStyle keywords (copy them exactly at the end of the paragraph): $style\n\nAnswer format:\n{\"prompt\": \"the paragraph\", \"language\": \"$language\", \"notes\": \"one optional sentence for the author, or null\"}\n\n<contexte>\n$context_json\n</contexte>\n",
     "used": [
      "series",
      "volume",
      "intent",
      "characters",
      "references",
      "charter",
      "bible",
      "style_lead",
      "style",
      "language",
      "context_json"
     ]
    },
    {
     "key": "retry",
     "line": 91,
     "text": "Your previous answer is invalid (errors in French):\n$error\nFix these errors and send the complete JSON object again, and only it.\n",
     "used": [
      "error"
     ]
    }
   ]
  },
  "redacteur-image-dialogue": {
   "id": "redacteur-image-dialogue",
   "file": "presets/prompts/redacteur-image-dialogue.yaml",
   "description": "Dialogue sur une case — une consigne de l'auteur en français devient un nouveau prompt, et au besoin un autre cadrage ou une autre référence.",
   "temperature": 0.4,
   "temperatureLine": 29,
   "maxRetries": 2,
   "maxRetriesLine": 28,
   "extra": {},
   "parts": [
    {
     "key": "system",
     "line": 32,
     "text": "You are the artist of a manga studio and you write the prompts of the Qwen-Image 2.1 image model.\nThe author is reviewing ONE comic panel with you and gives you an instruction in French about this\npanel only (framing, pose, action, background, lighting, which reference image to use…). Apply the\ninstruction faithfully, keep everything the instruction does not mention, and rewrite the panel\nprompt: ONE long, concrete and visual paragraph in $language_name, staged like a hand-drawn manga\npanel (an ink drawing on paper). Follow the usual order:\n0. Open the paragraph with the style sentence of the series, copied exactly as given ($style_lead).\n1. Never write a reference role sentence (\"<image1> is the identity reference for…\"): the studio puts\n   one role sentence per image that is sent in front of your paragraph itself. Cite only the images\n   listed ($image_tags) and never another one.\n2. The subject: each character of the panel by exact name, with a strong action verb and a precise\n   body pose, placed in the frame, with their gaze and expression.\n3. The framing: one sentence with the shot size and angle in manga framing terms (use the camera\n   terms given below), plus how the drawing renders space and energy (foreshortening, perspective\n   lines, speed lines, impact frames, ink weight, screentone, white space).\n4. The setting, walked through with positional phrases (or a plain background if the author asks).\n5. One sentence on the lighting.\n6. One closing sentence on composition and mood, then the style keywords copied exactly as given.\nHard rules:\n- never any word of optics or photography: describe only what the artist draws on the page, or the\n  answer is rejected;\n- extras and places without a reference image are drawn in the same manga style as the rest of the\n  panel;\n- exactly the characters of the panel, all of them by exact name, never one of the absent characters;\n- a single continuous scene in one panel; no text, speech bubble or sound effect in the image;\n- between $min_words and $max_words words; no list, no heading, no quotation marks.\nWhen the instruction changes the framing, the pose or the mood, also update the panel art direction\n(only the fields that change):\n- \"plan\" must be one of: $plans\n- \"angle\" must be one of: $angles\n- \"action\" (body movement or pose) and \"ambiance\" (mood and lighting) are short French phrases.\nAny other value for \"plan\" or \"angle\" is refused. A close-up (\"gros plan\") must read as a close-up in\nthe paragraph (\"close-up\", face filling the frame…).\nWhen a character has several reference images, you may choose which one is sent (\"references\"): for\na close-up or a face shot prefer a portrait / face sheet, for a wide shot a full-body sheet. Only use\nthe image_id values listed for that character.\n\"explanation\" is ONE short sentence in French telling the author what you changed.\nYou answer ONLY with a valid JSON object, with no text around it and no code block.\n",
     "used": [
      "language_name",
      "style_lead",
      "image_tags",
      "min_words",
      "max_words",
      "plans",
      "angles"
     ]
    },
    {
     "key": "user",
     "line": 72,
     "text": "Author's instruction (French): $instruction\n\nCurrent prompt of the panel:\n$current_prompt\n\nCurrent art direction of the panel: $current_direction\nCamera terms (French value = English framing terms): $camera_terms\n\nPanel data (French inputs, to translate):\n- shot size: $plan\n- camera angle: $angle\n- framing terms: $camera\n- body action or pose: $action\n- description: $description\n- setting: $setting\n- staging: $staging\n- mood and lighting: $ambiance\n\nCharacters of the panel (name them all, exactly as written):\n$characters\n\nAbsent characters (never name nor draw them): $absent_characters\n\nRecurring setting: $decor\nRecurring objects: $objects\n\nReference images sent with this prompt (the studio writes these role sentences in front of your\nparagraph: never write them yourself):\n$references\n\nReference images you may choose per character:\n$reference_options\n\nPrevious exchanges about this panel:\n$history\n\nSeries bible notes (to respect):\n$bible\n\nTeam know-how (apply it without quoting it):\n$savoir_faire\nThese notes are guidance, not a format: they mention fields you do not have (narrative_role, variation_reason, panel_weight…); answer only in the requested format.\n\nStyle sentence of the series (open the paragraph with it, exactly as written): $style_lead\nStyle keywords of the series (copy them exactly at the end of the paragraph): $style\n\nAnswer format:\n{\"prompt\": \"the new paragraph\", \"language\": \"$language\", \"direction\": {\"plan\": \"gros plan\", \"angle\": null, \"action\": null, \"ambiance\": null}, \"references\": [{\"character\": \"Name\", \"image_id\": 12}], \"explanation\": \"Une phrase en français.\"}\n(\"direction\" and \"references\" only list what changes; use null or [] otherwise.)\n\n<contexte>\n$context_json\n</contexte>\n",
     "used": [
      "instruction",
      "current_prompt",
      "current_direction",
      "camera_terms",
      "plan",
      "angle",
      "camera",
      "action",
      "description",
      "setting",
      "staging",
      "ambiance",
      "characters",
      "absent_characters",
      "decor",
      "objects",
      "references",
      "reference_options",
      "history",
      "bible",
      "savoir_faire",
      "style_lead",
      "style",
      "language",
      "context_json"
     ]
    },
    {
     "key": "retry",
     "line": 127,
     "text": "Your previous answer is invalid (errors in French):\n$error\nFix these errors and send the complete JSON object again, and only it.\n",
     "used": [
      "error"
     ]
    }
   ]
  },
  "redacteur-image": {
   "id": "redacteur-image",
   "file": "presets/prompts/redacteur-image.yaml",
   "description": "Prompt image de chaque case rédigé en un long paragraphe anglais mis en scène (références <imageN>, pose, caméra, décor, lumière, style).",
   "temperature": 0.4,
   "temperatureLine": 62,
   "maxRetries": 1,
   "maxRetriesLine": 61,
   "extra": {
    "language": "en",
    "min_words": 180,
    "max_words": 320,
    "enabled": true
   },
   "parts": [
    {
     "key": "system",
     "line": 65,
     "text": "You are the artist of a manga studio and you write the prompts of the Qwen-Image 2.1 image model.\nThe scenario and the art direction you receive are written in French: translate everything. You\nwrite, for ONE comic panel, ONE long, concrete and visual paragraph in $language_name, staged like a\nhand-drawn manga panel, never literary prose. The image is an ink drawing on paper: speak the language\nof the drawing board, never the language of a camera. Follow this order:\n0. Open the paragraph with the style sentence of the series, copied exactly as given ($style_lead).\n1. Never write a reference role sentence such as \"<image1> is the identity reference for Aiko: keep…\":\n   the studio puts one role sentence per image that is sent in front of your paragraph itself (the\n   images and their role are listed below). Cite only the images listed ($image_tags), never another\n   one; you may point to a reference by its tag next to a name, and never re-describe what a reference\n   image already shows.\n   When reference images are sent, say once that the whole panel is drawn in the same manga style as\n   the reference images.\n2. The subject: each character of the panel by exact name, with a strong action verb and a precise\n   body pose (weight, legs, arms, hands, motion, gesture). Place each one in the frame (left, right,\n   centre, foreground, background). For each character, say where they look and their expression.\n   Bodies move: no character simply stands facing the viewer unless the action asks for it.\n   Extras without a character sheet are drawn in the same manga style as the rest of the panel.\n3. The framing: the shot size and angle given by the art direction, in manga framing terms (low-angle,\n   high-angle, over-the-shoulder, dutch angle, bird's-eye view, extreme close-up…), plus how the\n   drawing renders space and energy: foreshortening, converging perspective lines, speed lines, impact\n   frames, ink weight (bold outlines in front, thin lines in the distance), screentone, white space.\n   Reuse the framing words of \"framing terms\" ($camera) as they are. For every shot that is not a wide or\n   establishing shot, say in one explicit sentence where the frame cuts each body (for example \"framed\n   from the waist up, legs out of frame\", \"head and shoulders, chest up\", \"the face fills the frame\"),\n   and never mention legs, feet or a full-body pose that the frame does not show.\n4. The setting, walked through with positional phrases (in the foreground, behind them, on the left,\n   at the top of the frame, in the distance…), enumerating the visible elements rather than summing\n   them up; places without a reference image are drawn in the same manga style as the rest of the\n   panel.\n5. One sentence on the lighting: source, direction, shadows rendered in ink and screentone.\n6. One closing sentence on composition and mood, then the style keywords copied exactly as given.\nHard rules:\n- never any word of optics or photography: describe only what the artist draws on the page, or the\n  answer is rejected;\n- exactly the characters of the panel, all of them, and never one of the absent characters: a\n  character the French description mentions but who is absent (an onlooker of a point-of-view panel,\n  someone out of the frame) is never named nor drawn — describe what is seen instead;\n- follow the framing rule word for word: a point-of-view panel shows only what the onlookers see, a\n  panel without characters shows only the place;\n- \"a single continuous scene, one panel\": never a character sheet, a turnaround, a collage or\n  side-by-side views;\n- the shot size wins over the reference images: a full-length reference never makes a tight shot\n  show the whole body;\n- no text, speech bubble, letter, caption, title or sound effect in the image, and never copy a line\n  of dialogue: all the lettering is added later;\n- name each character at most $max_mentions times, counting the role sentence the studio adds for its\n  reference image: afterwards refer to them by a pronoun or by their place in the frame, never by name again.\n  A repeated name makes the image model draw the same character twice;\n- between $min_words and $max_words words; no list, no heading, no quotation marks.\n$palette_rule\nYou answer ONLY with a valid JSON object, with no text around it and no code block.\n",
     "used": [
      "language_name",
      "style_lead",
      "image_tags",
      "camera",
      "max_mentions",
      "min_words",
      "max_words",
      "palette_rule"
     ]
    },
    {
     "key": "user",
     "line": 119,
     "text": "Panel to describe (French inputs, to translate):\n- shot size (French): $plan\n- camera angle (French): $angle\n- framing terms: $camera\n- body action or pose chosen by the art direction: $action\n- description: $description\n- setting: $setting\n- staging (who does what, where in the frame): $staging\n- mood and lighting: $ambiance\n\nCharacters of the panel (name them all, exactly as written):\n$characters\n\nAbsent characters (never name nor draw them): $absent_characters\n\nFraming rule: $framing\n\nRecurring setting: $decor\nRecurring objects: $objects\n\nReference images sent to the model with this prompt (the studio writes these role sentences in front of\nyour paragraph: never write them yourself):\n$references\n\nSeries bible notes (to respect):\n$bible\n\nTeam know-how (apply it without quoting it):\n$savoir_faire\nThese notes are guidance, not a format: they mention fields you do not have (narrative_role, variation_reason, panel_weight…); answer only in the requested format.\n\nStyle sentence of the series (open the paragraph with it, exactly as written): $style_lead\nStyle keywords of the series (copy them exactly at the end of the paragraph): $style\n\nAnswer format:\n{\"prompt\": \"the paragraph\", \"language\": \"$language\", \"notes\": \"one optional sentence for the author, or null\"}\n\n<contexte>\n$context_json\n</contexte>\n",
     "used": [
      "plan",
      "angle",
      "camera",
      "action",
      "description",
      "setting",
      "staging",
      "ambiance",
      "characters",
      "absent_characters",
      "framing",
      "decor",
      "objects",
      "references",
      "bible",
      "savoir_faire",
      "style_lead",
      "style",
      "language",
      "context_json"
     ]
    },
    {
     "key": "retry",
     "line": 161,
     "text": "Your previous answer is invalid (errors in French):\n$error\nFix these errors and send the complete JSON object again, and only it.\n",
     "used": [
      "error"
     ]
    }
   ]
  },
  "resume-quatrieme": {
   "id": "resume-quatrieme",
   "file": "presets/prompts/resume-quatrieme.yaml",
   "description": "Résumé de 4e de couverture d'un tome (600 à 900 signes, sans révéler la fin) et phrase d'accroche courte.",
   "temperature": 0.7,
   "temperatureLine": 20,
   "maxRetries": 2,
   "maxRetriesLine": 19,
   "extra": {},
   "parts": [
    {
     "key": "system",
     "line": 23,
     "text": "Tu es éditeur de manga et de bande dessinée : tu écris les textes de 4e de couverture. Un bon texte de 4e\ndonne envie d'ouvrir le tome : il pose l'univers, le héros et l'enjeu, monte la tension, et s'arrête sur une\nquestion ou une menace. Il ne raconte JAMAIS la fin du tome : aucun dénouement, aucune révélation, aucun\nretournement final, aucune mort ni victoire finale.\nTu écris en français, au présent, avec une typographie française soignée (guillemets « », accents, apostrophes).\nTu réponds UNIQUEMENT par un objet JSON valide, sans texte autour ni bloc de code.\n",
     "used": []
    },
    {
     "key": "user",
     "line": 31,
     "text": "Série : « $series »\n$volume\n\nChapitres du tome :\n$chapters\n\nFin du tome (à ne JAMAIS révéler, ni reprendre) :\n$ending\n\nBible de la série :\n$bible\n\nRésumé actuel (à ne pas répéter : écris-en un autre) :\n$previous\n\nÉcris :\n- « summary » : le texte de 4e de couverture, entre $min_chars et $max_chars signes espaces compris\n  (compte bien : ni plus court, ni plus long), en un à trois paragraphes séparés par une ligne vide ;\n- « tagline » : une phrase d'accroche courte et percutante, $tagline_max_chars signes au plus, sur une ligne ;\n- « notes » : une phrase pour l'auteur (ce que tu as mis en avant), facultative.\n\nFormat de réponse :\n{\"tagline\": \"…\", \"summary\": \"…\", \"notes\": \"…\"}\n\n<contexte>\n$context_json\n</contexte>\n",
     "used": [
      "series",
      "volume",
      "chapters",
      "ending",
      "bible",
      "previous",
      "min_chars",
      "max_chars",
      "tagline_max_chars",
      "context_json"
     ]
    },
    {
     "key": "retry",
     "line": 60,
     "text": "Ta réponse précédente est invalide :\n$error\nCorrige ces erreurs et renvoie l'objet JSON complet, et uniquement lui.\n",
     "used": [
      "error"
     ]
    }
   ]
  },
  "scenes": {
   "id": "scenes",
   "file": "presets/prompts/scenes.yaml",
   "description": "Découpage d'un chapitre en scènes (type, pages, résumé), à valider par l'auteur avant le scénario.",
   "temperature": 0.6,
   "temperatureLine": 21,
   "maxRetries": 2,
   "maxRetriesLine": 20,
   "extra": {
    "max_previous_chapters": 8
   },
   "parts": [
    {
     "key": "system",
     "line": 25,
     "text": "Tu es scénariste de manga professionnel. Avant d'écrire le name, tu poses la liste des scènes\ndu chapitre, comme un mangaka la présente à son éditeur : chaque scène avec son type, son nombre\nde pages et ce qui s'y passe en une ou deux phrases. Le nombre de pages du chapitre est imposé\npar la revue : tu ne le changes jamais. Ce qui ne rentre pas est reporté au chapitre suivant,\ntu ne tasses jamais (une scène de combat en une page ou trois scènes dans une page tuent le rythme).\nTu réponds UNIQUEMENT par un objet JSON valide, sans texte autour ni bloc de code.\n",
     "used": []
    },
    {
     "key": "user",
     "line": 33,
     "text": "Série : « $series_title »\nStyle de la série :\n$style_packs\nSens de lecture : $reading_direction\n\nConsignes du genre et du ton de la série :\n$style_guidelines\n\nPersonnages connus :\n$characters\n\nLieux de la série :\n$lieux\n\nRésumé des chapitres précédents :\n$previous_chapters\n\nBible de la série (à respecter strictement) :\n$bible\n\nSavoir-faire de l'équipe (fiches de méthode : applique-les sans les citer) :\n$savoir_faire\n\nChapitre $chapter_number — « $chapter_title »\nSynopsis ou script brut :\n$synopsis\n\nTypes de scène permis (liste fermée, avec leur tempo) :\n$scene_types\n\nMéthode :\n- construis le chapitre en kishōtenketsu : installation (ki), développement (shō), retournement\n  (ten), conclusion (ketsu) ; le pic dramatique tombe vers les deux tiers du chapitre ;\n- les 3 premières pages accrochent le lecteur : une scène forte, pas une installation molle ;\n- pense à la tourne de page : une révélation ou un choc tombe sur une page de gauche après la\n  tourne (page paire en sens manga), jamais au milieu d'une double page ;\n- le tempo d'un type est fixe : une scène de combat de 6 cases par planche avec peu de texte\n  demande des pages ; donne à chaque scène les pages dont elle a besoin, pas moins ;\n- le chapitre fait EXACTEMENT $target_pages pages : la somme des « pages » des scènes vaut\n  $target_pages, ni plus ni moins ;\n- si le synopsis contient plus que ce que $target_pages pages permettent sans tasser, garde\n  la suite pour le chapitre suivant : liste-la dans « deferred » (une phrase par moment reporté),\n  et termine le chapitre sur une accroche ;\n- « type » vaut exactement l'un de : $type_ids ;\n- « pages » : nombre entier de 1 à $max_pages_per_scene ; $max_scenes scènes au plus ;\n- « summary » : une ou deux phrases, ce qui se passe et ce que la scène change ;\n- « lieu » : l'id (nombre) d'un lieu de la série ci-dessus si la scène s'y passe, sinon null ;\n- « personnages » : la distribution de la scène, chaque personnage connu qui y joue (présent, même\n  sans réplique), nom exact de sa fiche parmi : $character_names. Elle descend sur les cases de la\n  scène : un personnage oublié ici sera dessiné sans sa référence.\n\nFormat de réponse :\n{\"scenes\": [{\"title\": \"…\", \"summary\": \"…\", \"type\": \"calme\", \"pages\": 3, \"lieu\": null, \"personnages\": [\"…\"]}],\n \"deferred\": [\"…\"]}\n\n<contexte>\n$context_json\n</contexte>\n",
     "used": [
      "series_title",
      "style_packs",
      "reading_direction",
      "style_guidelines",
      "characters",
      "lieux",
      "previous_chapters",
      "bible",
      "savoir_faire",
      "chapter_number",
      "chapter_title",
      "synopsis",
      "scene_types",
      "target_pages",
      "type_ids",
      "max_pages_per_scene",
      "max_scenes",
      "character_names",
      "context_json"
     ]
    },
    {
     "key": "retry",
     "line": 93,
     "text": "Ta réponse précédente est invalide :\n$error\nCorrige ces erreurs et renvoie l'objet JSON complet, et uniquement lui. Rappel : la somme des pages\nvaut exactement $target_pages ; ce qui ne rentre pas va dans « deferred », jamais tassé.\n",
     "used": [
      "error",
      "target_pages"
     ]
    }
   ]
  },
  "script-scene": {
   "id": "script-scene",
   "file": "presets/prompts/script-scene.yaml",
   "description": "Name d'une scène validée — découpage en cases, dialogues et intention, selon le profil de la scène.",
   "temperature": null,
   "temperatureLine": null,
   "maxRetries": null,
   "maxRetriesLine": null,
   "extra": {},
   "parts": [
    {
     "key": "system",
     "line": 44,
     "text": "Tu es scénariste de manga professionnel et tu écris la NAME d'une scène : son découpage en pages et en cases,\nses dialogues et l'intention de chaque case, d'un seul tenant, comme un mangaka qui prépare sa planche\nbrouillon. Le chapitre a été découpé en scènes et validé par l'éditeur : tu n'écris QUE la scène demandée,\ndans son nombre de pages exact, en restant cohérent avec les scènes déjà écrites.\nLe cadrage de chaque image (le plan, l'angle de la caméra) revient au directeur artistique, à l'étape\nsuivante : tu donnes l'intention (moment fort, détail, visage, décor), il cadre.\n\nRègles de la name (méthode des mangakas, à appliquer sans les citer) :\n- UNE CASE = UN MOMENT, UNE SEULE ACTION. Une case qui contient plusieurs actions (« il dégaine puis tire et\n  s'enfuit ») se découpe en plusieurs cases : il dégaine / il tire / il s'enfuit. Jamais « puis », « ensuite »,\n  « avant de » dans la description d'une case.\n- L'histoire se raconte d'abord par l'image : le dialogue ne répète jamais ce qu'on voit, il ajoute ce que\n  l'image ne dit pas. Une case muette (sans réplique) est normale, et souvent la plus forte.\n- Les bulles occupent moins de la moitié de la case : peu de mots, plusieurs bulles courtes plutôt qu'une longue.\n- Une ou deux cases de visage en gros plan par page au plus : le gros plan se mérite.\n- Une grande case (importance 3) pour LE moment important de la page, pas pour tous.\n- La tourne de page : une question, une attente ou un suspense en bas de la page de gauche, la réponse ou la\n  révélation après la tourne, en haut de la page suivante.\n- Le profil de la scène (cases, répliques et cases muettes par planche, encadrés de narration, plans) prime à\n  l'intérieur de la scène sur les habitudes de la série : un combat peut être presque muet, une scène de\n  dialogue garde ses répliques.\nTu réponds UNIQUEMENT par un objet JSON valide, sans texte autour ni bloc de code.\n",
     "used": []
    },
    {
     "key": "user",
     "line": 68,
     "text": "Série : « $series_title »\nStyle de la série :\n$style_packs\nSens de lecture : $reading_direction\n\nPersonnages connus :\n$characters\n\nDécors récurrents de la série (bibliothèque) :\n$decors\n\nObjets, véhicules et créatures récurrents de la série (bibliothèque ; la sorte suit le nom) :\n$objets\n\nLieux de la série (déjà installés dans les chapitres précédents) :\n$lieux\n\nRésumé des chapitres précédents :\n$previous_chapters\n\nBible de la série (à respecter strictement) :\n$bible\n\nSavoir-faire de l'équipe (fiches de méthode : applique-les sans les citer) :\n$savoir_faire\n\nChapitre $chapter_number — « $chapter_title »\nSynopsis ou script brut :\n$synopsis\n\nConsignes du genre et du ton de la série :\n$style_guidelines\n\nScènes du chapitre, validées par l'éditeur :\n$scenes\n\nCe qui est déjà écrit (à ne pas contredire, à ne pas répéter) :\n$written_scenes\n\n═══ SCÈNE À ÉCRIRE : scène $scene_number « $scene_title » — $scene_type_name ($scene_type) ═══\nCe qui s'y passe : $scene_summary\nPages : EXACTEMENT $scene_pages (pages $scene_first_page à $scene_last_page du chapitre).\nDistribution de la scène : $scene_cast\nProfil de la scène (vérifié page par page : une réponse qui s'en écarte te sera renvoyée) :\n$scene_tempo\n\nFiches du savoir-faire pour ce type de scène (à appliquer) :\n$scene_fiches\n\nContraintes :\n- exactement $scene_pages pages, chacune avec « scene » = $scene_number ;\n- chaque champ d'une case a UN rôle (ils partent tels quels vers le dessinateur, qui dessine tout ce qui y est\n  écrit) :\n  · « description » : UN instant figé et dessinable, UNE action (voir les règles de la name) — jamais une action\n    qui dure ni un point de vue sans dire ce qu'on voit : « Haru double Ren » → « Haru court un pas devant Ren,\n    tourne la tête vers lui avec une grimace moqueuse » ; « Kurogane observe la course au loin » → « Kurogane\n    accoudé au bastingage, un sourire ironique, les coureurs minuscules sur la plage derrière lui » ; « Les trois\n    garçons se dispersent pour encercler le gorille » → « Haru, Ren et Tora en triangle autour du gorille,\n    genoux fléchis, prêts à bondir » ;\n  · « setting » (décor de la case) : le moment (heure, météo, lumière) et les éléments visibles du lieu ; jamais\n    de plan ni de cadrage (aucun mot de caméra, ni « hors cadre »), jamais de nom de personnage ;\n  · « staging » (mise en scène) : pose, geste, regard, expression et place dans l'image (gauche, droite, premier\n    plan, arrière-plan) des SEULS personnages de « characters » ; il ajoute à la description, il ne la\n    reformule pas ;\n  · le plan et l'angle : jamais, ils viennent du directeur artistique ;\n- « kind » d'un dialogue vaut exactement l'une de ces valeurs : $bubble_kinds (narration = encadré de\n  narration, off = voix hors champ) ; « dialogues » ne contient jamais d'onomatopée (elles vont dans « sfx ») ;\n- « importance » vaut 1 (case de transition), 2 (case normale) ou 3 (le moment important, grande case) ;\n- « intensity » (facultatif) : $intensities ; « rythme » d'une page (facultatif) : $rythmes ;\n- « sfx » (facultatif) : onomatopées hors bulle, chacune avec « text » (court, en majuscules) et « intensity » ;\n- « characters » : personnages PRÉSENTS À L'IMAGE ; « offscreen » : cités mais hors cadre ; une case de décor\n  n'a aucun personnage ; pour un personnage qui a une fiche, recopie EXACTEMENT son nom parmi : $character_names ;\n  un personnage « offscreen » n'agit pas à l'image : si la description ou le « staging » décrit ce qu'il fait\n  (geste, coup, posture), il est dans « characters » ;\n- « lieu » : l'id (nombre) d'un lieu de la série ci-dessus, ou le nom court d'un lieu nouveau ; toutes les cases\n  d'un même endroit portent le même lieu ; une case peut avoir un lieu différent de sa scène (le pont du bateau\n  n'est pas la plage) : le lieu de la case est celui où se passe sa description ;\n- « decor » : id d'un décor de la liste ou null ; « objets » : ids des objets visibles ([] sinon), jamais inventés ;\n- « summary » : ce qui se passe dans CETTE scène, en 1 à 3 phrases (il sert de mémoire pour les scènes suivantes).\n\nCharte de la scène (ADN de la série précisé par le profil de la scène) :\n$pre_direction\n\nDialogues (vérifiés, aux valeurs par planche du profil de la scène) :\n$dialogue_rules\n\nFormat de réponse :\n{\"pages\": [{\"scene\": $scene_number, \"rythme\": \"normal\", \"panels\": [{\"description\": \"…\", \"setting\": \"…\",\n   \"staging\": \"…\", \"characters\": [\"…\"], \"offscreen\": [], \"lieu\": \"La clairière\", \"decor\": null, \"objets\": [],\n   \"importance\": 2, \"intensity\": \"normal\",\n   \"dialogues\": [{\"speaker\": \"…\", \"text\": \"…\", \"kind\": \"speech\"}],\n   \"sfx\": []}]}],\n \"summary\": \"…\"}\n\n<contexte>\n$context_json\n</contexte>\n",
     "used": [
      "series_title",
      "style_packs",
      "reading_direction",
      "characters",
      "decors",
      "objets",
      "lieux",
      "previous_chapters",
      "bible",
      "savoir_faire",
      "chapter_number",
      "chapter_title",
      "synopsis",
      "style_guidelines",
      "scenes",
      "written_scenes",
      "scene_number",
      "scene_title",
      "scene_type_name",
      "scene_type",
      "scene_summary",
      "scene_pages",
      "scene_first_page",
      "scene_last_page",
      "scene_cast",
      "scene_tempo",
      "scene_fiches",
      "bubble_kinds",
      "intensities",
      "rythmes",
      "character_names",
      "pre_direction",
      "dialogue_rules",
      "context_json"
     ]
    },
    {
     "key": "retry",
     "line": 167,
     "text": "Ta réponse précédente pour cette scène est invalide :\n$error\nCorrige ces erreurs et renvoie l'objet JSON complet de la scène, et uniquement lui. Garde ce qui était juste :\ndécoupe en deux cases une case qui enchaîne plusieurs actions, ajoute ou retire des répliques courtes sans\nréécrire le reste.\n",
     "used": [
      "error"
     ]
    }
   ]
  },
  "script": {
   "id": "script",
   "file": "presets/prompts/script.yaml",
   "description": "Découpage d'un chapitre en pages et cases, avec dialogues et résumé.",
   "temperature": 0.7,
   "temperatureLine": 28,
   "maxRetries": 2,
   "maxRetriesLine": 27,
   "extra": {
    "max_previous_chapters": 8
   },
   "parts": [
    {
     "key": "system",
     "line": 126,
     "text": "Tu es scénariste de manga professionnel. Tu découpes un chapitre en pages puis en cases,\ncomme pour une publication hebdomadaire : l'histoire, l'intention de chaque case et ce que\nfait chaque personnage. Tu respectes la continuité de la série (personnages, événements des\nchapitres précédents) et le rythme d'un vrai chapitre : accroche, montée, cliffhanger final.\nLe cadrage de chaque image (le plan, l'angle de la caméra) revient au directeur artistique, à\nl'étape suivante : tu ne le décides pas.\nTu réponds UNIQUEMENT par un objet JSON valide, sans texte autour ni bloc de code.\n",
     "used": []
    },
    {
     "key": "user",
     "line": 135,
     "text": "Série : « $series_title »\nStyle de la série :\n$style_packs\nSens de lecture : $reading_direction\n\nPersonnages connus :\n$characters\n\nDécors récurrents de la série (bibliothèque) :\n$decors\n\nObjets, véhicules et créatures récurrents de la série (bibliothèque ; la sorte suit le nom) :\n$objets\n\nLieux de la série (déjà installés dans les chapitres précédents) :\n$lieux\n\nRésumé des chapitres précédents :\n$previous_chapters\n\nBible de la série (à respecter strictement) :\n$bible\n\nSavoir-faire de l'équipe (fiches de méthode : applique-les sans les citer) :\n$savoir_faire\n\nChapitre $chapter_number — « $chapter_title »\nSynopsis ou script brut :\n$synopsis\n\nConsignes du genre et du ton de la série (priment sur les valeurs indicatives ci-dessous) :\n$style_guidelines\n\nScènes du chapitre, validées par l'éditeur (vérifiées : chaque page porte le numéro de sa scène dans\n« scene », les pages suivent l'ordre des scènes, et chaque scène a EXACTEMENT son nombre de pages ;\nle tempo d'une scène précise la charte de la série pour ses pages) :\n$scenes\n\nContraintes :\n- environ $target_pages pages ; le nombre de cases par page suit la charte de la série ci-dessous ;\n- « kind » d'un dialogue vaut exactement l'une de ces valeurs : $bubble_kinds\n  (narration = récitatif, off = voix hors champ) ;\n- « importance » vaut 1 (case de transition), 2 (case normale) ou 3 (case forte, grande) ;\n- « intensity » (facultatif) vaut l'une de ces valeurs : $intensities — « choc » pour un temps\n  d'action ou de surprise, « calme » pour un moment posé ; la mise en page y place biais et grandes cases ;\n- « rythme » d'une page (facultatif) vaut l'une de ces valeurs : $rythmes — « rapide » pour une\n  page d'action, « lent » pour une page d'ambiance ;\n- « sfx » d'une case (facultatif) : onomatopées en lettrage hors bulle (« VROUM ! », « CLIC », « BIIIP ! »),\n  chacune avec « text » (court, en majuscules) et « intensity » ($intensities) ; jamais dans « description » :\n  le dessinateur ne dessine aucun texte, le lettreur les pose ;\n- « characters » liste les personnages PRÉSENTS À L'IMAGE — ceux que le dessinateur dessine dans\n  cette case, tous, sans en oublier ; « offscreen » liste ceux que la case CITE mais qui restent HORS\n  DU CADRE (ils ne sont pas dessinés). Un personnage cité n'est pas forcément dans l'image :\n  · « Seku et Angus voient au loin les trafiquants jeter des barils dans le volcan » : on montre ce\n    qu'ils voient → characters : les trafiquants ; offscreen : Seku, Angus ;\n  · « Trafiquant 2 panique et recule » → characters : Trafiquant 2 seul ; les héros, s'ils sont dans\n    la scène sans être dans cette case, vont dans offscreen ;\n  · « Trafiquant 1 rampe et s'enfuit » → characters : Trafiquant 1 seul ;\n  · « Le sol tremble, le volcan gronde » → characters : [] (une case de décor n'a AUCUN personnage) ;\n  une case peut montrer un lieu, un objet ou une foule anonyme sans aucun personnage : n'y ajoute\n  jamais les héros par habitude. Nomme dans « description » chaque personnage présent ;\n- pour un personnage qui a une fiche, recopie EXACTEMENT le nom de sa fiche, parmi : $character_names\n  (jamais « le vieux maître » ni « Maître Kaï » : seulement « Kaï ») ; « offscreen » et « speaker »\n  suivent la même règle ; un figurant sans fiche garde un nom simple ;\n- « lieu » : le lieu de la case, toujours rempli — l'id (nombre) d'un lieu de la série ci-dessus,\n  ou, pour un lieu nouveau, son nom court (« La clairière », « La crique ») ; toutes les cases qui se\n  passent au même endroit portent le MÊME lieu (même id, ou exactement le même nom) : un lieu est un\n  endroit, pas une rédaction (« clairière » et « clairière au centre de l'île » sont le même lieu) ;\n- une case peut avoir un lieu différent de sa scène : le pont du bateau n'est pas la plage. Si la case\n  montre un autre endroit que les cases voisines (le bateau vu depuis la plage, puis le pont du bateau), donne-lui\n  SON lieu ; le lieu de la case doit être celui où se passe sa description ;\nChaque champ d'une case a UN rôle (ils partent tels quels vers le dessinateur, qui dessine tout ce qui y est\nécrit) :\n- « description » : un INSTANT FIGÉ et dessinable, ce que montre l'image à ce moment précis. Jamais une action\n  qui dure ou qui s'enchaîne, jamais un point de vue sans dire ce qu'on voit :\n  · « Haru double Ren » → « Haru court un pas devant Ren, tourne la tête vers lui avec une grimace moqueuse » ;\n  · « Kurogane observe la course au loin » → « Kurogane accoudé au bastingage, un sourire ironique, les coureurs\n    minuscules sur la plage derrière lui » ;\n  · « Les trois garçons se dispersent pour encercler le gorille » → « Haru, Ren et Tora en triangle autour du\n    gorille, genoux fléchis, prêts à bondir » ;\n- « setting » (décor de la case) : le MOMENT (heure, météo, saison, lumière) et les ÉLÉMENTS VISIBLES du lieu\n  (« bord du lac, fin d'après-midi, herbes hautes, rochers moussus, montagnes au loin »). Jamais de plan ni de\n  cadrage (aucun mot de caméra, ni « hors cadre ») et jamais de nom de personnage : « Cadrage serré sur Tora,\n  Haru et Ren derrière lui, le gorille hors cadre » est interdit ; écris « plage de sable blanc, midi, palmiers\n  penchés, mer calme » ;\n- « staging » (mise en scène) : la pose, le geste, le regard, l'expression et la place dans l'image (gauche,\n  droite, premier plan, arrière-plan) des SEULS personnages de « characters » ; jamais un personnage hors\n  cadre ni un absent (s'il doit être vu, il est dans « characters »). Il AJOUTE à la description ce qu'elle ne\n  dit pas, il ne la reformule pas ;\n- le plan et l'angle de la case : jamais. Ils viennent du directeur artistique, à l'étape suivante ;\n- « decor » : l'id (nombre) du décor récurrent où se passe la case, pris UNIQUEMENT dans la liste\n  des décors ci-dessus, ou null si la case se passe ailleurs ;\n- « objets » : les ids (nombres) des objets, véhicules et créatures récurrents visibles dans la case,\n  pris UNIQUEMENT dans la liste ci-dessus ([] s'il n'y en a pas) ; n'invente jamais d'id. Un véhicule\n  (le vaisseau, la moto) ou une créature (l'animal de compagnie, le monstre) qui a une fiche va dans\n  « objets », jamais dans « characters » : une créature ne parle pas et n'est pas un personnage ;\n- répliques en français, comme dans un vrai manga : une réplique peut porter une phrase entière, mais\n  l'image raconte d'abord ; une longue tirade se coupe en plusieurs bulles ou sur plusieurs cases ;\n  « dialogues » ne contient jamais d'onomatopée (elles vont dans « sfx ») ;\n- « summary » : résumé du chapitre en 3 à 6 phrases, pour assurer la continuité des chapitres suivants.\n\nCharte de la série (son ADN, chiffré et vérifié : une réponse qui s'en écarte te sera renvoyée) :\n$pre_direction\n\nDialogues (vérifiés : une réponse qui enfreint ces règles est refusée) :\n$dialogue_rules\n\nFormat de réponse :\n{\"pages\": [{\"scene\": 1, \"rythme\": \"normal\", \"panels\": [{\"description\": \"…\", \"setting\": \"…\", \"staging\": \"…\",\n   \"characters\": [\"…\"], \"offscreen\": [], \"lieu\": \"La clairière\", \"decor\": null, \"objets\": [],\n   \"importance\": 2, \"intensity\": \"normal\",\n   \"dialogues\": [{\"speaker\": \"…\", \"text\": \"…\", \"kind\": \"speech\"}, {\"speaker\": \"…\", \"text\": \"…\", \"kind\": \"shout\"}],\n   \"sfx\": [{\"text\": \"VROUM !\", \"intensity\": \"choc\"}]}]}],\n \"summary\": \"…\"}\n\n<contexte>\n$context_json\n</contexte>\n",
     "used": [
      "series_title",
      "style_packs",
      "reading_direction",
      "characters",
      "decors",
      "objets",
      "lieux",
      "previous_chapters",
      "bible",
      "savoir_faire",
      "chapter_number",
      "chapter_title",
      "synopsis",
      "style_guidelines",
      "scenes",
      "target_pages",
      "bubble_kinds",
      "intensities",
      "rythmes",
      "character_names",
      "pre_direction",
      "dialogue_rules",
      "context_json"
     ]
    },
    {
     "key": "retry",
     "line": 255,
     "text": "Ta réponse précédente est invalide :\n$error\nCorrige ces erreurs et renvoie l'objet JSON complet, et uniquement lui. Garde ce qui était juste :\npour les dialogues, ajoute, coupe ou retire des répliques sans réécrire le reste du découpage.\n",
     "used": [
      "error"
     ]
    }
   ]
  }
 },
 "imagePrompt": {
  "file": "presets/image_prompt.yaml",
  "parts": [
   {
    "line": 37,
    "text": "$style_lead.",
    "used": [
     "style_lead"
    ]
   },
   {
    "line": 38,
    "text": "$finition.",
    "used": [
     "finition"
    ]
   },
   {
    "line": 39,
    "text": "$plan.",
    "used": [
     "plan"
    ]
   },
   {
    "line": 40,
    "text": "$framing.",
    "used": [
     "framing"
    ]
   },
   {
    "line": 41,
    "text": "Camera angle: $angle.",
    "used": [
     "angle"
    ]
   },
   {
    "line": 42,
    "text": "$description.",
    "used": [
     "description"
    ]
   },
   {
    "line": 43,
    "text": "Action and pose: $action.",
    "used": [
     "action"
    ]
   },
   {
    "line": 44,
    "text": "Setting: $setting.",
    "used": [
     "setting"
    ]
   },
   {
    "line": 45,
    "text": "Staging: $staging.",
    "used": [
     "staging"
    ]
   },
   {
    "line": 46,
    "text": "Mood and lighting: $ambiance.",
    "used": [
     "ambiance"
    ]
   },
   {
    "line": 47,
    "text": "Recurring setting: $decor.",
    "used": [
     "decor"
    ]
   },
   {
    "line": 48,
    "text": "$character_count: $characters.",
    "used": [
     "character_count",
     "characters"
    ]
   },
   {
    "line": 49,
    "text": "Objects: $objects.",
    "used": [
     "objects"
    ]
   },
   {
    "line": 50,
    "text": "Series bible notes: $bible.",
    "used": [
     "bible"
    ]
   },
   {
    "line": 51,
    "text": "Style: $style.",
    "used": [
     "style"
    ]
   },
   {
    "line": 52,
    "text": "Style notes: $savoir_faire.",
    "used": [
     "savoir_faire"
    ]
   },
   {
    "line": 54,
    "text": "A single continuous scene in one panel, no text or speech bubbles in the image.",
    "used": []
   }
  ],
  "styleMaxChars": 240,
  "styleMaxCharsLine": 99,
  "lines": {
   "parts": 36,
   "character": 57,
   "style_lead": 91,
   "style_max_chars": 99,
   "strip_quotes": 103,
   "references": 112,
   "references.character": 114,
   "references.sorting": 124,
   "references.after": 136,
   "references.monochrome": 142,
   "monochrome_forbidden_terms": 163,
   "monochrome_writer_rule": 257,
   "mood_conflicts": 267,
   "camera_terms": 340,
   "tight_shots": 364,
   "mentions": 370,
   "single_instance": 380,
   "framing": 386,
   "forbidden_text_terms": 62,
   "negative_photo_terms": 67,
   "forbidden_photo_terms": 71
  }
 },
 "qcVision": {
  "file": "presets/qc.yaml",
  "line": 91,
  "text": "Tu es contrôleur qualité pour un studio de manga. Regarde cette case et dis si elle correspond\nà sa description.\nDescription de la case : $description\nPersonnages attendus : $characters\nType de plan : $shot\nVérifie : présence et nombre des personnages, action, cadrage, anatomie (mains, visages),\nabsence de tout texte ou lettre dessiné dans l'image.\nRéponds uniquement en JSON : {\"score\": <entier 0-100>, \"raisons\": [\"<raison courte en français>\", …]}.\n100 = parfaitement conforme ; moins de 40 = à refaire.\n",
  "used": [
   "description",
   "characters",
   "shot"
  ]
 },
 "trace": {
  "series": {
   "title": "La Lame du vent (série d'essai)",
   "genre": "shonen",
   "rendering": "nb-trames",
   "tone": "lumineux",
   "monochrome": true
  },
  "panel": {
   "description": "Aiko lève son sabre face à Ren sur le toit, le vent soulève son bandeau. « Je n'ai pas peur ! »",
   "shot_type": "contre-plongée",
   "setting": "toit d'un lycée au crépuscule, château d'eau, antennes, ville en contrebas",
   "staging": "Aiko au premier plan à gauche, sabre levé ; Ren à droite, en retrait, bras croisés",
   "plan": "gros plan",
   "angle": "en contre-plongée",
   "ambiance": "contre-jour orangé, vent violent",
   "action": "Aiko bondit en avant, sabre levé à deux mains, le poids sur la jambe avant"
  },
  "characters": [
   {
    "name": "Aiko",
    "details": "lycéenne, cheveux courts noirs, bandeau rouge, sabre de bois",
    "keywords": [
     "anime girl",
     "red headband"
    ]
   },
   {
    "name": "Ren",
    "details": "rival au regard froid, long manteau gris, cicatrice à la joue",
    "keywords": [
     "anime boy",
     "grey coat"
    ]
   }
  ],
  "factice": {
   "bible": "Aiko: always wears her mother's red headband",
   "savoir_faire": "Low-angle panels exaggerate the foreshortening of the raised arm"
  },
  "stored": "Black and white manga panel, hand-drawn inked line art with halftone screentone shading, shonen manga style. Close-up, the face fills the frame, shoulders cut by the frame edge. Camera angle: low-angle view looking up. Aiko lève son sabre face à Ren sur le toit, le vent soulève son bandeau. Action and pose: Aiko bondit en avant, sabre levé à deux mains, le poids sur la jambe avant. Setting: toit d'un lycée au crépuscule, château d'eau, antennes, ville en contrebas. Staging: Aiko au premier plan à gauche, sabre levé ; Ren à droite, en retrait, bras croisés. Mood and lighting: contre-jour orangé, vent violent. Two characters: Aiko (lycéenne, cheveux courts noirs, bandeau rouge, sabre de bois, anime girl, red headband); Ren (rival au regard froid, long manteau gris, cicatrice à la joue, anime boy, grey coat). Series bible notes: Aiko: always wears her mother's red headband. Style: shonen manga, dynamic energetic style, determined young hero, black and white manga, halftone screentone dots, regular grey dot pattern, no cross-hatching, bright joyful atmosphere, warm light, light screentone, subtly grey. Style notes: Low-angle panels exaggerate the foreshortening of the raised arm. A single continuous scene in one panel, no text or speech bubbles in the image.",
  "segments": [
   {
    "t": "Black and white manga panel, hand-drawn inked line art with halftone screentone shading, shonen manga style",
    "src": "style",
    "var": "style_lead"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 37
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Close-up, the face fills the frame, shoulders cut by the frame edge",
    "src": "da",
    "var": "plan"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 39
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Camera angle: ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 41
   },
   {
    "t": "low-angle view looking up",
    "src": "da",
    "var": "angle"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 41
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Aiko lève son sabre face à Ren sur le toit, le vent soulève son bandeau",
    "src": "script",
    "var": "description"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 42
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Action and pose: ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 43
   },
   {
    "t": "Aiko bondit en avant, sabre levé à deux mains, le poids sur la jambe avant",
    "src": "da",
    "var": "action"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 43
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Setting: ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 44
   },
   {
    "t": "toit d'un lycée au crépuscule, château d'eau, antennes, ville en contrebas",
    "src": "script",
    "var": "setting"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 44
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Staging: ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 45
   },
   {
    "t": "Aiko au premier plan à gauche, sabre levé ; Ren à droite, en retrait, bras croisés",
    "src": "script",
    "var": "staging"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 45
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Mood and lighting: ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 46
   },
   {
    "t": "contre-jour orangé, vent violent",
    "src": "da",
    "var": "ambiance"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 46
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Two characters",
    "src": "code",
    "var": "character_count"
   },
   {
    "t": ": ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 48
   },
   {
    "t": "Aiko (lycéenne, cheveux courts noirs, bandeau rouge, sabre de bois, anime girl, red headband); Ren (rival au regard froid, long manteau gris, cicatrice à la joue, anime boy, grey coat)",
    "src": "fiche",
    "var": "characters"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 48
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Series bible notes: ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 50
   },
   {
    "t": "Aiko: always wears her mother's red headband",
    "src": "bible",
    "var": "bible"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 50
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Style: ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 51
   },
   {
    "t": "shonen manga, dynamic energetic style, determined young hero, black and white manga, halftone screentone dots, regular grey dot pattern, no cross-hatching, bright joyful atmosphere, warm light, light screentone, subtly grey",
    "src": "style",
    "var": "style"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 51
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Style notes: ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 52
   },
   {
    "t": "Low-angle panels exaggerate the foreshortening of the raised arm",
    "src": "savoir",
    "var": "savoir_faire"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 52
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "A single continuous scene in one panel, no text or speech bubbles in the image.",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 54
   }
  ],
  "skipped": [
   {
    "part": "$finition.",
    "line": 38,
    "empty": [
     "finition"
    ]
   },
   {
    "part": "$framing.",
    "line": 40,
    "empty": [
     "framing"
    ]
   },
   {
    "part": "Recurring setting: $decor.",
    "line": 47,
    "empty": [
     "decor"
    ]
   },
   {
    "part": "Objects: $objects.",
    "line": 49,
    "empty": [
     "objects"
    ]
   }
  ],
  "sentSegments": [
   {
    "t": "<image1> is the identity reference for Aiko: keep the face, hair and outfit; ignore its pose, framing and background. ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 143
   },
   {
    "t": "<image2> is the identity reference for Ren: keep the face, hair and outfit; ignore its pose, framing and background.",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 143
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Black and white manga panel, hand-drawn inked line art with halftone screentone shading, shonen manga style",
    "src": "style",
    "var": "style_lead"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 37
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Close-up, the face fills the frame, shoulders cut by the frame edge",
    "src": "da",
    "var": "plan"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 39
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Camera angle: ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 41
   },
   {
    "t": "low-angle view looking up",
    "src": "da",
    "var": "angle"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 41
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Aiko lève son sabre face à Ren sur le toit, le vent soulève son bandeau",
    "src": "script",
    "var": "description"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 42
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Action and pose: ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 43
   },
   {
    "t": "Aiko bondit en avant, sabre levé à deux mains, le poids sur la jambe avant",
    "src": "da",
    "var": "action"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 43
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Setting: ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 44
   },
   {
    "t": "toit d'un lycée au crépuscule, château d'eau, antennes, ville en contrebas",
    "src": "script",
    "var": "setting"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 44
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Staging: ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 45
   },
   {
    "t": "Aiko au premier plan à gauche, sabre levé ; Ren à droite, en retrait, bras croisés",
    "src": "script",
    "var": "staging"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 45
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Mood and lighting: ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 46
   },
   {
    "t": "contre-jour ",
    "src": "da",
    "var": "ambiance"
   },
   {
    "t": "orangé",
    "src": "da",
    "var": "ambiance",
    "removed": true
   },
   {
    "t": ", vent violent",
    "src": "da",
    "var": "ambiance"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 46
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Two characters",
    "src": "code",
    "var": "character_count"
   },
   {
    "t": ": ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 48
   },
   {
    "t": "Aiko (lycéenne, cheveux courts noirs, bandeau ",
    "src": "fiche",
    "var": "characters"
   },
   {
    "t": "rouge",
    "src": "fiche",
    "var": "characters",
    "removed": true
   },
   {
    "t": ", sabre de bois, anime girl, ",
    "src": "fiche",
    "var": "characters"
   },
   {
    "t": "red",
    "src": "fiche",
    "var": "characters",
    "removed": true
   },
   {
    "t": " headband); Ren (rival au regard froid, long manteau gris, cicatrice à la joue, anime boy, grey coat)",
    "src": "fiche",
    "var": "characters"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 48
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Series bible notes: ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 50
   },
   {
    "t": "Aiko: always wears her mother's ",
    "src": "bible",
    "var": "bible"
   },
   {
    "t": "red",
    "src": "bible",
    "var": "bible",
    "removed": true
   },
   {
    "t": " headband",
    "src": "bible",
    "var": "bible"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 50
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Style: ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 51
   },
   {
    "t": "shonen manga, dynamic energetic style, determined young hero, black and white manga, halftone screentone dots, regular grey dot pattern, no cross-hatching, bright joyful atmosphere, warm light, light screentone, subtly grey",
    "src": "style",
    "var": "style"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 51
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "Style notes: ",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 52
   },
   {
    "t": "Low-angle panels exaggerate the foreshortening of the raised arm",
    "src": "savoir",
    "var": "savoir_faire"
   },
   {
    "t": ".",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 52
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "A single continuous scene in one panel, no text or speech bubbles in the image.",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 54
   },
   {
    "t": " ",
    "src": "sep"
   },
   {
    "t": "From <image1> take only the face, hair, body and outfit of Aiko; ignore its layout, pose grid, rules, labels and white background. From <image2> take only the face, hair, body and outfit of Ren; ignore its layout, pose grid, rules, labels and white background.",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 124
   },
   {
    "t": " Use the reference images for identity and design only (face, hair, body shape, outfit, materials): draw a new scene with new poses, a new camera angle and the whole background described above, everything (extras and places included) drawn in the same manga style as the reference images. Exactly one continuous scene in a single panel: not a character sheet, not a turnaround, not a collage, no side-by-side views, no multiple poses, no plain white background.",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 151
   },
   {
    "t": " Each character appears only once in the panel, no duplicate or twin of the same character.",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 380
   },
   {
    "t": " White paper dominant, clean line art, screentone only in the shadows, large white areas, no muddy grey fill.",
    "src": "style",
    "var": "tonality",
    "file": "presets/style_renderings/nb-trames.yaml"
   }
  ],
  "sent": "<image1> is the identity reference for Aiko: keep the face, hair and outfit; ignore its pose, framing and background. <image2> is the identity reference for Ren: keep the face, hair and outfit; ignore its pose, framing and background. Black and white manga panel, hand-drawn inked line art with halftone screentone shading, shonen manga style. Close-up, the face fills the frame, shoulders cut by the frame edge. Camera angle: low-angle view looking up. Aiko lève son sabre face à Ren sur le toit, le vent soulève son bandeau. Action and pose: Aiko bondit en avant, sabre levé à deux mains, le poids sur la jambe avant. Setting: toit d'un lycée au crépuscule, château d'eau, antennes, ville en contrebas. Staging: Aiko au premier plan à gauche, sabre levé ; Ren à droite, en retrait, bras croisés. Mood and lighting: contre-jour, vent violent. Two characters: Aiko (lycéenne, cheveux courts noirs, bandeau, sabre de bois, anime girl, headband); Ren (rival au regard froid, long manteau gris, cicatrice à la joue, anime boy, grey coat). Series bible notes: Aiko: always wears her mother's headband. Style: shonen manga, dynamic energetic style, determined young hero, black and white manga, halftone screentone dots, regular grey dot pattern, no cross-hatching, bright joyful atmosphere, warm light, light screentone, subtly grey. Style notes: Low-angle panels exaggerate the foreshortening of the raised arm. A single continuous scene in one panel, no text or speech bubbles in the image. From <image1> take only the face, hair, body and outfit of Aiko; ignore its layout, pose grid, rules, labels and white background. From <image2> take only the face, hair, body and outfit of Ren; ignore its layout, pose grid, rules, labels and white background. Use the reference images for identity and design only (face, hair, body shape, outfit, materials): draw a new scene with new poses, a new camera angle and the whole background described above, everything (extras and places included) drawn in the same manga style as the reference images. Exactly one continuous scene in a single panel: not a character sheet, not a turnaround, not a collage, no side-by-side views, no multiple poses, no plain white background. Each character appears only once in the panel, no duplicate or twin of the same character. White paper dominant, clean line art, screentone only in the shadows, large white areas, no muddy grey fill.",
  "negative": [
   {
    "t": "text",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "letters",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "speech bubble",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "caption",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "watermark",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "signature",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "multiple panels",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "comic page layout",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "collage",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "split screen",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "character sheet",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "turnaround",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "model sheet",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "white background",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "duplicate character",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "extra people",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "extra limbs",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "deformed hands",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "blurry",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "low quality",
    "src": "workflow",
    "file": "presets/workflows/qwen-image-edit-ref-qualite.yaml"
   },
   {
    "t": "onomatopoeia",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 62
   },
   {
    "t": "photorealistic",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 67
   },
   {
    "t": "photograph",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 67
   },
   {
    "t": "photo",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 67
   },
   {
    "t": "3d render",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 67
   },
   {
    "t": "cgi",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 67
   },
   {
    "t": "realistic skin texture",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 67
   },
   {
    "t": "film grain",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 67
   },
   {
    "t": "full body",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 364
   },
   {
    "t": "full-length",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 364
   },
   {
    "t": "feet visible",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 364
   },
   {
    "t": "standing pose facing viewer",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 364
   },
   {
    "t": "color",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 254
   },
   {
    "t": "colored",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 254
   },
   {
    "t": "colorful",
    "src": "preset",
    "file": "presets/image_prompt.yaml",
    "line": 254
   },
   {
    "t": "dark muddy image",
    "src": "style",
    "file": "presets/style_renderings/nb-trames.yaml"
   },
   {
    "t": "grey overall",
    "src": "style",
    "file": "presets/style_renderings/nb-trames.yaml"
   },
   {
    "t": "heavy black fill",
    "src": "style",
    "file": "presets/style_renderings/nb-trames.yaml"
   },
   {
    "t": "underexposed",
    "src": "style",
    "file": "presets/style_renderings/nb-trames.yaml"
   }
  ],
  "negativeWorkflow": "qwen-image-edit-ref-qualite",
  "flux": {
   "prompt": "<image1> is the identity reference for Aiko <obj_1>: keep the face, hair and outfit; ignore its pose, framing and background. <image2> is the identity reference for Ren <obj_2>: keep the face, hair and outfit; ignore its pose, framing and background. Black and white manga panel, hand-drawn inked line art with halftone screentone shading, shonen manga style. Close-up, the face fills the frame, shoulders cut by the frame edge. Camera angle: low-angle view looking up. Aiko lève son sabre face à Ren sur le toit, le vent soulève son bandeau. Action and pose: Aiko bondit en avant, sabre levé à deux mains, le poids sur la jambe avant. Setting: toit d'un lycée au crépuscule, château d'eau, antennes, ville en contrebas. Staging: Aiko au premier plan à gauche, sabre levé ; Ren à droite, en retrait, bras croisés. Mood and lighting: contre-jour, vent violent. Two characters: Aiko (lycéenne, cheveux courts noirs, bandeau, sabre de bois, anime girl, headband); Ren (rival au regard froid, long manteau gris, cicatrice à la joue, anime boy, grey coat). Series bible notes: Aiko: always wears her mother's headband. Style: shonen manga, dynamic energetic style, determined young hero, black and white manga, halftone screentone dots, regular grey dot pattern, no cross-hatching, bright joyful atmosphere, warm light, light screentone, subtly grey. Style notes: Low-angle panels exaggerate the foreshortening of the raised arm. A single continuous scene in one panel, no text or speech bubbles in the image. From <image1> take only the face, hair, body and outfit of Aiko; ignore its layout, pose grid, rules, labels and white background. From <image2> take only the face, hair, body and outfit of Ren; ignore its layout, pose grid, rules, labels and white background. Use the reference images for identity and design only (face, hair, body shape, outfit, materials): draw a new scene with new poses, a new camera angle and the whole background described above, everything (extras and places included) drawn in the same manga style as the reference images. Exactly one continuous scene in a single panel: not a character sheet, not a turnaround, not a collage, no side-by-side views, no multiple poses, no plain white background. Each character appears only once in the panel, no duplicate or twin of the same character. White paper dominant, clean line art, screentone only in the shadows, large white areas, no muddy grey fill.",
   "boxes": [
    {
     "name": "Aiko",
     "x": 0.0,
     "y": 0.08,
     "w": 0.6,
     "h": 0.92,
     "desc": "Aiko, anime girl, red headband",
     "source": "mise en scène",
     "place": {
      "column": "left",
      "depth": "front"
     }
    },
    {
     "name": "Ren",
     "x": 0.4,
     "y": 0.1,
     "w": 0.6,
     "h": 0.88,
     "desc": "Ren, anime boy, grey coat",
     "source": "mise en scène",
     "place": {
      "column": "right"
     }
    }
   ]
  },
  "writerUser": "Panel to describe (French inputs, to translate):\n- shot size (French): gros plan\n- camera angle (French): en contre-plongée\n- framing terms: close-up, the face fills the frame, shoulders cut by the frame edge, low-angle view looking up\n- body action or pose chosen by the art direction: Aiko bondit en avant, sabre levé à deux mains, le poids sur la jambe avant\n- description: Aiko lève son sabre face à Ren sur le toit, le vent soulève son bandeau\n- setting: toit d'un lycée au crépuscule, château d'eau, antennes, ville en contrebas\n- staging (who does what, where in the frame): Aiko au premier plan à gauche, sabre levé ; Ren à droite, en retrait, bras croisés\n- mood and lighting: contre-jour, vent violent\n\nCharacters of the panel (name them all, exactly as written):\n- Aiko: lycéenne, cheveux courts noirs, bandeau, sabre de bois, anime girl, headband\n- Ren: rival au regard froid, long manteau gris, cicatrice à la joue, anime boy, grey coat\n\nAbsent characters (never name nor draw them): (none)\n\nFraming rule: (ordinary panel: the characters listed above are in the frame)\n\nRecurring setting: (none)\nRecurring objects: (none)\n\nReference images sent to the model with this prompt (the studio writes these role sentences in front of\nyour paragraph: never write them yourself):\n- <image1> is the identity reference for Aiko: keep the face, hair and outfit; ignore its pose, framing and background.\n- <image2> is the identity reference for Ren: keep the face, hair and outfit; ignore its pose, framing and background.\n\nSeries bible notes (to respect):\nAiko: always wears her mother's red headband\n\nTeam know-how (apply it without quoting it):\nLow-angle panels exaggerate the foreshortening of the raised arm\nThese notes are guidance, not a format: they mention fields you do not have (narrative_role, variation_reason, panel_weight…); answer only in the requested format.\n\nStyle sentence of the series (open the paragraph with it, exactly as written): Black and white manga panel, hand-drawn inked line art with halftone screentone shading, shonen manga style.\nStyle keywords of the series (copy them exactly at the end of the paragraph): shonen manga, dynamic energetic style, determined young hero, black and white manga, halftone screentone dots, regular grey dot pattern, no cross-hatching, bright joyful atmosphere, warm light, light screentone, subtly grey\n\nAnswer format:\n{\"prompt\": \"the paragraph\", \"language\": \"en\", \"notes\": \"one optional sentence for the author, or null\"}",
  "style": {
   "value": "shonen manga, dynamic energetic style, determined young hero, black and white manga, halftone screentone dots, regular grey dot pattern, no cross-hatching, bright joyful atmosphere, warm light, light screentone, subtly grey",
   "length": 223,
   "cap": 240,
   "cut": []
  }
 },
 "styleCuts": {
  "total": 108,
  "truncated": 4,
  "worst": {
   "genre": "franco-belge",
   "rendering": "nb-trames",
   "tone": "dark",
   "cut": [
    "classic Franco-Belgian comic style"
   ],
   "length": 237
  },
  "maxCut": 1
 }
};
