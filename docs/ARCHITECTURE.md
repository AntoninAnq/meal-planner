# Meal Planner — Architecture & décisions

> **Statut** : document de référence du projet. Toute décision structurante y est consignée avec sa justification.
> **Dernière révision** : 2026-08-04
> **Langue** : ce document est en français. **Le code, les identifiants, les tables et les schémas sont en anglais** (voir §12).

---

## 1. Objet du document

Ce fichier est la colonne vertébrale du projet. Il fixe :

- ce que le produit fait et ne fait pas,
- le vocabulaire du domaine,
- les **invariants non négociables** (§5),
- le modèle de données cible,
- la frontière entre code déterministe et LLM,
- la stratégie de test et d'évaluation,
- le phasage.

Une décision qui contredit ce document doit d'abord modifier ce document.

---

## 2. Produit

### 2.1 Positionnement

SaaS de planification de repas pour familles. Le marché français généraliste est occupé (Jow, FamilyChef, MesMenus) : le produit ne se positionne pas frontalement, mais sur un **wedge** précis.

### 2.2 Le wedge

Les foyers où **tout le monde ne mange pas la même chose** — typiquement de jeunes enfants qui ne mangent pas le plat des adultes. Les applications existantes raisonnent « un menu par foyer » et traitent mal ce cas.

Trois usages :

1. **Planification de la semaine** avec plusieurs plats par créneau (le cœur).
2. **Idées de goûters** (module optionnel).
3. **Mode invités** : repas quand famille ou amis viennent dîner le week-end.

### 2.3 La douleur réelle

Ce n'est pas « je ne sais pas quoi donner aux enfants », c'est **« je ne veux pas cuisiner deux fois »**.

Conséquence directe sur la fonction objectif : le planificateur ne se contente pas de remplir des créneaux en respectant des contraintes, il cherche à **minimiser le nombre de préparations distinctes** — sans jamais en faire une contrainte dure (voir §4.2).

### 2.4 Hors périmètre (volontairement repoussé)

- Inventaire du frigo et liste de courses automatique.
- Scan photo du frigo.
- Détection des dates de péremption.
- Mode anti-gaspi (bon second wedge, mais après le socle).

---

## 3. Glossaire du domaine

Le code est en anglais. Ce glossaire fixe la traduction pour éviter toute dérive de vocabulaire.

| Anglais (code) | Français | Définition |
|---|---|---|
| `household` | foyer | L'unité de compte et de facturation. Porte les membres, la grille de créneaux, l'historique. |
| `member` | membre | Une personne du foyer. Porte ses contraintes alimentaires et son stade de vie. |
| `life_stage` | stade de vie | `baby` / `young_child` / `teen_adult`. Détermine ce qui constitue un vrai repas pour ce membre. |
| `meal_slot` | créneau | Une case du planning : un jour × un type de repas (`lunch` / `dinner`). |
| `dish` | plat | Ce qui est effectivement servi sur un créneau. Un créneau porte 1 à N plats. |
| `planned_dish` | plat planifié | Un plat sur un créneau donné, avec les membres qui le mangent. |
| `recipe` | recette | Une entrée du catalogue. |
| `ingredient` | ingrédient | Une entrée du **référentiel normalisé**, distincte du texte libre d'une ligne de recette. |
| `allergen` | allergène | Un des 14 allergènes réglementaires (INCO). |
| `dietary_constraint` | contrainte alimentaire | Allergie sévère, intolérance ou aversion, portée par un membre. |
| `food_category` | catégorie alimentaire | Légumineuses, poisson, viande rouge, féculents, légumes verts… Sert à la rotation. |
| `snack` | goûter | Objet distinct, **pas** un créneau de repas. Module optionnel. |
| `guest_plan` | mode invités | Workflow séparé, réutilise les nœuds du workflow semaine. |

> **Note d'internationalisation.** Le front démarre en français mais est i18n-ready dès la phase 0. Certains concepts sont franco-français (`snack` au sens du goûter à 16 h n'a pas d'équivalent anglo-saxon) : ils sont traités comme des **modules optionnels**, activables par foyer, jamais câblés dans le noyau. Une version anglaise demanderait aussi un **catalogue de recettes distinct**, pas seulement des libellés traduits.

---

## 4. Modèle de domaine

### 4.1 Pas de groupes stockés

**Un « groupe » n'est pas une propriété de la personne, c'est une conséquence d'un repas donné.**

Les contraintes (allergies, stade de vie, goûts) sont **individuelles**. Ce qui est partagé, c'est le plat.

> Pour chaque créneau, le planificateur produit **1 à N plats** et **assigne chaque membre à un plat**. Un « groupe » est l'ensemble des membres qui mangent le même plat ce jour-là — émergent, recalculé à chaque créneau, jamais stocké comme partition du foyer.

Conséquences :

- Un adulte peut manger le plat de l'enfant de 5 ans si ça lui convient — le modèle l'autorise naturellement.
- L'objectif de recouvrement et le nombre de plats deviennent **le même levier** : minimiser les plats distincts = maximiser la taille des clusters.
- L'historique anti-répétition est **par membre**, seule granularité correcte.
- Un cluster de taille 1 est parfaitement valide (le bébé qui déjeune seul le mercredi) et ne doit pas être traité comme un échec.

### 4.2 Le recouvrement est un objectif, pas une contrainte

Le recouvrement est **souhaitable mais non contraignant**. Une semaine où rien ne se recoupe est un résultat acceptable, pas une erreur.

De même, le **nombre maximal de plats par créneau est une pénalité de scoring, jamais une contrainte dure**.

> **Pourquoi.** Un foyer avec un bébé + un intolérant au lactose + un ado a mécaniquement besoin de 3 plats. Une borne dure à 2 rendrait le problème infaisable et l'endpoint retournerait « aucune solution » pour un foyer parfaitement banal. Seule borne dure : au pire, un plat par membre — trivialement satisfaisable.

### 4.3 Stades de vie et adéquation

Chaque **membre** a un `life_stage`. Chaque **recette** porte `suitable_stages`, l'ensemble des stades pour lesquels elle constitue **un vrai repas**.

> Une assignation est valide **ssi** `member.life_stage ∈ recipe.suitable_stages`.

Un seul champ, une seule règle, en SQL, qui couvre les deux directions :

- la purée lisse est taguée `{baby}` → un adulte ne peut pas y être assigné ;
- le curry relevé est tagué `{teen_adult}` → le bébé non plus.

#### Seuils et transitions

| `life_stage` | Intervalle |
|---|---|
| `baby` | 0 – 18 mois |
| `young_child` | 18 mois – 11 ans |
| `teen_adult` | 11 ans et plus |

**Le stade est choisi par l'utilisateur, pas dérivé.** La date de naissance est optionnelle et n'est pas collectée par l'interface (voir `UX-V0.md` §9) ; la dérivation reste implémentée mais dormante, disponible si l'on veut un jour proposer la date de naissance en option contre des rappels automatiques. Les seuils ci-dessus sont **configurables**, pas codés en dur (I8).

> **Pourquoi 18 mois et non 12.** Les interdits réglementaires (miel, lait de vache) lèvent à 12 mois, mais les textures et le risque de fausse route non. Le seuil de sécurité doit être plus conservateur que le seuil légal.

> **Pourquoi un stade choisi et non dérivé est acceptable.** Les groupes ne se franchissent que dans le sens de l'âge, donc **oublier de mettre à jour est toujours du côté sûr** : un enfant resté marqué `baby` garde le catalogue le plus restrictif — agaçant, pas dangereux, et auto-correctif, puisque le parent verra des purées proposées à un enfant qui mange comme tout le monde. L'erreur inverse exigerait d'avancer volontairement le groupe trop tôt : un acte délibéré, pas un oubli. En prime, plus aucune date de naissance de mineur en base.

