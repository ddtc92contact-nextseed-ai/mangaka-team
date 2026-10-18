/*
 * Goulots et faiblesses : la vue structurelle, relevée dans le code.
 * Chaque citation `src` donne un fichier (relatif à la racine du dépôt), une ligne et un extrait `x` que
 * `mangaka-tuto/verifier.py` retrouve à cette ligne (ou dans les 3 suivantes) : une citation périmée se voit.
 * Les chiffres ne viennent jamais d'ici : ils viennent de data/mesures.js (mesurer.py). Une faiblesse sans
 * mesure possible dans la base porte `mesure: null` et s'affiche « à mesurer ».
 */
window.GOULOTS = {
  // Étape de job (table jobs) → étape de la carte (TUTO.steps). `generation` couvre croquis, passage au propre et
  // réparations : le journal des générations (generation_logs.kind) les sépare.
  jobToStep: {
    scenes: "scenes",
    script: "scenario",
    art_direction: "direction",
    generation: "generation",
    control_map: "generation",
    qc: "qc",
    qc_bench: "qc",
    finishing: "finition",
    export: "export",
    reference: "bibliotheque",
    style_board: "bibliotheque",
    cover: "couvertures",
    cover_export: "couvertures",
  },
  // Sorte du journal → étape de la carte, pour les étapes que la table jobs ne distingue pas.
  logKindToStep: { croquis: "croquis", inpaint: "reparation" },
  jobLabels: {
    scenes: "Scènes",
    script: "Scénario",
    art_direction: "Direction artistique",
    generation: "Génération des cases",
    control_map: "Carte de contrôle",
    qc: "Contrôle qualité",
    qc_bench: "Banc d'essai QC",
    comfyui_trial: "Case d'essai ComfyUI",
    finishing: "Finition d'impression",
    export: "Export du chapitre",
    reference: "Fiches de référence",
    style_board: "Planche de style",
    cover: "Couverture de tome",
    cover_export: "Export de la couverture",
  },
  logKindLabels: {
    panel: "Case",
    croquis: "Croquis",
    from_sketch: "Passage au propre",
    inpaint: "Réparation",
    angle: "Changer l'angle",
    reference_sheet: "Fiche de référence",
    style_trial: "Essai de style",
    style_reference: "Référence de style",
  },

  // ------------------------------------------------------------------ vue structurelle
  structure: [
    {
      id: "serialisation",
      title: "Points de sérialisation",
      intro: "Ce qui oblige des travaux indépendants à passer l'un après l'autre.",
      items: [
        {
          title: "Une seule file ComfyUI pour neuf étapes",
          text: "Toutes les images (cases, croquis, propre, réparations, fiches, planche de style, couvertures, finition) **et** le contrôle qualité passent par un seul thread, un job à la fois, le plus ancien d'abord. Deux chapitres qui génèrent en même temps s'attendent ; une couverture lancée pendant un chapitre attend toutes ses cases.",
          src: [
            { f: "engine/mangaka_engine/pipeline/queue.py", l: 58, x: "class SerialJobQueue" },
            { f: "engine/mangaka_engine/pipeline/queue.py", l: 98, x: "threading.Thread(target=self._loop" },
            { f: "engine/mangaka_engine/main.py", l: 162, x: "queue = SerialJobQueue(" },
          ],
        },
        {
          title: "Le pool LLM est limité à 4 jobs",
          text: "Scènes, scénario, direction artistique, export et export de couverture partagent 4 threads. Un cinquième job reste « en attente » sans rien dire.",
          src: [{ f: "engine/mangaka_engine/pipeline/jobs.py", l: 51, x: "max_workers: int = 4" }],
        },
        {
          title: "Le QC attend la fin des générations",
          text: "Le contrôle qualité est sur le même thread que la génération (jamais de vision pendant ComfyUI). Chaque QC part donc derrière toutes les générations déjà en file : sur un lot de cases, les verdicts arrivent à la fin. La couche vision attend en plus que ComfyUI soit vide, jusqu'à 10 minutes, puis renonce (« ComfyUI occupé »).",
          src: [
            { f: "engine/mangaka_engine/main.py", l: 170, x: "Le contrôle qualité partage le worker de la génération" },
            { f: "engine/mangaka_engine/pipeline/qc.py", l: 682, x: "def wait_comfy_idle" },
            { f: "engine/mangaka_engine/pipeline/qc.py", l: 922, x: "wait_comfy_idle(cfg.vision.wait_idle_s" },
            { f: "presets/qc.yaml", l: 87, x: "wait_idle_s: 600" },
          ],
        },
        {
          title: "Recharger les flux est refusé pendant une génération",
          text: "« Recharger les flux » (Réglages) répond 409 tant qu'un job de la file ComfyUI tourne. Sur un long lot, corriger un flux oblige à attendre la file vide ou à redémarrer le moteur.",
          src: [
            { f: "engine/mangaka_engine/api/deps.py", l: 67, x: "running = self.generation.current_job_id" },
            { f: "engine/mangaka_engine/api/system.py", l: 253, x: "recharge les flux quand la file est vide" },
          ],
        },
      ],
    },
    {
      id: "portes",
      title: "Portes manuelles",
      intro: "Ce qui attend une décision de l'auteur avant de continuer. Ce temps humain est voulu, mais il pèse sur la durée d'un chapitre.",
      items: [
        {
          title: "La name se valide page par page",
          text: "Avec le palier croquis, générer et passer au propre exigent que chaque page ait sa name validée. Toute retouche d'une case (description, plan, découpe, croquis) rend la validation caduque.",
          src: [
            { f: "engine/mangaka_engine/pipeline/name_board.py", l: 72, x: "def validate_page_name" },
            { f: "engine/mangaka_engine/pipeline/stage_gate.py", l: 173, x: 'ActionDef("generation", "générer"' },
            { f: "engine/mangaka_engine/pipeline/stage_gate.py", l: 373, x: 'elif key == "name":' },
          ],
        },
        {
          title: "Pas de passage au propre sans croquis retenu",
          text: "Chaque case doit avoir un croquis validé au tri avant son propre ; sinon le job refuse.",
          src: [{ f: "engine/mangaka_engine/pipeline/sketch.py", l: 186, x: "aucun croquis validé" }],
        },
        {
          title: "La garde d'étapes enchaîne six étapes avant de générer",
          text: "Générer exige scénario, direction, mise en page, références, prompts et name. Lettrer exige toutes les cases approuvées ; exporter exige en plus le lettrage. L'auteur peut passer outre une étape à la fois.",
          src: [{ f: "engine/mangaka_engine/pipeline/stage_gate.py", l: 168, x: "ACTIONS: dict[str, ActionDef]" }],
        },
      ],
    },
    {
      id: "llm",
      title: "Tentatives LLM et délais des fournisseurs",
      intro: "Combien de fois on réessaie, et combien de temps on attend avant d'abandonner.",
      items: [
        {
          title: "Trois essais au plus pour les agents d'écriture, puis erreur",
          text: "Le nombre de relances est plafonné à 2 (donc 3 essais) ; scénario, scènes et direction artistique sont réglés au maximum. Le rédacteur de prompt image est à 1 relance (2 essais), puis il se replie sur des fragments sans bloquer la génération.",
          src: [
            { f: "engine/mangaka_engine/presets/schemas.py", l: 2092, x: "max_retries: int = Field(default=2, ge=0, le=2)" },
            { f: "engine/mangaka_engine/pipeline/script.py", l: 587, x: "total = 1 + prompt.max_retries" },
            { f: "engine/mangaka_engine/pipeline/script.py", l: 599, x: "Le LLM n'a pas pu répondre" },
            { f: "presets/prompts/redacteur-image.yaml", l: 61, x: "max_retries: 1" },
          ],
        },
        {
          title: "DeepSeek : jusqu'à 5 min par appel (15 min en raisonnement)",
          text: "Un appel au modèle rapide peut attendre 300 s ; les modèles qui raisonnent, 900 s. Avec 3 essais, un découpage en échec peut occuper un thread du pool 15 à 45 minutes.",
          src: [
            { f: "presets/providers.yaml", l: 6, x: "timeout_s: 300" },
            { f: "presets/providers.yaml", l: 25, x: "timeout_s: 900" },
          ],
        },
        {
          title: "ComfyUI : 10 min par génération, puis abandon",
          text: "Au-delà du `timeout_s` du flux (600 s par défaut), le moteur interrompt ComfyUI et le job échoue. Chaque requête HTTP vers ComfyUI a 5 s.",
          src: [
            { f: "engine/mangaka_engine/presets/schemas.py", l: 375, x: "timeout_s: float = Field(default=600" },
            { f: "engine/mangaka_engine/pipeline/generation.py", l: 2313, x: "n'a pas terminé la génération en" },
            { f: "engine/mangaka_engine/config.py", l: 49, x: "comfyui_timeout_s: float = 5.0" },
          ],
        },
        {
          title: "Ollama (vision) : 2 min par appel",
          text: "La couche vision attend 120 s, réessaie une fois une réponse invalide, puis passe en erreur (la case est envoyée « à revoir »).",
          src: [
            { f: "presets/providers.yaml", l: 58, x: "timeout_s: 120" },
            { f: "presets/qc.yaml", l: 86, x: "max_retries: 1" },
          ],
        },
      ],
    },
    {
      id: "interruption",
      title: "Étapes non interruptibles",
      intro: "Ce qu'on ne peut pas arrêter une fois parti.",
      items: [
        {
          title: "Un job LLM lancé va jusqu'au bout",
          text: "Le pool n'annule qu'un job pas encore démarré. Un découpage, des scènes, une direction artistique ou un export en cours ne s'arrêtent pas : l'API répond 409.",
          src: [
            { f: "engine/mangaka_engine/pipeline/jobs.py", l: 96, x: "False s'il tourne déjà (non interruptible)" },
            { f: "engine/mangaka_engine/api/jobs.py", l: 111, x: "ne peut pas être interrompu" },
          ],
        },
        {
          title: "Le QC s'arrête entre deux images, pas pendant la vision",
          text: "Le contrôle qualité n'a pas de fonction d'interruption : il vérifie l'annulation entre deux images et pendant l'attente de ComfyUI, mais un appel à la vision déjà parti va jusqu'à son délai.",
          src: [{ f: "engine/mangaka_engine/main.py", l: 171, x: "queue.add_step(QC_STEP" }],
        },
      ],
    },
    {
      id: "redemarrage",
      title: "Redémarrage du moteur",
      intro: "Ce qui se perd quand le moteur s'arrête.",
      items: [
        {
          title: "Tout job en attente ou en cours passe en échec",
          text: "Au démarrage, le moteur marque en échec les jobs `pending` **et** `running` (« Interrompu par un redémarrage du moteur »). Rien n'est remis en file : un lot de 40 cases interrompu à la 5e est à relancer à la main.",
          src: [
            { f: "engine/mangaka_engine/pipeline/jobs.py", l: 56, x: "def recover(self) -> int:" },
            { f: "engine/mangaka_engine/pipeline/jobs.py", l: 62, x: "Interrompu par un redémarrage du moteur" },
            { f: "engine/mangaka_engine/main.py", l: 102, x: "interrupted = runner.recover()" },
          ],
        },
      ],
    },
    {
      id: "dependances",
      title: "Dépendances externes",
      intro: "Trois services hors du moteur. Aucun repli automatique sur le mode factice : un fournisseur mal configuré reste indisponible.",
      items: [
        {
          title: "DeepSeek tombe",
          text: "Scènes, scénario et direction artistique répondent 503 « LLM indisponible » ou échouent après leurs essais. La génération continue : le prompt image se replie sur des fragments.",
          src: [
            { f: "engine/mangaka_engine/api/chapters.py", l: 465, x: "LLM indisponible" },
            { f: "engine/mangaka_engine/pipeline/generation.py", l: 1245, x: "une panne du rédacteur ne bloque pas la génération" },
          ],
        },
        {
          title: "ComfyUI tombe",
          text: "Plus aucune image : 503 « ComfyUI indisponible » à la demande, ou jobs en échec « ComfyUI ne répond pas / hors ligne ». Toute la file s'arrête, QC compris.",
          src: [
            { f: "engine/mangaka_engine/api/generation.py", l: 436, x: "ComfyUI indisponible" },
            { f: "engine/mangaka_engine/providers/comfyui/http.py", l: 89, x: "ComfyUI ne répond pas" },
          ],
        },
        {
          title: "Ollama tombe",
          text: "La couche vision passe en erreur et la case part « à revoir » : le QC ne bloque pas, mais il renvoie plus de travail à l'auteur. Sans aucune couche disponible, le job QC échoue.",
          src: [
            { f: "engine/mangaka_engine/providers/vision/__init__.py", l: 106, x: "lance « ollama serve »" },
            { f: "engine/mangaka_engine/pipeline/qc.py", l: 943, x: '"error",' },
            { f: "engine/mangaka_engine/pipeline/qc.py", l: 720, x: "aucune couche de contrôle disponible" },
          ],
        },
        {
          title: "Pas de repli automatique",
          text: "Une erreur de configuration laisse le fournisseur à vide et note la raison ; le moteur démarre quand même. Le mode factice n'est le défaut que si la variable n'est pas réglée.",
          src: [{ f: "engine/mangaka_engine/providers/factory.py", l: 180, x: "une erreur de configuration n'empêche pas le démarrage" }],
        },
      ],
    },
  ],

  // ------------------------------------------------------------------ faiblesses classées
  // impact : 3 = fort, 2 = moyen, 1 = faible (jugement sur le code, pas une mesure).
  // mesure : clé lue dans data/mesures.js (voir goulots.js : MESURES_FAIBLESSES), ou null = « à mesurer ».
  faiblesses: [
    {
      id: "file-unique",
      title: "File ComfyUI unique : les images et le QC s'attendent",
      impact: 3,
      mesure: "attente_comfy",
      cause: "Un seul thread pour neuf étapes de job.",
      src: [{ f: "engine/mangaka_engine/pipeline/queue.py", l: 58, x: "class SerialJobQueue" }],
      piste: "Prioriser la file (une case demandée par l'auteur avant un lot) ou sortir le QC sans vision de la file.",
    },
    {
      id: "qc-tardif",
      title: "Le verdict QC arrive après tout le lot",
      impact: 2,
      mesure: "attente_qc",
      cause: "Le QC partage le thread de la génération et passe derrière les générations déjà en file.",
      src: [{ f: "engine/mangaka_engine/main.py", l: 170, x: "Le contrôle qualité partage le worker de la génération" }],
      piste: "Faire passer les détecteurs (CPU) hors de la file, et garder seulement la vision derrière ComfyUI.",
    },
    {
      id: "redemarrage",
      title: "Un redémarrage perd tout le travail en file",
      impact: 3,
      mesure: "interrompus_redemarrage",
      cause: "`recover()` passe en échec les jobs en attente comme ceux en cours.",
      src: [{ f: "engine/mangaka_engine/pipeline/jobs.py", l: 62, x: "Interrompu par un redémarrage du moteur" }],
      piste: "Remettre en file les jobs `pending` au démarrage au lieu de les marquer en échec.",
    },
    {
      id: "regenerations",
      title: "Beaucoup de régénérations par case",
      impact: 2,
      mesure: "regenerations",
      cause: "Chaque version de case est une génération complète au palier choisi.",
      src: [{ f: "engine/mangaka_engine/store/models.py", l: 692, x: "class PanelImage(Base):" }],
      piste: "Regarder quelle couche du QC ou quel défaut déclenche les relances, avant de toucher aux prompts.",
    },
    {
      id: "vision-sautee",
      title: "La vision renonce quand ComfyUI est occupé",
      impact: 2,
      mesure: "vision_sautee",
      cause: "Attente de 600 s au plus que ComfyUI se vide, puis couche sautée.",
      src: [{ f: "engine/mangaka_engine/pipeline/qc.py", l: 924, x: "ComfyUI occupé" }],
      piste: "Relancer la vision plus tard plutôt que la sauter, ou la planifier en fin de lot.",
    },
    {
      id: "delai-comfy",
      title: "Générations abandonnées au délai de 10 min",
      impact: 2,
      mesure: "comfy_delai",
      cause: "`timeout_s` du flux, 600 s par défaut.",
      src: [{ f: "engine/mangaka_engine/presets/schemas.py", l: 375, x: "timeout_s: float = Field(default=600" }],
      piste: "Comparer ce délai au p90 mesuré de la génération et l'ajuster par palier.",
    },
    {
      id: "llm-echecs",
      title: "Échecs des agents d'écriture après leurs essais",
      impact: 2,
      mesure: "llm_echecs",
      cause: "3 essais au plus, puis erreur ; jusqu'à 300 s par appel.",
      src: [{ f: "engine/mangaka_engine/pipeline/script.py", l: 599, x: "Le LLM n'a pas pu répondre" }],
      piste: "Distinguer dans l'erreur délai, réponse invalide et panne, pour savoir quoi corriger.",
    },
    {
      id: "llm-non-interruptible",
      title: "Un job LLM lancé ne s'arrête pas",
      impact: 1,
      mesure: null,
      cause: "Le pool n'annule que les jobs pas encore démarrés.",
      src: [{ f: "engine/mangaka_engine/pipeline/jobs.py", l: 96, x: "non interruptible" }],
      piste: "Passer un drapeau d'annulation aux agents, vérifié entre deux essais.",
    },
    {
      id: "rechargement",
      title: "Recharger les flux bloqué pendant une génération",
      impact: 1,
      mesure: null,
      cause: "409 tant qu'un job de la file ComfyUI tourne.",
      src: [{ f: "engine/mangaka_engine/api/deps.py", l: 67, x: "running = self.generation.current_job_id" }],
      piste: "Recharger entre deux jobs de la file au lieu de refuser.",
    },
    {
      id: "pool-4",
      title: "Pool LLM de 4 : un 5e job attend en silence",
      impact: 1,
      mesure: "attente_pool",
      cause: "`ThreadPoolExecutor` de 4 threads.",
      src: [{ f: "engine/mangaka_engine/pipeline/jobs.py", l: 51, x: "max_workers: int = 4" }],
      piste: "Afficher la place dans la file du pool, comme pour la file ComfyUI.",
    },
    {
      id: "temps-humain",
      title: "Le temps humain entre deux étapes",
      impact: 2,
      mesure: "temps_humain",
      cause: "Portes manuelles : scènes, name page par page, croquis retenus, choix des versions, lettrage.",
      src: [{ f: "engine/mangaka_engine/pipeline/stage_gate.py", l: 168, x: "ACTIONS: dict[str, ActionDef]" }],
      piste: "Repérer la porte la plus longue (tableau par chapitre) avant de vouloir l'automatiser.",
    },
  ],
};
