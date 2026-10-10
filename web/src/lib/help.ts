// Textes des bulles d'aide (« ? ») de l'atelier, rangés par écran. Une ou deux phrases : ce que ça fait, et quand
// s'en servir. À reformuler ici librement : les écrans n'y font référence que par leur clé.

export const HELP = {
  // --- série (création / modification) -------------------------------------------------------------------------
  "serie.genre":
    "Le genre de la série (shōnen, seinen, franco-belge…) : il ajoute ses mots-clés de style à chaque image et pré-remplit la mise en page, le sens de lecture et les polices, que tu peux changer ensuite.",
  "serie.rendering":
    "Le rendu des images : N&B encre pure, N&B à trames, couleur douce ou cel-shading. Il s'applique à toutes les cases de la série ; les réglages de trames n'apparaissent qu'en noir et blanc.",
  "serie.tone":
    "L'ambiance visuelle (lumineuse, sombre, humour…) ajoutée au style de chaque case. Certains tons ne sont pas proposés pour tous les genres.",
  "serie.option.trait":
    "L'épaisseur du trait d'encrage, de fin à épais. Laisse « Par défaut » pour garder celle du genre.",
  "serie.option.trames":
    "La densité des trames grises du noir et blanc : légères pour un rendu aéré, denses pour un rendu sombre. Masqué pour un rendu couleur.",
  "serie.option.detail":
    "Le niveau de détail des arrière-plans : simple pour faire ressortir les personnages, riche pour les planches d'ambiance.",
  "serie.lora":
    "Un LoRA est un petit modèle qui impose un style appris (trait, encrage) à toutes les cases de la série. Optionnel : sans lui, seuls les mots du style guident l'image.",
  "serie.lora_weight":
    "La force du LoRA de style : vers 0,6 il se fait discret, au-delà de 1 il peut déformer les images. Le poids conseillé du catalogue est repris quand tu le choisis.",
  "serie.direction":
    "Manga : on lit de droite à gauche ; BD : de gauche à droite. Le sens décide de l'ordre des cases, de la reliure et de la place des bulles ; le changer recalcule les pages déjà mises en page.",
  "serie.layout_style":
    "La façon de découper les pages : sage (découpes droites, grille régulière), dynamique (des découpes en biais sur la plupart des pages, par défaut) ou nerveuse (biais fréquents et raides, tailles contrastées). Il s'applique aux pages à leur mise en page ; après un changement, « Remettre en page » recalcule les pages pas encore générées.",
  "serie.fonts":
    "Les polices du lettrage, pré-remplies par le genre. Celle des cris sert aux bulles « cri » ; chaque bulle peut encore changer de police au lettrage.",
  "serie.page_format":
    "La taille des pages à l'impression (B4 manga, A4…) en 300 dpi. Il fixe le ratio de la mise en page et la résolution visée à l'export.",
  "serie.tier":
    "Rapide (par défaut) est recommandé pour la qualité : 25 pas, ~1 min par case, des cases plus fidèles à la scène et aux références. Turbo génère plus vite (~35 s) pour avancer en volume. Qualité est plus lent mais plus fin : régénère en Qualité les cases importantes depuis l'atelier. Les croquis restent au palier rapide du croquis.",
  "serie.ai_prompt":
    "Oui : le LLM du dessinateur rédige le prompt image de chaque case en un vrai paragraphe (sujet, action, cadrage, décor, lumière, style), comme l'attend Qwen-Image. Il est écrit une fois par case, visible et modifiable dans l'atelier. Non : l'assemblage par fragments, sans LLM. Consignes, langue et longueur : écran « L'équipe », Dessinateur.",
  "serie.sketch":
    "Avec le palier croquis, chaque case est d'abord esquissée en quelques secondes : tu tries les compositions au clavier, puis seules celles validées passent au propre. Pratique pour ne pas gaspiller de longues générations.",
  "serie.sketch_denoise":
    "La part du croquis redessinée au passage au propre : bas (0,3) pour garder fidèlement la composition, haut (0,7) pour laisser plus de détails neufs. Vide : la valeur du preset.",
  "serie.clean_mode":
    "Comment le croquis validé devient l'image propre : redessiné en partie (image → image), ou verrouillé par ControlNet qui impose cadrage et poses du croquis.",
  "serie.clean_control":
    "Ce que ControlNet garde du croquis : le trait, la profondeur, les poses ou les grandes lignes. Le trait est le plus fidèle à la composition ; laisse « Par défaut » si tu hésites.",
  "serie.upscaler":
    "Le modèle qui agrandit chaque case jusqu'au dpi d'impression avant l'assemblage de la page (« Finaliser la page »). Les modèles marqués « lent » sont plus fidèles.",
  "serie.bible":
    "Univers, ton, règles et notes de personnages transmis à tous les agents de cette série (scénariste, prompts image) pour garder la cohérence d'un chapitre à l'autre.",
  "chapitre_infos.target_pages":
    "Le nombre de pages que le scénariste vise au découpage. Ce n'est pas une limite stricte : tu peux ajouter ou retirer des pages ensuite.",
  "chapitre_infos.status":
    "Où en est le chapitre. En passant à « Prêt » ou « Publié », son résumé rejoint la bible de la série pour les chapitres suivants.",
  "chapitre_infos.planned_date":
    "La date de sortie prévue : le tableau de bord affiche les chapitres à sortir dans les 7 prochains jours.",
  "chapitre_infos.summary":
    "Résumé écrit par le LLM au découpage. Les chapitres suivants le relisent pour garder la continuité de l'histoire.",
  "chapitre_infos.generate_all":
    "Met en file tout le chapitre en un clic : les pages sans mise en page sont mises en page d'abord, puis chaque case sans version choisie des pages de l'histoire et bonus part en génération (en croquis d'abord si le palier croquis est activé). Une génération à la fois ; une confirmation montre le nombre de cases et la durée estimée.",

  // --- planche de style ------------------------------------------------------------------------------------------
  "style_board.trials":
    "Quatre croquis rapides de la même scène test du genre, chacun avec une graine différente, pour voir le style de la série avant de produire. Choisis celui qui te plaît, ou relance une nouvelle série d'essais.",
  "style_board.reference":
    "L'essai retenu passe au propre et devient la référence de style : il est joint à chaque fiche de référence (personnages, objets, décors) et aux cases quand il reste une place, pour que tout garde le même style.",
  "style_board.keys":
    "Raccourcis clavier : tape 1 à 4 pour choisir l'essai correspondant, R pour relancer une série d'essais. Ils sont ignorés pendant une génération ou quand tu tapes dans un champ.",

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
  "scenario.setting":
    "Où et quand se passe la case : lieu, moment (heure, météo) et éléments visibles du décor. Il devient « Lieu : … » dans le prompt image, même sans décor récurrent : sans lui, le modèle dessine souvent un fond blanc.",
  "scenario.staging":
    "Qui fait quoi et où dans le cadre : premier plan, arrière-plan, gauche, droite, regards et gestes entre personnages. Il devient « Mise en scène : … » dans le prompt image.",
  "scenario.characters":
    "Tous les personnages visibles dans la case, séparés par des virgules. Chaque nom est rapproché d'une fiche (majuscules, accents et alias ignorés, « Urus le dragon » → Urus) : ses références, sa description et son LoRA servent à la génération.",
  "scenario.unmatched":
    "Ces noms ne correspondent à aucune fiche personnage : la case serait générée sans leurs références ni leur description. Rattache chaque nom à la bonne fiche (il devient un alias, reconnu partout dans la série) ou écarte-le si c'est un figurant.",

  // --- chapitre : mise en page, croquis, atelier, lettrage, production, QC --------------------------------------
  // lettrage
  "lettrage.guides":
    "Superpose à la planche la zone où chaque case peut recevoir ses bulles (en rose) et les visages détectés, que le placement automatique évite de couvrir. Décoche pour voir la planche telle qu'elle sera exportée.",
  "lettrage.recompute":
    "Replace toutes les bulles et onomatopées de la page automatiquement. À utiliser après une nouvelle image ou une nouvelle mise en page ; tes ajustements à la main de cette page sont perdus.",
  "lettrage.warnings":
    "Ce qui empêche une page propre : case sans image retenue, texte qui ne tient pas dans sa bulle, onomatopée qui déborde. Clique sur « voir la bulle » pour corriger.",
  "lettrage.bubble_kind":
    "Change la forme de la bulle et sa police (parole, pensée, cri, hors champ ou récitatif). Le récitatif est un cartouche de narration, sans queue.",
  "lettrage.bubble_auto":
    "Oublie la position, la taille et la queue réglées à la main : la bulle reprend la place calculée automatiquement.",
  "lettrage.sfx":
    "Les onomatopées sont lettrées par-dessus l'image, hors bulle, et peuvent déborder de la case. Elles ne sont jamais dessinées par le modèle d'image : ajoute-les ici.",
  "lettrage.sfx_intensity":
    "Règle la taille et la police par défaut : « calme » pour un petit bruit, « choc » pour une explosion qui envahit la case.",
  "lettrage.sfx_skew":
    "Penche les lettres vers la droite (valeur positive) ou la gauche, pour donner du mouvement. 0 = lettres droites.",
  "lettrage.bleed":
    "Ajoute la marge de fond perdu autour de la page : l'image déborde du format rogné pour qu'aucun liseré blanc n'apparaisse à la coupe. À cocher pour un imprimeur.",
  "lettrage.crop_marks":
    "Trace les traits de coupe dans les coins, pour indiquer à l'imprimeur où rogner. Inutile pour une lecture à l'écran.",
  "lettrage.render":
    "Assemble la page courante (images, bulles, onomatopées) en PNG et SVG avec les options cochées, pour la vérifier ou la télécharger seule.",
  "lettrage.export":
    "Assemble toutes les pages du chapitre et les range dans un ZIP à télécharger. Le travail passe par la file d'attente ; tu peux continuer pendant ce temps.",
  "lettrage.finish":
    "Agrandit les images retenues trop petites pour l'impression (sous le seuil de dpi du format), sans changer leur composition. À lancer avant l'export final.",
  // production
  "production.agents":
    "Où en sont les agents qui travaillent avant les images : le scénariste découpe, le directeur artistique règle chaque page, le metteur en page dessine les cases.",
  "production.generation":
    "La case en cours de génération et la file de ce chapitre. « Générer tout le chapitre » met en file chaque case sans version choisie, au palier de la série.",
  "production.remaining":
    "Nombre de cases encore en file et temps estimé. L'estimation se base sur la durée réelle des dernières générations, ou sur les presets tant qu'il n'y en a pas.",
  "production.lettered":
    "Affiche la page assemblée avec ses bulles et onomatopées, comme à l'export. Décoche pour revoir les cases nues et leur état.",
  // contrôle qualité
  "qc.detections":
    "Ce que les détecteurs du contrôle qualité ont trouvé dans l'image : visages, mains et texte parasite. Une main mal dessinée ou du texte dans l'image baisse le score.",

  "layout.style":
    "Le style de découpe de cette page : sage (découpes droites, lecture posée), dynamique (quelques biais sur les cases fortes) ou nerveuse (biais marqués). Par défaut, celui de la série.",
  "layout.template":
    "La grille des cases. En automatique, elle est choisie d'après le nombre, l'importance et l'intensité des cases ; impose un gabarit si la découpe proposée ne te convient pas.",
  "layout.reroll":
    "« Nouvelle mise en page » tire une autre variante du même style (nouvelle graine). « Recalculer » refait le calcul avec la même graine, par exemple après un changement de format ou de scénario.",
  "layout.panels":
    "La taille et les biais de chaque case viennent de son importance et de son intensité, réglées dans le Scénario ou la Direction artistique. Bord, fond perdu et incrustation se forcent ici, case par case.",
  "layout.frame":
    "Bordure classique, sans bord, ou fondu au papier (l'image s'efface vers le blanc). « Auto » laisse le style de mise en page décider.",
  "layout.bleed":
    "Fond perdu : l'image déborde jusqu'au bord de la feuille, sans marge blanche. Possible seulement pour une case qui touche un bord extérieur de la page.",
  "layout.inset":
    "Incrustation : la case est posée par-dessus sa voisine, comme un médaillon. Utile pour un gros plan de réaction sur une grande case.",
  "croquis.croquer":
    "Un croquis est un brouillon de la case en quelques secondes, au ratio exact de sa case : tu juges la composition avant de lancer une vraie génération. Les cases validées, au propre ou en file sont ignorées.",
  "croquis.propre":
    "Génère la version finale des seules cases validées, au palier de la série, en repartant du croquis (même graine, même prompt) : le cadrage retenu est conservé.",
  "croquis.clavier":
    "Trie sans souris : V ou Entrée valide et passe à la suivante, R re-croque (nouvelle graine), E modifie la description, U retire la validation, ← et → changent de case, C croque toute la page.",
  "croquis.denoise":
    "La part du croquis redessinée au passage au propre : bas, le résultat colle au croquis ; haut, le modèle corrige davantage. Vide : la valeur de la série.",
  "direction.lancer":
    "Le directeur artistique (LLM) propose un rythme par page et, pour chaque case, intensité, plan, angle, cadre, ambiance et onomatopées. Rien ne bouge dans la mise en page tant que tu n'appliques pas.",
  "direction.appliquer":
    "Recalcule la mise en page des pages avec les choix retenus (rythme, page choc, style, gabarit, intensité des cases). À faire une fois la proposition relue et retouchée.",
  "direction.lock":
    "Un choix verrouillé 🔒 est le tien : l'agent le garde quand il repropose. Modifier un champ le verrouille ; clique sur le cadenas pour le rendre à l'agent.",
  "direction.rythme":
    "Le tempo de la page dans le chapitre : calme, montée, climax ou respiration. Il règle le contraste des tailles de cases et les biais à la mise en page.",
  "direction.page_choc":
    "Pleine page : une seule image occupe la page. Splash : une case géante domine les autres. À réserver aux révélations et aux scènes clés.",
  "direction.panel":
    "Intensité, plan, angle et cadre guident la taille de la case et le prompt de l'image ; l'ambiance décrit la lumière. Le cadre et les onomatopées servent ensuite au lettrage.",
  "atelier.generate_missing":
    "Seulement la page affichée : met en file ses cases sans version choisie, en version finale. Pour tout le chapitre, utilise « Générer le chapitre ». Suis l'avancement dans la file en haut à droite ou dans l'onglet Production.",
  "atelier.finish":
    "Finition d'impression : agrandit la version retenue des cases trop petites pour le dpi du format, sans changer la composition. À faire une fois les versions choisies, avant l'export.",
  "atelier.dpi":
    "La résolution réelle de la case une fois imprimée au format de la série. Sous le seuil, elle sera floue à l'impression : lance « Finaliser ».",
  "atelier.prompt":
    "Le texte envoyé au modèle d'image, rédigé par l'IA (série en « Prompt rédigé par l'IA ») ou assemblé par fragments d'après la case, les personnages et le style de la série. Rédigé une fois par case, pas à chaque génération. Retouché à la main, il est gardé tel quel ; « Reconstruire le prompt » repart de zéro (et le redemande à l'IA).",
  "atelier.workflow":
    "Le workflow ComfyUI de la case. Automatique : celui de la série, ou sa variante avec références quand un personnage, un décor ou un objet a des images de référence.",
  "atelier.seed":
    "La graine du hasard : même seed et même prompt redonnent la même image. Laisse vide pour explorer ; fixe-la pour juger l'effet d'une retouche du prompt.",
  "atelier.variants":
    "Le nombre de versions lancées d'un coup, chacune avec sa propre seed. Elles s'ajoutent aux versions de la case : tu choisis ensuite.",
  "atelier.regenerate":
    "Lance une nouvelle version au palier de la série ; les anciennes restent. « Même seed » rejoue la seed de la version choisie, utile après une retouche du prompt.",
  "atelier.quality":
    "Régénère cette case seule au palier Qualité, plus lent et plus fin, même prompt et nouvelle seed. À garder pour les cases importantes ; les autres versions ne bougent pas.",
  "atelier.composition":
    "Le verrouillage de composition (ControlNet) impose le cadrage et les poses d'une image guide à toutes les régénérations de la case. Utile quand la composition est bonne mais le rendu à refaire.",
  "atelier.control_strength":
    "1 : la composition de l'image guide est tenue. Plus bas, le modèle s'en écarte plus librement ; au-dessus de 1 (jusqu'à 2), la contrainte est renforcée.",
  "atelier.control_lineart":
    "Trait : suit les contours et les traits de l'image guide. Le plus fidèle pour repartir d'un croquis ou d'une version existante.",
  "atelier.control_depth":
    "Profondeur : ne garde que les volumes et les plans (premier plan, fond). Laisse plus de liberté au dessin que le trait.",
  "atelier.control_pose":
    "Pose : extrait le squelette des personnages (corps, mains, visage). Idéal depuis une photo de pose ou un mannequin.",
  "atelier.control_scribble":
    "Croquis à la main : réduit ton gribouillis ou ton crayonné à ses grandes lignes. Pour un dessin rapide fait par toi.",
  "atelier.control_canny":
    "Contours nets (Canny) : détecte les bords francs de l'image. Utile pour une photo ou un décor aux lignes nettes.",
  "atelier.control_carte":
    "Carte déjà prête : l'image importée est déjà une carte de contrôle (trait, profondeur ou pose) et est utilisée sans prétraitement.",
  "atelier.versions":
    "Toutes les images générées pour la case. Clique pour agrandir, comparer, réparer ou choisir : seule la version choisie est assemblée dans la page.",
  "atelier.repair":
    "Redessine une seule zone (visage, main…) d'une version ; le reste de l'image ne bouge pas au pixel près. Le résultat devient une nouvelle version, à choisir ou non.",
  "atelier.repair_grow":
    "La marge ajoutée autour de la zone pour que la retouche se raccorde au reste. Augmente-la si la jonction se voit.",
  "atelier.repair_feather":
    "Le fondu des bords de la retouche. Plus il est large, plus la transition avec l'image d'origine est douce.",
  "atelier.repair_denoise":
    "La force de la retouche : vers 0,3 la zone est juste corrigée, vers 0,6 elle est redessinée franchement.",
  "atelier.annotation":
    "Juge la version « bonne » ou « mauvaise » (touches B et M), avec ses défauts. Ces annotations nourrissent le banc d'essai du QC ; elles ne changent pas son verdict.",
  "atelier.qc":
    "Le contrôle qualité note la version sur 100 : 70 et plus = OK, moins de 40 = rejet, entre les deux = à revoir. Il passe automatiquement après chaque génération.",
  "atelier.qc_scores":
    "Chaque couche note sur 100 (détecteurs, cohérence des personnages, vision) ; le score final est leur moyenne pondérée. Des règles peuvent l'abaisser : texte dessiné = rejet, visage manquant = à revoir.",
  "atelier.qc_doubt":
    "Zone de doute : quand détecteurs et cohérence donnent entre 40 et 80, la vision (plus lente) est lancée pour trancher. « Avec la vision » la force même hors de cette zone.",
  "atelier.qc_override":
    "Garde la version malgré le verdict du QC, quand tu juges qu'il se trompe. Ta décision est tracée dans le contrôle qualité.",
  "atelier.qc_chapter":
    "Contrôle toutes les cases générées du chapitre pas encore contrôlées, après les générations en file. « Tout recontrôler » refait aussi celles déjà notées.",
  // (section chapitre)

  // --- banc d'essai, savoir-faire, équipe ------------------------------------------------------------------------
  "bench.dataset":
    "Les cases que tu as annotées « bonne » ou « mauvaise » dans l'atelier. Le banc mesure le contrôle qualité dessus ; vise 50 à 100 cases, dont des mauvaises.",
  "bench.vision":
    "Ajoute la couche vision (un modèle qui regarde l'image et la compare à sa description). Plus juste mais lente : décoche pour un premier passage rapide.",
  "bench.run":
    "Repasse chaque couche du contrôle qualité sur les cases annotées et compare son verdict au tien. Le banc attend que les générations en cours soient finies.",
  "bench.history":
    "Chaque passage du banc est gardé avec le preset utilisé : compare deux runs pour voir si un réglage de presets/qc.yaml a amélioré les choses.",
  "bench.layers":
    "Les couches du contrôle qualité : détecteurs (visages, mains, texte), cohérence des personnages avec leur fiche, vision, et le score combiné qui décide du verdict.",
  "bench.precision":
    "Parmi les cases signalées, la part qui était vraiment mauvaise. Une précision basse = beaucoup de fausses alertes à vérifier à la main.",
  "bench.recall":
    "Parmi les mauvaises cases, la part que le contrôle a bien signalée. C'est la mesure prioritaire : une mauvaise case non signalée finit dans le chapitre.",
  "bench.fp":
    "Faux positifs : bonnes cases signalées à tort. Elles te coûtent un coup d'œil, pas plus.",
  "bench.fn":
    "Faux négatifs : mauvaises cases laissées passer. C'est l'erreur à faire tomber à zéro en premier.",
  "bench.threshold":
    "Le seuil réglé dans presets/qc.yaml, puis celui que le banc suggère : celui qui atteint le rappel visé avec le moins de fausses alertes.",
  "bench.apply":
    "Écrit les seuils suggérés dans presets/qc.yaml (tu vois les changements avant de confirmer). Les prochains contrôles qualité les utilisent aussitôt.",
  "bench.confusion":
    "Croise ton annotation (lignes) et le verdict de la couche au seuil actuel (colonnes) : VP et VN sont justes, FN et FP sont des erreurs.",
  // savoir-faire
  "knowledge.collections":
    "Une collection regroupe des fiches de méthode sur un thème. Les agents qui la lisent reçoivent les passages les plus proches de ce qu'ils sont en train de faire.",
  "knowledge.scope":
    "Globale : lue par les agents de toutes les séries. Rattachée à une série : seulement quand ils travaillent sur celle-ci (pratique pour un ton ou un univers précis).",
  "knowledge.search":
    "Pose la question qu'un agent se poserait pour vérifier que tes fiches remontent bien. Les passages en surbrillance sont ceux qu'il recevrait vraiment.",
  "knowledge.scores":
    "Score hybride : 60 % de proximité de sens (vecteurs) et 40 % de mots-clés en commun. Plus il est haut, plus le passage a de chances d'être injecté.",
  "knowledge.indexing":
    "Les fiches sont découpées en passages et transformées en vecteurs par le modèle d'embeddings local. Réindexe après un changement de modèle.",
  "knowledge.whole":
    "Une collection plus petite que ce seuil est injectée entière, sans recherche : utile pour une courte charte que l'agent doit toujours avoir sous les yeux.",
  "knowledge.agents":
    "Les collections que chaque agent lit, son budget de texte et le nombre de passages au plus. Se règle dans « L'équipe », agent par agent.",
  "knowledge.tags":
    "Mots-clés libres pour retrouver et trier tes documents. Ils comptent aussi dans la partie « mots-clés » de la recherche.",
  // l'équipe
  "equipe.agents":
    "Chaque agent fait une étape du pipeline (découpage, direction artistique, prompts d'image, contrôle qualité…). Ouvre-en un pour lire ses réglages, l'essayer et l'adapter.",
  "equipe.scope":
    "Profil global : vaut pour toutes les séries. Choisis une série pour lui donner des réglages propres ; ce que tu ne changes pas suit le profil global.",
  "equipe.knowledge":
    "Les collections de savoir-faire que l'agent lit avant de travailler, par leur nom. Laisse vide pour qu'il n'en lise aucune.",
  "equipe.top_k":
    "Nombre maximal de passages de savoir-faire joints à chaque appel. Plus il y en a, plus l'agent a de contexte, mais plus l'appel est long.",
  "equipe.trial":
    "Fait tourner l'agent sur un exemple avec les réglages du formulaire, même non enregistrés, et montre ce qu'il reçoit et ce qu'il produit. Rien n'est modifié dans tes séries.",
  "equipe.versions":
    "Chaque enregistrement crée une version. « Revenir à cette version » en recrée une nouvelle : l'historique n'est jamais perdu.",
  "equipe.series_overrides":
    "Les agents qui ont des réglages propres à cette série. Les autres suivent le profil global de « L'équipe ».",
} as const satisfies Record<string, string>;

export type HelpId = keyof typeof HELP;