> **Quand une date de naissance est présente, toute transition est proposée par le système et validée par le parent.** Aucune bascule silencieuse, dans aucun sens.
>
> **Pourquoi.** Franchir `baby` → `young_child` **élargit** ce qui est autorisé : du jour au lendemain, l'ensemble des candidats s'ouvre à des plats salés, épicés, en morceaux, sans que personne n'ait jugé si cet enfant-là est prêt. C'est la symétrie du §4.5 (`baby` n'est jamais implicite). Une règle uniforme est plus simple qu'une règle asymétrique, et le parent garde la main.

> **Sur la granularité.** `young_child` couvre dix ans, et un enfant de 2 ans ne mange pas comme un enfant de 9. On **reste délibérément à trois stades** : la différenciation fine relève du **score d'appétence** (phase 3+), pas d'un stade supplémentaire. Le stade dit « est-ce un vrai repas pour lui », l'appétence dit « va-t-il l'aimer » — ce ne sont pas le même axe. Ajouter un stade coûterait une décision de tag de plus sur chaque recette d'un catalogue qui est déjà le goulot (§4.5). Si l'appétence révèle qu'un stade manque, Alembic ajoute une valeur d'enum sans douleur.

> **Pourquoi pas un min/max.** Une borne haute serait bancale (un bœuf bourguignon n'a pas de limite d'âge supérieure). Un ensemble est plus simple et plus juste.

> **Pourquoi c'est nécessaire.** Sans ce champ, l'objectif « minimiser les plats distincts » a un **optimum dégénéré** : servir à tout le monde le plat du membre le plus contraint. La sécurité est monotone avec l'âge (un plat sûr pour le bébé est sûr pour tous), donc rien dans les contraintes de sécurité n'interdit cette solution absurde. `suitable_stages` la tue.

### 4.4 Portions

Un coefficient de portion par stade, **configurable, jamais codé en dur** :

| `life_stage` | Coefficient par défaut |
|---|---|
| `baby` | 0,25 |
| `young_child` | 0,5 |
| `teen_adult` | 1,0 |

Une recette « pour 4 » se recalcule pour « 2 adultes + 1 jeune enfant » sans jamais toucher à des apports nutritionnels.

> **Décision explicite : aucun calcul nutritionnel.** Pas de calories, pas de macronutriments, pas d'apports journaliers recommandés. Le stade de vie est le seul proxy d'adéquation. C'est volontaire : la nutrition calculée est un projet à part entière, et sa valeur ajoutée pour le wedge est faible.

### 4.5 Stades par défaut d'une recette

| Situation | `suitable_stages` |
|---|---|
| Défaut (utilisateur ou scraper n'a rien précisé) | `{young_child, teen_adult}` |
| `baby` | **Jamais implicite.** Uniquement par action humaine explicite. |

> **Pourquoi ce défaut asymétrique.** Le risque n'est pas réparti uniformément. Servir un plat d'adulte à un enfant de 5 ans qui n'aime pas, c'est un dîner raté. Le servir à un nourrisson, c'est du sel, du miel ou une fausse route. Le stade `baby` est la seule zone où l'erreur est dangereuse, donc la seule qui mérite un opt-in explicite.
>
> Un défaut restrictif (`{teen_adult}` seul) rendrait le catalogue inutilisable pour le wedge dès le premier jour ; un défaut permissif exposerait les nourrissons. L'asymétrie préserve les deux.

**Conséquence structurelle à assumer :** le stade `baby` n'est **jamais alimentable par le scraper**. Le catalogue bébé restera du contenu utilisateur ou curé à la main. C'est une limite du wedge, pas un bug à corriger.

### 4.6 Contraintes alimentaires : trois niveaux

| Niveau | Portée du filtre | Comportement |
|---|---|---|
| `severe_allergy` | **Foyer entier** | L'allergène ne rentre pas dans le plan, pour personne. |
| `intolerance` | **Membre** | Filtre l'assiette de cette personne uniquement → autorise un plat de plus. |
| `aversion` | **Aucune** | Alimente le score d'appétence (phase ultérieure), n'écarte jamais un plat de force. |

**Défaut quand l'utilisateur ne précise pas la sévérité : `severe_allergy`.**

**Le membre est optionnel — mais pour les aversions seulement.** Une aversion sans membre s'applique au foyer entier (« on n'aime pas ça ici ») ; avec un membre, à cette personne seule. Un seul concept, une seule table, un seul chemin de filtrage (voir `UX-V0.md` §10). Une allergie sans personne à qui elle appartient n'a en revanche pas de sens : sa portée foyer vient déjà de sa **sévérité**, pas de son stockage. Une contrainte de base le vérifie.

> **Pourquoi la portée foyer pour les allergies sévères.** La contamination croisée est réelle : même plan de travail, même huile, même éponge. Filtrer seulement l'assiette de la personne ne protège de rien. C'est d'ailleurs le comportement réel des familles concernées — on n'achète pas de cacahuètes quand un enfant y est allergique.
>
> **Pourquoi le défaut sévère.** Une famille sur-contrainte a des menus un peu ternes. Une famille sous-contrainte a un passage aux urgences. Le défaut tombe du côté sûr.

### 4.7 Grille de créneaux

La grille de créneaux à planifier est déclarée **au niveau du foyer** (pas par membre) : quels jours, quels types de repas.

Défaut à l'inscription : **soirs en semaine + week-end complet** (la cantine couvre les midis en semaine dans le cas français typique).

**Limite connue et acceptée :** le cas « le bébé déjeune à la maison pendant que les grands sont à la cantine » n'est pas exprimable par le profil. Échappatoire possible plus tard, sans nouvelle table : permettre de décocher des membres sur un créneau **au moment de générer** — c'est une entrée de génération, pas une donnée de profil.

### 4.8 Le goûter est un objet à part

Le goûter n'a pas de plat, pas d'assignation multi-groupes, pas de recouvrement. Le modéliser comme un créneau normal polluerait le planificateur de cas particuliers.

→ **Objet distinct, module optionnel, workflow et endpoint séparés.**

### 4.9 Trois façons de nourrir des besoins différents

Un plat n'est pas atomique. Il existe **trois mécanismes**, et ils n'ont pas le même coût de cuisine — ce qui compte, puisque l'objectif est de ne pas cuisiner deux fois :

| Niveau | Mécanisme | Effort |
|---|---|---|
| 1 | Même plat, même assiette | Une préparation |
| 2 | **Même préparation, assiette différente** — sans olives pour Léo, part du bébé prélevée avant salage et mixée | **Une préparation** |
| 3 | Deux plats distincts sur une base commune | Deux préparations |

**Le niveau 2 est le meilleur résultat possible du système**, meilleur que le niveau 3 : zéro cuisine supplémentaire et chacun mange ce qui lui convient. C'est aussi une piste sérieuse pour la déclinaison bébé — dans beaucoup de cas, ce n'est pas une recette bébé qui manque, c'est une **instruction de service**.

La **variante de service** est portée par l'**assignation** (`planned_dish_member`), pas par le plat : deux personnes peuvent avoir des variantes différentes sur le même plat. Texte libre en V0, structurée en V1 une fois les ingrédients disponibles.

> **La frontière de sécurité ne bouge pas.** Le code décide **si** un membre peut être assigné à ce plat (`suitable_stages`, allergènes) ; la variante décrit seulement **comment** le servir. Une variante ne peut jamais rendre acceptable une assignation qui ne l'était pas — sinon le LLM redeviendrait juge de la sécurité et I1 tombe.

Le niveau 3 exige les ingrédients, donc le catalogue : le lien `derived_from_dish_id` existe dans le contrat dès la V0 mais reste nul.

---

## 5. Invariants non négociables

Ces règles ne se négocient pas au cas par cas. Une PR qui les enfreint est refusée.

### I1 — Aucune décision de sécurité n'est prise par un LLM

Filtres allergènes, `suitable_stages`, validation d'une assignation : **code déterministe (SQL), toujours**. Un LLM peut *proposer*, jamais *décider*.

### I2 — Le filtre allergène porte sur des données vérifiables

Le filtre dur porte sur les **tags allergènes de la recette**, pas sur une recherche de sous-chaîne dans du texte libre.

> **Pourquoi.** « crème fraîche », « beurre demi-sel », « parmesan » et « béchamel » contiennent tous du lait, et aucun ne contient la chaîne `lait`. Un `WHERE ingredients NOT LIKE '%lait%'` est un **filtre fantôme** : il rassure sans protéger.

### I3 — `allergens_verified` est dérivé, jamais déclaré

> `allergens_verified = true` **ssi** toutes les lignes d'ingrédients de la recette résolvent vers le référentiel (match exact, ou match approché confirmé par un humain).

Une recette non vérifiée est **invisible pour tout foyer ayant une allergie sévère**. Le système dégrade proprement : les foyers sans allergie sévère voient tout le catalogue.

> **Pourquoi pas une extraction d'allergènes par LLM.** C'est exactement ce que I1 interdit. Un LLM peut proposer des tags ; la recette reste `allergens_verified = false` tant qu'un humain n'a pas confirmé.

### I4 — Le matching approché ne s'applique jamais tout seul

| Situation | Comportement |
|---|---|
| Match exact après normalisation (minuscules, `unaccent`, singulier, espaces) | Résolution automatique |
| Match approché (trigrammes `pg_trgm`) | **Proposition affichée à l'utilisateur**, jamais appliquée seule |
| Aucun match | Texte libre, ligne marquée non résolue |

> **Pourquoi.** Le fuzzy matching se trompe **exactement sur les cas qui comptent** :
>
> | Saisie | Match le plus proche | Conséquence |
> |---|---|---|
> | `lait de coco` | `lait` | Lait introduit ou effacé à tort |
> | `farine de riz` | `farine de blé` | **Gluten introduit ou effacé** |
> | `crème de soja` | `crème` | Lait ⇄ soja, deux allergènes échangés |
>
> Les ingrédients de substitution sont, par construction, nommés comme l'aliment qu'ils remplacent. Une similarité textuelle élevée y signale une **opposition** allergénique, pas une équivalence.

### I5 — Le constructeur de prompt ne reçoit jamais l'entité `member`

Il reçoit un **DTO de contraintes** : stades, codes allergènes, tags de goût, signaux de rotation. **Jamais** de prénom, de date de naissance, ni d'identifiant de foyer.

Testable : un test échoue si un prénom ou une date apparaît dans un prompt.

> **Pourquoi.** Les allergies sont des données de santé (RGPD art. 9, catégorie particulière) et l'on stocke des dates de naissance de mineurs. La règle ne coûte rien à poser maintenant et est très pénible à rétro-fitter. Bénéfice immédiat : les prompts sont plus courts et plus stables.

### I6 — `household_id` est dérivé de l'identité authentifiée

Jamais accepté depuis le corps ou l'URL d'une requête.

> **Pourquoi.** `POST /meal-plans/week {"household_id": 1}` fonctionne parfaitement pendant six mois, puis devient un **IDOR** au deuxième foyer : n'importe qui change le numéro et lit les allergies des enfants d'une autre famille. Corriger ça après coup veut dire toucher tous les endpoints et toutes les requêtes.

### I7 — Aucun contenu généré par IA n'entre au catalogue

Les recettes ne sont **pas** générées par IA. Les suggestions produites par le LLM (notamment en V0, §10.2) vont dans l'**historique** avec `source = llm_suggestion` et ne deviennent jamais des entrées de catalogue.

> **Pourquoi.** Semer le catalogue de contenu généré est irréversible : dans six mois, on ne saura plus lesquelles.

### I8 — Aucune dépendance technique n'est codée en dur

Ollama, Postgres local, chemins de fichiers, URL de base, endpoints, secrets : **tout passe par la configuration ou une interface**, même si une seule implémentation est utilisée pendant longtemps.

### I9 — Republication interdite

Pour tout contenu externe, on stocke **uniquement des métadonnées structurées** (ingrédients, quantités, temps, tags — des faits, non protégeables), extraites du JSON-LD `schema.org/Recipe`, et on **renvoie vers la source**. Jamais le texte ni la prose de l'auteur.

---

## 6. Frontière LLM

### 6.1 Le constat

Chaque fois qu'on rend une règle sûre et explicable, on la sort du LLM. Prises ensemble, ces décisions vident le centre du système et transforment le « workflow semaine » en simple solveur — LangGraph devenant alors un habillage décoratif.

Ce projet est **délibérément agentic**. La frontière ci-dessous préserve les deux promesses : un système réellement agentic **et** des garanties de sécurité qui ne dépendent jamais du modèle.

### 6.2 Le pipeline

```
┌──────────────────────────────────────────────────────────────────┐
│ 1. PRÉ-FILTRE (SQL, déterministe)                                │
│    Contraintes dures → ensemble de candidats sûrs                │
│    · allergies sévères → exclusion foyer                         │
│    · intolérances     → exclusion membre                         │
│    · suitable_stages  → compatibilité membre                     │
│    · allergens_verified si allergie sévère au foyer              │
│    Puis CLASSE et TRONQUE : ~15-25 candidats par créneau          │
└────────────────────────────┬─────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ 2. SIGNAUX SOUPLES (SQL, déterministe)                           │
│    · jours depuis la dernière occurrence par food_category       │
│    · historique récent par membre (anti-répétition)              │
│    · potentiel de recouvrement entre candidats                   │
│    · budget temps / complexité déclarés                          │
└────────────────────────────┬─────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ 3. ARBITRAGE (LLM)                                               │
│    Choisit parmi les candidats, en tenant compte des signaux.    │
│    Sortie contrainte par schéma JSON.                            │
│    N'ÉMET QUE DES IDENTIFIANTS. Jamais de prose.                 │
└────────────────────────────┬─────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ 4. RE-VALIDATION (SQL, déterministe)                             │
│    · chaque plat choisi appartient-il à l'ensemble autorisé ?    │
│    · chaque membre est-il assigné à exactement un plat ?         │
│    · aucune violation d'allergène ni de stade ?                  │
│    Sinon → rejeu, avec compteur borné.                           │
└──────────────────────────────────────────────────────────────────┘
```

### 6.3 La règle de répartition

> **Contrainte dure** → SQL, filtre l'ensemble de candidats
> **Signal souple** → calculé en SQL, **passé au LLM comme contexte**
> **Arbitrage** → LLM
> **Validation** → SQL, rejette et relance si la sortie sort de l'enveloppe

**La rotation nutritionnelle et l'anti-répétition sont des signaux, pas des filtres.** « Il faudrait des lentilles cette semaine » n'est pas une contrainte : c'est un souhait qui doit céder si l'ado déteste les lentilles et qu'il y a déjà un plat végétarien. Les traiter en SQL dur produirait des menus mécaniques.

Format du signal passé au prompt : `legumineuses: 23 jours · poisson: 4 jours · viande_rouge: 9 jours`.

### 6.4 Où l'agentic vit réellement

| Zone | Rôle du LLM | Phase |
|---|---|---|
| **Amont — intention floue** | « Cette semaine on est peu là, mardi je rentre tard, il reste du poulet » → contraintes et signaux structurés. Aucun formulaire ne capte ça. | V0 puis V1 |
| **Cœur — arbitrage** | Choix parmi les candidats pré-filtrés, en lisant les signaux. | V1 |
| **Cœur du wedge — déclinaison** | « Comment je sers ce curry au petit de 2 ans ? » → texture, ce qu'on retire, à quel moment on prélève sa part. **Ce n'est pas de la génération de recette, c'est de l'adaptation d'une recette existante.** | V1 |
| **Aval — négociation** | « Non, pas de poisson mardi » → réparation locale du plan sans tout recalculer. Plus l'explication d'un choix. | V1 |
| **Hors ligne — enrichissement** | JSON-LD incomplet, proposition de tags et de `suitable_stages`, classification. **Toujours en proposition, jamais en écriture directe.** | Phase 1 |

### 6.5 Le LLM émet des identifiants, jamais de la prose

Sortie d'un plan de semaine : `{slot, recipe_id, member_ids}` ≈ 200-300 tokens ≈ **20-30 s** sur un petit modèle en local.

L'explication (« pourquoi ce plat ») est un **appel séparé, à la demande, sur un seul créneau**.

> **Pourquoi.** Le goulot de génération est la sortie, pas l'entrée. 25 candidats (titre + ingrédients) ≈ 1 500 tokens d'entrée, ingérés en 10-20 s même sur CPU. Faire produire de la prose dans le même appel multiplie la latence par un ordre de grandeur et rend l'endpoint synchrone intenable.

Cette règle rend l'endpoint synchrone parfaitement tenable, y compris sans GPU.

---

## 7. Stack technique

| Couche | Choix | Note |
|---|---|---|
| Backend | **FastAPI** (Python 3.13) | |
| Orchestration agentic | **LangGraph** | Un workflow = un graphe, nœuds réutilisés entre workflows |
| Base de données | **PostgreSQL** + `unaccent` + `pg_trgm` | `pgvector` en option future (recherche sémantique) |
| Migrations | **Alembic** dès le premier schéma | Les phases 1 et 2 modifient le schéma ; une base créée à la main devient infaisable à faire évoluer une fois qu'elle contient de l'historique réel |
| LLM | Interface unique, **3 implémentations** | §7.1 |
| Frontend | **Next.js** (PWA à terme), i18n-ready | Dès la phase 0 |
| Styles | **Tailwind v4**, jetons dans un unique bloc `@theme` | §7.4 |
| Tests front | **Vitest** sur des fonctions pures | §13.4 |
| Conteneurs | **Docker Compose**, services séparés `db` / `api` / `llm` / `web` | Dès le premier commit, même en local |
| Intégration continue | **GitHub Actions** | §13.5 |
| Configuration | **Variables d'environnement uniquement** | Aucune valeur en dur (I8) |

### 7.1 L'interface LLM et ses trois implémentations

```
                    ┌─────────────────┐
                    │  LLMClient      │  interface unique
                    │  (JSON schema)  │
                    └────────┬────────┘
             ┌───────────────┼───────────────┐
             ▼               ▼               ▼
      ┌────────────┐  ┌────────────┐  ┌────────────┐
      │  Ollama    │  │  Cloud API │  │   Fake     │
      │  (dev)     │  │  (prod)    │  │  (tests)   │
      └────────────┘  └────────────┘  └────────────┘
```

> **Trois implémentations réelles = abstraction validée en continu.** Avec une seule implémentation, l'interface reste théorique, et le jour du swap on découvre tout ce qui avait fuité à travers (format des prompts, retries, gestion du JSON, tokenizer).

L'interface expose la **sortie structurée par schéma JSON** (supportée nativement par Ollama et par l'API cloud), pas « un prompt qui demande gentiment du JSON ».

**Signature :**

```python
class LLMClient(Protocol):
    def complete_structured(
        self,
        *,
        instructions: str,        # le rôle, stable → cacheable
        context: str,             # candidats + signaux, variable
        schema: dict,             # JSON Schema, contraint le décodage
        max_attempts: int = 3,
    ) -> StructuredResult: ...


@dataclass(frozen=True)
class StructuredResult:
    data: dict                    # déjà validé contre le schéma
    attempts: int                 # nombre d'essais consommés
    input_tokens: int
    output_tokens: int
    model_id: str                 # ce qui a réellement répondu
    latency_ms: int
```

Quatre choix structurants :

| Choix | Justification |
|---|---|
| **Une seule méthode** | Tout ce que fait le système, c'est produire une structure validée. Pas de `chat()`, `stream()` ni `complete_text()` : ajouter des méthodes « au cas où » est ce qui fait fuir une abstraction. L'explication (§6.5) est elle-même un appel structuré, avec un schéma à un champ. |
| **Le rejeu vit dans l'implémentation** | Sinon chaque nœud du graphe réimplémente sa propre boucle, différemment, et le comptage de tentatives devient inexploitable pour l'éval (§14.5). |
| **`instructions` et `context` séparés** | Le premier est stable et peut être mis en cache par l'API cloud, le second change à chaque appel. Les fusionner en un prompt unique ferme cette porte définitivement. |
| **La télémétrie est dans le type de retour** | `attempts`, tokens, latence, modèle sont exactement ce que le harness d'éval doit agréger. Hors de la valeur de retour, le script d'éval devrait parser des logs. |

Volontairement **absents** : `temperature` (retirée sur les modèles récents, et le déterminisme ne se pilote pas là), `effort` (rejeté par Haiku 4.5), `stream` (le LLM émet des identifiants, il n'y a rien à streamer).

### 7.2 Choix de modèle

| Contexte | Modèle | Justification |
|---|---|---|
| **Développement local** | Un **8B q4** via Ollama (~5 Go) | La machine de dev a 30 Go de RAM dont ~8 disponibles et **pas de GPU**. Un 27B q3 (13 Go) ne tient pas en mémoire : swap, débit sous le token/seconde, poste inutilisable. |
| **Production** | **Claude Haiku 4.5** (1 $ / 5 $ par M tokens) | ≈ **0,3 centime par plan** (1 500 in / 300 out). Supporte les sorties structurées. Ne supporte **pas** le paramètre `effort` — ne pas le câbler comme champ obligatoire. |
| **Secours qualité** | Claude Sonnet 5 | ≈ 0,9 centime par plan |

> **Ce qu'on valide au MVP, c'est la boucle agentic, pas la qualité gastronomique.** Un 8B suffit à prouver que le graphe tourne, que l'arbitrage reste dans l'enveloppe et que la re-validation attrape les sorties invalides. La qualité des menus se réévalue plus tard en swappant le modèle — c'est précisément la raison d'être de l'interface abstraite.
>
> **Principe de conception associé :** c'est au **harness** de garantir le résultat avec un petit modèle (enveloppe de candidats, schéma contraint, re-validation, rejeu). Un gros modèle n'améliore alors que le goût des menus, jamais la fiabilité du système.

Le pré-filtre ne se contente pas de filtrer : il **classe et tronque** à ~15-25 candidats par créneau. Un 8B ne digère pas 200 recettes. C'est le matériel qui l'impose, mais c'est de toute façon une bonne conception.

### 7.3 Décisions d'implémentation de la phase 0

| Sujet | Décision | Justification |
|---|---|---|
| **Ollama** | Reste **sur l'hôte**. Le service `llm` du Compose n'est qu'une URL de configuration. | Ollama est déjà installé en systemd avec un modèle de 5 Go ; le relancer en conteneur dupliquerait le modèle et la RAM. Conforme à I8 : c'est une valeur d'environnement, pas une dépendance en dur. |
| **Périmètre du schéma initial** | Tout le §8 **sauf le catalogue scrapé** : foyer, accès, membres, contraintes, créneaux, coefficients, seuils de stade, plans et historique (avec `free_text_label` pour la V0). | Alembic est là de toute façon, et avoir les tables de plan dès la phase 0 évite une migration au milieu de la V0. |
| **Next.js** | App Router, appels API depuis des Server Components quand c'est possible, `next-intl` pour l'i18n, aucune bibliothèque de composants tierce. | Le front de la V0 est écrit contre le contrat d'API final (§10.3) ; investir en design avant que l'UX soit validée serait du gaspillage. |

### 7.4 Décisions d'implémentation du front

| Sujet | Décision | Justification |
|---|---|---|
| **Sens des appels** | **Lectures depuis les Server Components, écritures depuis le navigateur** vers `/api`, puis `router.refresh()`. Pas de Server Actions. | Une Server Action ferait de Next.js un proxy devant une API **déjà en même origine et déjà authentifiée par le même cookie** : un saut de plus qui n'achète rien, et un second endroit où les erreurs sont retraduites. Quand l'API répond `422 constraint requires a member`, c'est ce message qu'on veut voir. Corollaire : la génération partant du navigateur, le délai de 300 s du `fetch` de Node n'est pas dans le chemin. |
| **Styles** | **Tailwind v4**, jetons dans un unique bloc `@theme`, composants écrits à la main. | La boucle réelle est « je regarde le rendu, je veux changer quelque chose ». Les classes sont écrites textuellement dans le JSX, donc l'ajustement local n'a aucune indirection ; et les modifications systématiques (« resserre tous les espacements ») se font sur le jeton, en un endroit lisible. Le danger réel de Tailwind est la duplication — la parade est la discipline de composants, pas du CSS. |
| **Pas de bibliothèque de composants** | Ni shadcn/ui, ni Radix, ni Mantine. | Elles apportent une apparence de tableau de bord qu'il faudrait défaire pour un produit dont l'identité est une grille de semaine. La seule chose que Radix achèterait vraiment ici — un `Dialog` accessible — est couverte par l'élément **`<dialog>` natif** : piège de focus, Échap, `aria-modal` et blocage du scroll, sans dépendance. |
| **Aucune chaîne en dur** | Ni français ni anglais dans un composant : clés `next-intl` ou texte reçu en props. | Le §12.1 l'impose déjà pour l'affichage ; l'appliquer aux composants **sans exception** évite d'avoir à les fouiller le jour de la traduction anglaise. |
| **`"use client"` le plus bas possible** | Un composant d'affichage reste rendu côté serveur ; seul l'élément interactif bascule. | Sinon la décision « lectures serveur » se vide de son sens : un `"use client"` haut placé fait basculer tout l'arbre en dessous. |

---

## 8. Modèle de données cible

Identifiants en anglais, sans accents. Schéma indicatif — Alembic fait foi.

### 8.1 Foyer et membres

```sql
household(id, name, created_at)

household_access(auth_subject, household_id, created_at)
-- auth_subject est PRÉFIXÉ par le mécanisme : 'google:117482…', 'password:antonin'
-- Plusieurs lignes par foyer (les deux parents). Aucun secret, aucune donnée personnelle.

member(id, household_id, display_name, birth_date,
       life_stage,                     -- valeur EFFECTIVE, confirmée par le parent
       life_stage_confirmed_at,
       created_at)

-- enum life_stage: 'baby' | 'young_child' | 'teen_adult'
-- birth_date ne sert qu'à CALCULER une proposition de transition.
-- Si f(birth_date, seuils) != life_stage → transition en attente, à confirmer (§4.3).

life_stage_threshold(life_stage, upper_bound_months)   -- 18 / 132 / NULL, configurable

dietary_constraint(id, member_id,
                   allergen_code,      -- l'un des deux renseigné
                   ingredient_id,
                   severity,           -- 'severe_allergy'|'intolerance'|'aversion'
                   note)

meal_slot_config(household_id, day_of_week, meal_type, enabled)
-- enum meal_type: 'lunch' | 'dinner'

portion_coefficient(life_stage, coefficient)   -- configurable, pas codé en dur

household_settings(household_id, snacks_enabled, max_dishes_soft_limit, ...)
```

### 8.2 Catalogue

```sql
recipe(id, title, source_url, source_type,      -- 'user'|'scraped'|'licensed_api'
       prep_minutes, cook_minutes, complexity,
       servings, instructions_url,               -- jamais le texte des instructions (I9)
       allergens_verified,                       -- DÉRIVÉ (I3)
       last_checked_at,                          -- re-vérification périodique des liens
       created_at)

recipe_suitable_stage(recipe_id, life_stage)     -- l'ensemble de §4.3

recipe_allergen(recipe_id, allergen_code)        -- source du filtre dur (I2)

recipe_ingredient(recipe_id, position,
                  quantity, unit,
                  raw_text,                      -- toujours conservé
                  ingredient_id)                 -- NULL = non résolu

recipe_food_category(recipe_id, food_category_id)

ingredient(id, canonical_name, normalized_name)  -- normalized: lower + unaccent + singulier
ingredient_allergen(ingredient_id, allergen_code)
ingredient_food_category(ingredient_id, food_category_id)

food_category(id, code, label)
-- legumes_secs, fish, red_meat, white_meat, starch, green_vegetable, dairy, egg, ...
```

**Codes allergènes (14, INCO)** : `gluten`, `crustaceans`, `eggs`, `fish`, `peanuts`, `soybeans`, `milk`, `nuts`, `celery`, `mustard`, `sesame`, `sulphites`, `lupin`, `molluscs`.

### 8.3 Plans et historique

```sql
meal_plan(id, household_id, week_start, generated_at, generation_input)

planned_dish(id, meal_plan_id, day, meal_type,
             recipe_id,                 -- NULL en V0
             free_text_label,           -- utilisé en V0
             source,                    -- 'catalog' | 'llm_suggestion'
             position)

planned_dish_member(planned_dish_id, member_id)   -- l'assignation de §4.1

meal_history(id, household_id, member_id, eaten_on, meal_type,
             recipe_id, free_text_label, source, rating)
```

> `planned_dish_member` est ce qui rend l'anti-répétition **par membre** possible — la seule granularité correcte.

### 8.4 Goûters

```sql
snack_suggestion(id, household_id, suggested_on, label, recipe_id, source)
```

Objet séparé (§4.8).

---

## 9. API

**Une façade FastAPI unique** côté frontend, qui route en interne vers les workflows. Pas d'API séparée par workflow technique. Endpoints orientés métier.

Le contrat détaillé et sa justification sont dans **`UX-V0.md` §13** — c'est l'UX qui le définit (§10.3), pas l'inverse.

| Endpoint | Phase |
|---|---|
| `POST /meal-plans/interpret` — texte libre → contraintes structurées, montrées et corrigeables | V0 |
| `POST /meal-plans` — **une seule opération paramétrée** : portée (semaine \| créneau) + convives (membres \| invités transitoires) | V0 (bouchonné) → V1 (réel) |
| `GET /meal-plans?week_start=…` — la vue charge un plan existant, elle ne dépend pas de la réponse de génération | V0 |
| `GET …/dishes/{id}/alternatives` — candidats écartés, **aucun appel LLM** | V0 (vide) → V1 |
| `PUT …/dishes/{id}` — remplacement, écriture immédiate | V0 |
| `POST …/dishes/{id}/regenerate` — réparation dirigée, avec la raison | V0 |
| `POST …/dishes/{id}/rating` — amorce le score d'appétence et confirme implicitement | V0 |
| `GET …/dishes/{id}/explanation` — appel LLM séparé | **V1** — en V0 il n'y aurait rien de réel à expliquer |
| `GET`/`POST` `/household/constraints` — **pas** imbriqué sous un membre : une aversion peut n'en avoir aucun | V0 |
| `GET`/`PATCH` `/household/settings` — goûter, limite souple de plats, et `onboarded_at` | V0 |
| `POST /meal-plans/snack` | Phase 3 |
| `POST /meal-plans/leftover-rescue` | Phase 4 |
| CRUD `households`, `members`, `recipes` | Phases 0-1 |

> **Il n'y a pas d'endpoint « invités ».** Le mode invités est la même génération avec une portée d'un créneau et des convives transitoires. Deux endpoints partageant 90 % de leur logique divergent toujours : une correction appliquée à l'un, oubliée sur l'autre.

**Synchrone d'abord.** Bascule en asynchrone (job + polling/websocket) seulement si la latence mesurée le justifie. La règle « le LLM émet des identifiants » (§6.5) rend le synchrone tenable.

> **Latence mesurée.** Une semaine complète prend **182 s sur `qwen3:8b` en local**
> — dont deux tentatives, l'enveloppe ayant rejeté la première proposition — contre
> une trentaine de secondes attendues du modèle cloud. Un facteur six entre les deux
> déploiements : **tout seuil d'interface lié à cette durée vient de la
> configuration** (I8), jamais du code.
>
> Le synchrone reste tenable parce que le chemin est navigateur → Caddy → FastAPI,
> et qu'aucun des deux n'impose de délai de réponse. Conséquence à assumer :
> `generate_plan` ne fait qu'un `commit`, après le retour du modèle, et l'endpoint
> synchrone n'est pas notifié d'une déconnexion — **un client qui abandonne
> n'interrompt rien.** L'interface le dit plutôt que de prétendre annuler
> (`UX-V0.md` §7).

**`household_id` n'apparaît dans aucune signature d'endpoint** — il vient de l'identité (I6).

---

## 10. Trajectoire

### 10.1 Phasage

| Phase | Back | Front | Sortie |
|---|---|---|---|
| **0 — Fondations** | Repo, Docker Compose (`db`/`api`/`llm`/`web`), config env, schéma DB initial, Alembic, auth, interface LLM à 3 implémentations | Squelette Next.js, i18n-ready | — |
| **0-bis — V0** | Graphe agentic complet, **coutures bouchonnées**, historique | **Conception UX, puis les six écrans du `UX-V0.md` §14 dans l'ordre**, écrits contre le contrat d'API final | **En ligne, usage interne** |
| **1 — Catalogue** | Scraper (blogs whitelistés, JSON-LD) + référentiel d'ingrédients + CRUD recettes utilisateur | — (back pur) | **300 recettes à ingrédients résolus** |
| **2 — V1** | Workflow semaine réel : filtres durs, signaux, arbitrage, re-validation + harness d'éval | Branchement sur les vrais endpoints | **MVP testable sur le fondateur** |
| **3** | Workflows goûter et invités (réutilisation des nœuds) | Extension | — |
| **4** | Anti-gaspi + saisie manuelle du frigo, puis scan photo | Extension | — |
| **5** | — | Polissage : design, offline, installation PWA | — |

### 10.2 La V0 : un spike d'architecture

En V0, le LLM propose des **titres de plats** en texte libre (« poulet aux olives », « tarte courgettes feta »), sans catalogue.

**Conséquence mécanique : plus aucune garantie déterministe.** Pas de référentiel → pas de filtre allergène. Pas de `suitable_stages` → pas de contrôle d'âge.

C'est acceptable **à une condition** : que ce soit un spike, utilisé par le fondateur seul, jamais montré à un autre foyer, avec mention explicite qu'aucune garantie allergène n'existe.

> **Tension à trancher explicitement.** L'ordre de construction du front a été choisi
> **pour faire tester l'app par d'autres personnes** — ce que la condition ci-dessus
> interdit. Les deux ne peuvent pas être vrais en même temps.
>
> La résolution retenue n'est pas de renoncer aux testeurs, mais de **déplacer la
> mention hors de ce document** : tant qu'aucun catalogue n'existe, l'interface
> affiche elle-même, à l'endroit où les allergies se saisissent et sur le plan
> généré, que **les allergies déclarées ne sont pas filtrées** et que les plats
> proposés ne sont vérifiés par personne. Une garantie absente qui n'est écrite que
> dans un fichier d'architecture n'a jamais protégé un enfant allergique.
>
> Cette mention disparaît en V1, quand le filtre devient réel (I2, I3).

Deux garde-fous :

1. **La V0 garde la forme finale, même à vide.** Le graphe est déjà `pré-filtre → signaux → arbitrage → re-validation`. Le pré-filtre est un **bouchon** qui renvoie « aucune contrainte » ; il n'est **pas contourné**. Les coutures existent dès le premier commit. Passer en V1, c'est remplacer deux implémentations derrière des interfaces déjà en place — pas réécrire le graphe.
2. **Rien de ce que produit la V0 n'entre au catalogue** (I7).

Bénéfice non négligeable : l'historique de la V0 est le **meilleur seed de catalogue**. Après trois semaines d'usage, on sait quels plats reviennent réellement, et on saisit ceux-là — au lieu de deviner 50 recettes dans le vide.

**Le risque à surveiller est humain, pas technique** : une V0 qui marche « à peu près » devient la V1 par inertie, et la couche de sécurité n'atterrit jamais.

### 10.3 UX et contrat d'API

L'UX du workflow semaine **est** la décision produit, et elle **définit le contrat d'API** :

| Décision d'UX | Ce qu'elle impose côté back |
|---|---|
| « Je veux changer juste ce plat-là » | Endpoint de **re-planification partielle** |
| « Je décris ma semaine en une phrase » | Nœud de **parsing d'intention** |
| « Pourquoi ce plat ce soir ? » | Endpoint **explication** à la demande |
| « Le petit ne mange pas ça » | **Négociation par membre**, pas par créneau |

D'où la décision : **l'UX se conçoit en phase 0-bis, contre un back bouchonné.** C'est rapide, ça ne coûte rien, et ça garantit que l'API est dessinée dans le bon sens.

**Garde-fou :** le front est écrit contre le **contrat final**, jamais contre les particularités du bouchon. Sinon les hypothèses du stub finissent codées en dur dans le front.

---

## 11. Sécurité, données personnelles, contenu

### 11.1 Authentification

**Une authentification réelle dès la V0. Pas de solution d'attente.**

| Décision | Choix |
|---|---|
| Mécanisme | **OAuth Google**, portée `openid email profile` (non sensible) |
| Où vit l'auth | **Dans FastAPI**, jamais au reverse-proxy |
| Session | **Cookie signé `HttpOnly`, `SameSite=Lax`, `Secure`** |
| Topologie | **Origine unique** derrière le proxy : `/` → Next.js, `/api` → FastAPI |
| Rôle du proxy | **Terminaison TLS uniquement** |

> **Pourquoi l'auth n'est pas au proxy.** Avec un proxy qui authentifie et injecte un en-tête (`X-Auth-User`), l'API **croit sur parole** ce que l'en-tête lui dit. Or le conteneur `api` est joignable autrement : sur le réseau Docker, et sur le port exposé en local. Forger l'en-tête donne alors un accès complet — c'est l'IDOR de I6 déplacé d'un cran.
>
> Pire, plus insidieux : **en développement, on tape l'API directement**, donc le chemin d'authentification ne serait jamais exécuté en dev. On développerait des mois sur un système sans auth, et la première exécution réelle de ce code serait en production. Même mode de défaite que le validateur jamais testé (§13.1).

> **Pourquoi Google plutôt que magic link.** Le magic link *paraît* plus simple mais ramène un service d'envoi d'emails, un domaine avec SPF/DKIM et de la délivrabilité à surveiller — et la délivrabilité est précisément la pièce sur laquelle on a le moins de prise : un email de connexion en spam, c'est un utilisateur bloqué dehors, découvert par un message et non par une alerte. Le client OAuth se configure une fois, en une heure.

> **Pourquoi une origine unique.** Sur deux origines, le cookie devient tiers : il faut du CORS avec `credentials`, du `SameSite=None`, et un combat permanent contre des protections navigateur qui se durcissent chaque année. Gratuit à faire maintenant, pénible à corriger après.

> **Pourquoi pas de jeton en `localStorage`.** Lisible par n'importe quel script injecté, avec des données de santé derrière.

**`auth_subject` est préfixé par le mécanisme** — `google:117482…`, `password:antonin`, `email:antonin@…`.

> **Pourquoi.** Sans préfixe, deux mécanismes finiront par produire la même chaîne pour deux personnes différentes. Avec, ajouter un mécanisme se réduit à écrire une fonction de vérification qui renvoie un `auth_subject` : **ni endpoint, ni requête, ni test ne bouge**. Coût aujourd'hui : un préfixe dans une chaîne.

**Invariant I6** dans tous les cas : une dépendance FastAPI résout `auth_subject → household_id`, et tout accès porte un `WHERE household_id = :current`. `household_id` n'apparaît dans aucune signature d'endpoint.

#### Sur l'ajout ultérieur d'un login mot de passe

Techniquement indolore grâce au préfixe. Mais « sans compromis de sécurité » a un prix, et il ramène l'email :

| À ajouter | Difficulté |
|---|---|
| Stockage en argon2id | Standard |
| Limitation de débit et anti-bourrage d'identifiants | Modéré |
| Vérification contre les bases compromises (HIBP, k-anonymat) | Facile, souvent oublié |
| **Réinitialisation du mot de passe** | **Nécessite un envoi d'email** |

Un login mot de passe sans réinitialisation est intenable en support. Donc « ajouter le mot de passe » signifie en pratique « ajouter le mot de passe *et* l'infrastructure email ».

**Décision : ne l'ajouter que si un utilisateur réel le réclame.** Chaque mécanisme supplémentaire est de la surface d'attaque en plus pour zéro valeur produit.

### 11.2 Données personnelles

Le système stocke des **dates de naissance de mineurs** et des **allergies** (données de santé, RGPD art. 9).

- Légitime au regard de la finalité, mais durcit les obligations dès la phase 0.
- **Interdit** d'envoyer ces profils tels quels à une API LLM tierce → **invariant I5** (minimisation au niveau du prompt).
- Repli possible si l'on veut éviter la date de naissance : stocker un **âge en mois à une date de référence** et le faire vieillir. Moins précis, même bénéfice fonctionnel.

### 11.3 Politique recettes

**Décision ferme : les recettes ne sont pas générées par IA.**

| Source | Traitement |
|---|---|
| **Contenu utilisateur** | Cœur du catalogue. Les familles saisissent et gardent leurs propres recettes. Seule source possible pour le stade `baby`. |
| **Blogs externes** | **Métadonnées structurées uniquement**, extraites du JSON-LD `schema.org/Recipe` (ingrédients, quantités, temps, tags — des faits). **Redirection vers la source.** Jamais de republication du texte ni de la prose (I9). |
| **API sous licence** (Spoonacular, Edamam) | Complément éventuel. |

**Re-vérification périodique** des liens et contenus du catalogue : les blogs changent ou suppriment des pages. Sans ce mécanisme, l'index dérive silencieusement. Colonne `recipe.last_checked_at`, tâche planifiée.

### 11.4 Deux familles d'agents distinctes

1. **Workflows en ligne** (à la demande utilisateur) — graphes LangGraph, lisent un index **déjà construit**, ne scrapent **jamais** en direct.
2. **Pipeline d'alimentation du catalogue** — **tâche d'arrière-plan planifiée** (cron), découvre/extrait/classe depuis des blogs whitelistés, indépendante du trafic utilisateur.

---

## 12. Conventions

### 12.1 Langue

- **Tout le code en anglais** : identifiants, tables, colonnes, énumérations, commentaires, noms de tests.
- **Documentation et échanges d'équipe en français.**
- **Front en français d'abord, i18n-ready dès la phase 0** : aucune chaîne affichée en dur, tout passe par la couche de traduction.
- Les concepts franco-français (le goûter au premier chef) sont des **modules optionnels**, jamais câblés dans le noyau.

### 12.2 Structure du dépôt

```
meal-planner/
├── docker-compose.yml
├── .env.example
├── docs/
│   └── ARCHITECTURE.md          ← ce document
├── api/                          FastAPI + LangGraph
│   ├── domain/                   entités, règles, invariants — sans I/O
│   ├── infrastructure/           SQL, clients LLM, scraper
│   ├── workflows/                graphes LangGraph
│   ├── routers/                  façade HTTP
│   ├── migrations/               Alembic
│   └── tests/
├── web/                          Next.js
│   └── src/
│       ├── app/[locale]/         écrans — assemblent, ne stylent rien
│       ├── components/
│       │   ├── ui/               ne sait RIEN du domaine
│       │   └── <feature>/        plan/, members/, constraints/…
│       ├── lib/
│       │   ├── api/types.ts      miroir du contrat, source unique
│       │   ├── api/server.ts     lectures depuis les Server Components
│       │   ├── api/client.ts     écritures depuis le navigateur
│       │   └── api/error.ts      `ApiError`, partagé par les deux
│       └── styles/globals.css    le bloc @theme, seul endroit des jetons
├── db/                           init, seed du référentiel d'ingrédients
└── eval/                         fixtures figées + script d'évaluation
```

**La bibliothèque de composants a deux étages, et une seule règle les tient :
`components/ui/` n'importe jamais `lib/api`.** Dépendance unidirectionnelle,
vérifiable d'un coup d'œil et vérifiée en CI. Le jour où un `Button` connaît un
`LifeStage`, la bibliothèque est morte — c'est toujours comme ça que ça commence.

Les primitives sans domaine (`Button`, `Field`, `Dialog`, `Card`, `EmptyState`,
`Spinner`) sont écrites d'emblée : les deviner ne comporte aucun risque. **Tout ce
qui a une forme métier attend qu'un deuxième écran le réclame** — et la relecture
« qu'est-ce qui vient d'être écrit deux fois » a lieu à la fin de chaque écran,
sans quoi l'extraction reste une intention.

Pas de fichiers `index.ts` de ré-export : ils masquent les cycles d'import et
cassent le découpage. On importe le chemin complet.

### 12.3 Règles de code

- Aucune valeur d'infrastructure en dur (I8).
- Le module `domain/` ne connaît ni SQL, ni HTTP, ni LLM : ce sont des fonctions pures, testables sans base.
- Toute écriture en base passe par une migration Alembic, jamais par un script ad hoc.
- `components/ui/` n'importe jamais `lib/api` — la règle est vérifiée en CI.
- Toute logique dérivée du front vit dans `lib/` sous forme de **fonction pure**, jamais dans un composant : elle survit aux refontes visuelles, et c'est ce qui la rend testable (§13.4).

---

## 13. Tests

### 13.1 Ce que contient la CI

| Couche | Contenu | Nature |
|---|---|---|
| **1. Noyau déterministe** | Filtres allergènes, `suitable_stages`, coefficients de portion, signaux de rotation, clustering | Tests unitaires classiques. **Couverture sérieuse : c'est là que vit la sécurité.** |
| **2. Enveloppe** | Le LLM est remplacé par l'implémentation **Fake**, qui renvoie des sorties **hostiles** | Le harness |

Sorties hostiles à injecter obligatoirement :

- une recette absente de l'ensemble de candidats,
- un créneau manquant,
- un membre assigné à un plat qui viole son allergène,
- du JSON mal formé,
- un plat en double,
- un membre assigné à zéro ou deux plats.

Les tests vérifient que le validateur **rejette et rejoue**.

> **Sans tests qui injectent des sorties LLM invalides, le code de re-validation n'est jamais exécuté avant le jour où il compte. Il sera faux.** C'est le mode de défaite classique de cette architecture : le validateur existe, personne ne l'a jamais vu rejeter quoi que ce soit, et il laisse passer.

### 13.2 Ce que la CI ne contient pas

**Aucun appel LLM réel.** C'est lent, coûteux, instable, et ça ne teste rien de reproductible.

### 13.3 Le Fake est un citoyen de première classe

L'implémentation factice est la **troisième implémentation** de l'interface LLM (§7.1), au même titre qu'Ollama et l'API cloud. Une interface avec trois implémentations réelles ne fuit pas.

### 13.4 Le front : des fonctions pures, rien d'autre

La quasi-totalité des écrans est de la présentation. Ce qui porte réellement de la
logique se compte : la résolution de la vue (cookie + media query), le regroupement
des plats par créneau et la détection de divergence, la localisation des violations
sur les créneaux, et la logique d'attente (seuil de bascule, plafond
d'interrogation).

**Ces logiques vivent dans `lib/` sous forme de fonctions pures, et ce sont les
seules choses testées** — avec Vitest, en quelques lignes.

| Écarté | Pourquoi |
|---|---|
| **Tests de rendu** | Ils affirment du balisage sur une interface qu'on ajustera dès qu'on la verra. Ils seraient réécrits à chaque itération visuelle, c'est-à-dire souvent, et maintenant. |
| **Bout en bout (Playwright)** | Exigerait une pile qui tourne, **une session OAuth Google réelle** — notoirement pénible à automatiser — et un LLM disponible. Beaucoup de machinerie pour vérifier ce qu'on constate en ouvrant l'app. |

L'intérêt de cette contrainte dépasse le test : **sortir ces logiques des composants
est une meilleure architecture que le test n'est un test.** Le composant peut
changer trois fois, la fonction reste.

### 13.5 L'intégration continue

GitHub Actions, sur chaque poussée : `ruff` et `pytest` côté API, `tsc --noEmit`,
`next lint` et `vitest` côté web, plus la vérification de la règle d'import du
§12.3.

**Pas de déploiement automatique.** Il suppose des décisions non prises — où, comment
les secrets circulent, ce qui déclenche `alembic upgrade head`, ce qui se passe s'il
échoue au démarrage. Automatiser un déploiement qu'on n'a jamais fait à la main est
la façon classique de se retrouver avec une panne qu'on ne sait pas diagnostiquer.
On le fera à la main d'abord, on l'automatisera quand il sera ennuyeux.

> **Pourquoi maintenant et pas plus tard.** À partir du moment où quelqu'un d'autre
> ouvre l'app, une régression non vue lui arrive dessus. Et le front ajoute une
> deuxième chaîne d'outils : cinq commandes à lancer à la main avant chaque
> poussée, c'est la discipline qui s'érode en premier — pile quand on itère vite
> sur le rendu.

---

## 14. Évaluation

Hors CI. Objectif : **comparer des modèles** (Ollama 8B vs Haiku 4.5 vs Sonnet 5) et détecter les régressions de prompt.

### 14.1 Jeu de données figé

Fixtures **commitées** dans `eval/` : un catalogue de référence + une dizaine de foyers couvrant les cas intéressants (bébé seul, allergie sévère, intolérance forçant un 2ᵉ plat, ado + jeune enfant, foyer sans contrainte).

> **Pourquoi figé.** Un banc d'essai qui tape sur la base de production ne permet **aucune comparaison dans le temps** : le catalogue grossit, l'historique change, et le score d'octobre n'est pas comparable à celui de décembre. On croirait avoir changé de modèle alors qu'on a changé de données.

### 14.2 Golden à trois sections

Chaque cas de test contient trois clés distinctes.

**1. `expected_exact` — le noyau déterministe.** Égalité stricte, un diff, un échec net. **C'est ici que les garanties de sécurité sont vérifiées.**

```yaml
case: household_severe_peanut_allergy
expected_exact:
  candidates_after_filters: [r_012, r_037, r_041, r_055]
  portions_monday_dinner: { teen_adult: 1.0, young_child: 0.5 }
  minimum_feasible_clusters: 2
```

**2. `expected_properties` — la couche LLM.** Invariants durs et taux.

```yaml
case: household_severe_peanut_allergy
runs: 5
expected_properties:
  allergen_violations: 0          # dur, 0 toléré
  dishes_outside_candidates: 0    # dur, 0 toléré
  distinct_dishes_per_slot: <= 3
  legumes_signal_followed: >= 4/5 # souple, un taux
```

**3. `human_reference` — plan de référence écrit à la main.** Ne fait échouer aucun test ; sert de base de comparaison (§14.4) et de repère de lecture pour juger l'appétence.

### 14.3 N runs par cas

**5 runs minimum par cas. Taux, jamais un booléen.**

> Un run par cas ne mesure rien sur un système stochastique : le même modèle sur le même cas peut réussir puis échouer. **Un golden qui passe une fois sur deux et qu'on relance jusqu'au vert est pire que pas de golden — il donne une confiance fausse.**

### 14.4 Distance à la référence humaine

**Ce qu'il ne faut PAS scorer : l'identité des recettes.** Un plan qui ne partage aucune recette avec la référence peut être tout aussi bon — c'est même le comportement souhaité. Un Jaccard sur les `recipe_id` pénaliserait exactement ce qu'on veut encourager.

**Score composite sur trois distances, toutes déterministes :**

| Distance | Calcul | Ce qu'elle capture |
|---|---|---|
| **Structurelle** | Écart sur le nombre de plats distincts par créneau + le motif d'assignation | Les mêmes arbitrages de recouvrement |
| **Catégorielle** | Distance L1 entre les deux vecteurs de `food_category` sur la semaine | Une semaine **équivalente** sans les mêmes plats — la plus utile |
| **Effort** | Écart sur le temps de préparation cumulé et le nombre de recettes complexes | Le respect de la contrainte de charge |

Le **Jaccard** sur les recettes est **affiché mais hors score** (0 % = le modèle explore ailleurs, 100 % = il a recopié).

### 14.5 Métriques rapportées

| Métrique | Ce qu'elle dit |
|---|---|
| Taux de sortie valide au 1ᵉʳ essai / nombre de rejeux | **La métrique du harness.** Un petit modèle qui rejoue 3 fois coûte plus qu'un gros qui réussit du premier coup |
| Sorties hors enveloppe | Le validateur travaille-t-il, et combien |
| Plats distincts par créneau | L'objectif de recouvrement (§4.2) |
| Répétitions sur 4 semaines | L'anti-répétition |
| Signaux souples suivis | Le LLM lit-il le contexte |
| Latence, tokens, coût par plan | La comparaison économique |
| Appétence (1-5, **saisie humaine**) | La seule métrique non automatisable |

### 14.6 Ce que `qwen3:8b` fait et ne fait pas — mesuré

Premier essai réel du wedge : un foyer `teen_adult` + `young_child` + `baby`, neuf
créneaux, aucune contrainte. Trois générations successives, en corrigeant le prompt
entre chacune. **Les résultats à conserver, parce qu'ils orientent le harness :**

| Mesure | Avant | Après correction du prompt |
|---|---|---|
| Créneaux avec variante de service | 0 / 9 | **9 / 9** |
| Plats dupliqués dans un même créneau | 3 par créneau | 0 |
| Plats distincts sur la semaine | 1 / 9 | **1 / 9** |
| Violations | 0 | 0 |

Deux enseignements qui ne se devinent pas :

**Le modèle connaissait les stades de vie et n'en faisait rien.** Le contexte
envoyait bien `stage=baby` ; les instructions ne disaient nulle part ce qu'un
stade *implique* pour une assiette. Face à la règle « préférer moins de plats
distincts », servir un poulet rôti à un nourrisson satisfaisait parfaitement la
consigne. Le vocabulaire des stades étant fixe, il appartient aux instructions —
donc à la partie cacheable — et non au contexte.

**Il a ensuite exprimé la variante en fabriquant trois plats de titre identique**,
au lieu de remplir `serving_variants`. Décrire un mécanisme en prose ne suffit
pas : il a fallu **nommer le champ et montrer la forme JSON attendue**. C'est une
défaillance de compréhension du schéma, pas du domaine — et le validateur
l'acceptait, trois plats pour trois mangeurs restant sous la limite.

**Ce qui résiste : la non-répétition.** Neuf créneaux, le même plat neuf fois,
malgré une règle explicite et non ambiguë. C'est le plafond du 8B sur cette tâche,
pas un trou de prompt. La comparaison avec Haiku 4.5 sur ce cas précis est le
premier travail du harness — et **le chemin Anthropic n'a jamais été exercé contre
la vraie API**, ce qui en fait un préalable, pas une conclusion.

### 14.7 LLM-juge : repoussé

Un modèle qui note le plan généré face à la référence capte des choses que les distances ratent. Mais c'est du non-déterministe qui évalue du non-déterministe, il faut le valider lui-même, et il demande un modèle **plus gros** que celui testé — donc plus cher que ce qu'il évalue.

**Phase ultérieure, et jamais comme unique porte de sortie.**

---

## 15. Décisions repoussées

| Sujet | Statut |
|---|---|
| Score d'appétence par membre (goûts + historique) | Phase 3+ — le construire trop tôt, c'est calibrer sur du vide |
| `pgvector` / recherche sémantique | Option future |
| Désactivation de membres par créneau à la génération | Échappatoire connue, sans nouvelle table, non retenue au MVP |
| LLM-juge dans le banc d'essai | Phase ultérieure |
| Passage en asynchrone (job + polling) | Seulement si la latence mesurée le justifie |
| Facturation, multi-foyer réel, gestion de comptes | Après validation du wedge |
| Version anglaise du produit | Demande un catalogue distinct, pas seulement des libellés |
| Login par identifiant / mot de passe | Indolore techniquement (`auth_subject` préfixé), mais ramène l'infrastructure email via la réinitialisation. Seulement si un utilisateur réel le réclame (§11.1) |
| Stades de vie supplémentaires (`toddler`…) | Seulement si le score d'appétence révèle qu'un stade manque (§4.3) |

---

## 16. Résumé des invariants

À relire avant toute PR structurante.

| # | Invariant |
|---|---|
| **I1** | Aucune décision de sécurité n'est prise par un LLM |
| **I2** | Le filtre allergène porte sur des tags vérifiables, jamais sur du texte libre |
| **I3** | `allergens_verified` est dérivé, jamais déclaré |
| **I4** | Le matching approché ne s'applique jamais sans confirmation humaine |
| **I5** | Le constructeur de prompt ne reçoit jamais l'entité `member` |
| **I6** | `household_id` est dérivé de l'identité authentifiée |
| **I7** | Aucun contenu généré par IA n'entre au catalogue |
| **I8** | Aucune dépendance technique n'est codée en dur |
| **I9** | Aucune republication de contenu externe |
