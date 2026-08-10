# UX de la V0 — décisions et contrat d'API

> **Statut** : document de phase. Il décrit l'interface de la **V0** (phase 0-bis) et
> le contrat d'API qu'elle impose. Contrairement à `ARCHITECTURE.md`, il n'est pas
> censé survivre au produit : la V1 le remplacera.
> **Dernière révision** : 2026-08-07

`ARCHITECTURE.md` §10.3 pose que **l'UX définit le contrat d'API**. Ce fichier est
l'application de ce principe : chaque décision d'interface y est suivie de ce
qu'elle impose au back.

---

## 1. Le modèle mental

**Le plan est une banque de suggestions, pas un engagement.**

L'usage réel est double :

| Moment | Contexte | Besoin |
|---|---|---|
| Générer la semaine | Assis, au calme | Vue d'ensemble, ajustements |
| « C'est quoi jeudi ? » | Debout dans la cuisine | Une réponse, en deux secondes |

Le second moment n'est pas une consultation de contrôle : c'est *« je n'ai plus
d'idée, qu'est-ce que j'avais prévu ? »*. D'où trois règles d'interface :

- **Aucune notion d'écart.** Pas de « vous avez dévié du plan », pas de taux de
  respect, pas de case qui reproche.
- **La nouveauté est suggérée, jamais imposée.** L'anti-répétition reste un
  signal (`ARCHITECTURE.md` §6.3), y compris dans ce que l'interface raconte.
- **Rien ne bloque.** Aucun écran n'est un péage vers un autre.

À côté de la semaine, une **génération à la demande sur un seul créneau** — c'est
aussi le mode invités (§4 ci-dessous).

---

## 2. Deux vues, pas une vue redimensionnée

| Vue | Répond à | Forme |
|---|---|---|
| **Grille** | « Comment s'organise ma semaine » | 7 jours × créneaux, tout visible |
| **Liste** | « Qu'est-ce que je fais maintenant » | Une colonne, centrée sur aujourd'hui |

Ce sont **deux vues du même objet**, pas la même vue à deux tailles. Les dériver
l'une de l'autre par des media queries donne les deux en moins bien.

**La taille d'écran fixe le défaut, elle n'impose rien.** Les deux vues sont
accessibles partout : planifier le dimanche soir depuis le canapé avec un
téléphone est un usage réel, et un design purement piloté par point de rupture
l'interdirait. Le basculement est mémorisé **pour la session seulement** — rouvrir
en grille le lendemain matin dans la cuisine serait contre-productif.

> **Conséquence API.** La vue « aujourd'hui » ne doit pas télécharger sept jours
> pour afficher un plat, et la vue semaine doit survivre à un rechargement. D'où
> `GET /meal-plans?week_start=…`, chargé au montage, plutôt qu'un front qui
> n'affiche que la réponse du `POST` de génération.

---

## 3. L'intention en texte libre est interprétée **à la vue**

Avant de générer, l'utilisateur peut écrire :

> *« Cette semaine on est peu là, mardi je rentre tard, il reste du poulet, et ça
> fait longtemps qu'on n'a pas mangé de légumineuses. »*

Aucun formulaire ne capte ça. Mais l'interprétation n'est **jamais invisible** :

```
Compris :
  · semaine allégée
  · mardi soir → repas rapide (< 20 min)
  · poulet à réutiliser
  · légumineuses souhaitées                        [retirer]
```

L'utilisateur retire ou corrige une ligne, puis lance la génération.

> **Pourquoi pas l'interprétation invisible.** Quand le modèle lit *« mardi je
> rentre tard »* comme *« pas de repas mardi »*, l'utilisateur reçoit un plan faux
> **et ne sait pas pourquoi**. Il ne peut que reformuler à l'aveugle. C'est le mode
> de défaite classique du texte libre : impressionnant en démonstration,
> exaspérant à l'usage.

Trois bénéfices, dont deux dépassent l'UX :

1. **La correction arrive avant l'étape coûteuse** — un clic plutôt qu'une
   régénération de 20-30 secondes.
2. **Le contrat se sépare en deux appels**, et la séparation est la bonne :
   régénérer réutilise les contraintes sans re-parser.
3. **L'interprétation devient testable isolément.** Le harness d'éval
   (`ARCHITECTURE.md` §14) peut comparer les contraintes extraites à des
   contraintes attendues, sur du texte figé, sans jamais générer un plan — un cas
   de test *déterministe dans sa forme* alors que la génération ne l'est pas.

---

## 4. Une seule opération de génération, et le mode invités

Le mode invités n'est pas un workflow séparé : c'est la même génération avec deux
paramètres qui changent, **la portée** et **les convives**.

> **Pourquoi pas deux endpoints.** `/week` et `/guests` partageraient 90 % de leur
> logique et divergeraient : une correction appliquée à l'un, oubliée sur l'autre,
> et six mois plus tard le mode invités a des règles que personne n'a décidées.

### Les invités sont transitoires

**Ils ne deviennent jamais des `member`.** Ajouter ses beaux-parents au foyer
parce qu'ils viennent dîner polluerait le foyer pour toujours : ils compteraient
dans l'anti-répétition, dans les portions par défaut, dans les propositions de
transition de stade. Des gens qui mangent là deux fois par an fausseraient les
menus toute l'année.

Trois règles :

| Point | Règle |
|---|---|
| Stockage | Aucun. Ils existent le temps d'un créneau. |
| Portions | Il faut leur **stade de vie** : « 4 personnes » ne dit pas si ce sont quatre adultes ou deux adultes et deux enfants de 5 ans. |
| Allergies | Déclarables, et **excluent l'allergène du créneau pour tout le monde** — la règle de portée foyer du §4.6, appliquée à un repas. Rien n'est stocké. |
| Goûts | Déclarables, signal souple, comme une aversion. |

Corollaire à assumer : pour ce créneau, le plan n'offre **aucune garantie**
au-delà de ce qui a été déclaré. C'est vrai dans la vraie vie aussi — on demande à
ses invités — mais l'interface ne doit pas laisser croire l'inverse.

---

## 5. L'affichage d'un créneau

**Adaptatif : le cas simple doit avoir l'air simple.**

| Plats sur le créneau | Affichage |
|---|---|
| 1 | Le plat, sans décoration |
| 2+ | Une carte par plat, avec badges de mangeurs |

Si le foyer mange la même chose quatre soirs sur sept, afficher ces soirs-là
« Poulet aux olives — mangé par : Antonin, Camille, Léo, Bébé » transforme une
semaine banale en mur d'informations. Le multi-plats n'apparaît **que là où il y a
divergence** — c'est là que l'information a du sens.

### Les trois niveaux du composant

Il y a **trois façons** de nourrir des personnes aux besoins différents, et
l'interface doit les distinguer parce qu'elles n'ont pas le même coût de cuisine :

| Niveau | Mécanisme | Effort | Phase |
|---|---|---|---|
| 1 | Même plat, même assiette | Une préparation | V0 |
| 2 | **Même préparation, assiette différente** — sans olives pour Léo, part du bébé prélevée avant salage et mixée | **Une préparation** | **V0** |
| 3 | Deux plats distincts sur une base commune | Deux préparations | V1 |

**Le niveau 2 est le meilleur résultat possible du produit** — meilleur que le
niveau 3. Zéro cuisine en plus, et chacun mange ce qui lui convient. C'est
littéralement « je ne veux pas cuisiner deux fois », résolu sans compromis.

C'est aussi une piste sérieuse pour la déclinaison bébé : dans beaucoup de cas ce
n'est pas une recette bébé qui manque, c'est une **instruction de service**.

Le niveau 3 se **dessine maintenant et reste vide en V0** : il exige les
ingrédients, donc le catalogue. Sans ça la V1 redessinerait l'écran principal, et
c'est le seul écran qui compte.

### La variante de service

Portée par **l'assignation**, pas par le plat : deux personnes peuvent avoir des
variantes différentes sur le même plat.

En V0 c'est du texte libre — et c'est produisible **à partir d'un simple titre**,
sans catalogue :

> *Poulet aux olives — pour Léo : sans olives*

En V1 elle deviendra structurée (« retirer l'ingrédient #412 ») ; le texte survit
comme libellé affiché.

> **La frontière de sécurité ne bouge pas.** Le code décide **si** un membre peut
> être assigné à ce plat (`suitable_stages`, allergènes) ; la variante décrit
> seulement **comment** le servir. Une variante ne peut jamais rendre acceptable
> une assignation qui ne l'était pas — sinon le LLM redeviendrait juge de la
> sécurité et I1 tombe.

---

## 6. Refuser un plat

**Jamais de régénération de la semaine.** On perdrait les six autres jours qui
convenaient, pour 20-30 secondes d'attente.

| Ordre | Mécanisme | Coût |
|---|---|---|
| 1 | **Alternatives instantanées** — le pré-filtre a déjà produit 15-25 candidats validés pour ce créneau, en montrer trois autres ne demande **aucun appel LLM** | ~50 ms |
| 2 | **Réparation dirigée** — l'utilisateur dit *pourquoi* (« pas de poisson mardi », « trop long »), et la raison devient une contrainte | un appel LLM, un créneau |

Le premier couvre le cas le plus fréquent : « pas envie de celui-là, montre-moi
autre chose ». Le second est là où vit la négociation d'`ARCHITECTURE.md` §6.4 —
et la raison donnée a de la valeur, elle enrichit les contraintes pour la suite.

**Écriture immédiate, aucun brouillon.** Un plan n'est pas un document : un
mécanisme « modifier puis enregistrer » ajouterait un état, un risque de perdre
ses modifications et un bouton, pour un objet que l'utilisateur ne considère pas
comme un document.

---

## 7. L'attente

Le §6.5 impose **un seul appel LLM pour toute la semaine** — le modèle n'émet que
des identifiants. Il n'y a donc rien à streamer : la sortie arrive d'un bloc,
après 20-30 secondes (davantage sur le 8B local).

**Synchrone**, conformément au §9. Mais l'attente doit être bien faite : 25
secondes de roue qui tourne donnent l'impression que c'est cassé — le seuil où les
gens rechargent est autour de dix secondes.

| Principe | Détail |
|---|---|
| **Annoncer avant, pas pendant** | *« On prépare ta semaine — compte une trentaine de secondes »*, au clic. Une attente annoncée est deux fois plus courte qu'une attente subie. |
| **Messages ludiques** | Ton léger pendant l'arbitrage, dans les fichiers de traduction et jamais en dur. |
| **Ne jamais prétendre une progression** | Ton amusant, oui ; « plus que 20 % », non. Aucune barre factice : une barre qui avance seule puis se bloque à 90 % est pire que pas de barre. |
| **Seuil de bascule** | Passé environ le double du temps attendu, on abandonne le registre amusant : *« c'est plus long que d'habitude »* + annulation. Un message rigolo à la 90ᵉ seconde, quand le modèle est bloqué, est humiliant. |

> **Le risque de l'attente synchrone est déjà couvert.** Si la connexion tombe à
> la 25ᵉ seconde, le plan **a déjà été écrit en base** ; seul le client ne l'a pas
> vu. C'est pourquoi la vue semaine charge par `GET` au montage : un rechargement
> récupère tout.

---

## 8. L'historique se remplit tout seul

**Validation implicite : les plats planifiés dont la date est passée valent comme
mangés.** Aucun écran de saisie, aucune confirmation demandée.

> **Pourquoi pas de confirmation.** Une validation au fil de l'eau demande une
> habitude quotidienne que personne n'a — 18 h dans la cuisine n'est pas un moment
> d'administration. Un écran rétrospectif hebdomadaire serait mieux placé, mais
> resterait un formulaire que la plupart des gens sauteront.
>
> **Et le coût de l'approximation est faible**, parce que l'historique n'alimente
> que des **signaux souples** (§6.3) : un historique bruité ne *supprime* rien, il
> pousse légèrement. Une donnée fausse n'est dangereuse que là où elle décide.

Deux conséquences, gratuites aujourd'hui :

**On garde la distinction supposé / confirmé**, même si rien ne la produit encore
(`meal_history.confirmed_at`, toujours nul en V0). Ce n'est pas de la spéculation :
**noter un plat est une confirmation implicite qu'il a été mangé**. La colonne se
remplira toute seule avec le score d'appétence, sans migration — et le harness
d'éval saura distinguer un cas construit sur de l'historique supposé d'un cas
construit sur du réel. Ce ne sont pas des preuves de même force.

**Aucun job planifié.** La tentation serait un cron qui recopie les plats passés
dans `meal_history` : inutile, et source de dérive silencieuse s'il tombe. Une
seule fonction de lecture **unit** les plats planifiés passés et les éventuelles
lignes explicites. Elle fonctionne avec zéro ligne explicite et fonctionnera
identiquement quand il y en aura.

---

## 9. L'onboarding

**Minimum vital, puis enrichissement.**

> **Pourquoi pas un assistant en quatre étapes.** L'utilisateur n'a **aucune raison
> de faire confiance** au produit à ce stade : il n'a pas encore vu un seul menu.
> Lui demander les allergies de ses enfants avant de lui avoir rien montré est un
> mauvais échange.

| Étape | Contenu | Obligatoire |
|---|---|---|
| 1 | Les membres : **prénom + groupe d'âge** | Oui |
| 2 | « Quelqu'un a-t-il une allergie ? » avec un **« non » cliquable en un geste** | Posée, pas obligatoire |
| 3 | « Ce qu'on n'aime pas ici » — champ libre | Non |

Tout le reste (créneaux, affinage des contraintes) se règle depuis les réglages.

### Groupe d'âge choisi, pas de date de naissance

**Le groupe est saisi directement.** Pas de date de naissance, donc pas de
proposition automatique de transition : la responsabilité du changement revient à
l'utilisateur.

> **Pourquoi c'est acceptable.** Les groupes ne se franchissent que dans le sens
> de l'âge. Un parent qui a saisi `bébé` et n'y revient jamais garde son enfant
> dans le catalogue **le plus restrictif** — agaçant, pas dangereux, et
> **auto-correctif** : il verra des purées proposées à un enfant qui mange comme
> tout le monde et ira changer le réglage. L'erreur inverse demanderait d'avancer
> volontairement le groupe trop tôt, un acte délibéré et non un oubli.
>
> En prime, plus aucune date de naissance d'enfant en base — du RGPD art. 9 en
> moins pour un bénéfice qui se limitait à un rappel automatique.

La machinerie de dérivation reste en place mais **dormante** : `birth_date` est
optionnelle et non collectée, donc aucune proposition n'est jamais produite. Elle
redeviendra utile si l'on veut un jour proposer la date de naissance en option,
contre des rappels automatiques.

### Les allergies ne peuvent pas attendre indéfiniment

Si un foyer avec un enfant allergique génère trois semaines avant de penser à les
saisir, on a proposé trois semaines de plats potentiellement dangereux. En V0 c'est
sans conséquence — ni catalogue, ni garantie, un seul utilisateur — mais la
question doit être **posée une fois, explicitement**, plutôt qu'enfouie dans des
réglages.

---

## 10. Les aversions : un seul concept, membre optionnel

| Saisie | Stockage | Effet |
|---|---|---|
| À l'inscription, champ unique | aversion **sans membre** | Tout le foyer |
| Plus tard, depuis la fiche d'un membre | aversion **avec membre** | Ce membre seul |

**Un seul concept, une seule table, un seul chemin de filtrage.** Deux entités
distinctes produiraient deux comportements et la question « que se passe-t-il
quand elles se contredisent ».

**L'affinage va dans un seul sens** : « personne n'aime les épinards » → « en fait
c'est surtout Léo » est naturel. L'interface propose d'attacher une aversion foyer
à une personne, jamais de détacher.

> **Une aversion par membre est un argument pour un second plat**, donc pour le
> wedge : « Léo n'aime pas le poisson » justifie qu'il mange autre chose le soir du
> poisson. Une aversion au niveau foyer supprime le poisson pour tout le monde —
> elle réduit le problème au lieu de le révéler.

**Seules les aversions peuvent avoir un membre nul.** Une allergie sans personne à
qui elle appartient n'a pas de sens, et sa portée foyer vient déjà de sa sévérité
(§4.6), pas de son stockage. Une contrainte de base le vérifie.

---

## 11. Ce que porte une carte de plat

**Titre · mangeurs si divergence · variantes de service · un pouce facultatif.**

Volontairement pauvre, et deux refus assumés :

**Pas d'explication en V0.** Il n'y a **rien à expliquer** : le pré-filtre est
bouchonné, il n'y a ni candidats écartés ni contrainte appliquée. Le modèle
produirait une justification *plausible et inventée*. Le problème n'est pas
l'inexactitude, c'est ce qu'elle enseigne : on prendrait l'habitude de faire
confiance à des explications au moment précis où elles sont creuses, et on ne
saurait plus les évaluer quand elles deviendront réelles. Une V0 qui ne s'explique
pas est plus honnête qu'une V0 qui se justifie bien.

En V1, avec de vrais candidats et de vrais signaux, l'explication devient
vérifiable — et précieuse, y compris pour déboguer l'arbitrage.

**Pas de métadonnée inventée.** Temps de préparation, difficulté, nombre
d'ingrédients : le modèle peut les produire à partir d'un titre et elles seront
fausses la moitié du temps. Elles viendront du catalogue en V1. Mieux vaut une
carte pauvre qu'une carte qui ment.

**Un pouce, discret et facultatif.** Il amorce le score d'appétence de la phase 3+
— qui se calibre sur de l'historique, donc plus tôt il commence, mieux c'est — et
il remplit `confirmed_at` sans jamais demander de saisie. Rien ne doit en dépendre :
si personne ne clique, le système fonctionne exactement pareil.

---

## 12. Courses et batch cooking

La semaine a été justifiée en partie par « optimiser les courses ou les
préparations en une fois ». Mais la liste de courses est hors MVP (§2.4).

| Phase | Ce qui est montré |
|---|---|
| **V0** | Rien. Sans catalogue il n'y a ni ingrédients ni base commune : la V0 ne peut pas tenir cette promesse, autant ne pas la faire. |
| **V1** | **Le recouvrement, sans liste** — « lundi et jeudi partagent une base ». Aucune quantité, aucune unité, aucun inventaire : c'est la même donnée que le niveau 3 du composant créneau, affichée à l'échelle de la semaine. |
| — | **La liste de courses reste exclue.** Elle exige des quantités justes, des unités normalisées, l'agrégation d'ingrédients hétérogènes et la gestion de ce qu'on a déjà — sinon elle fait racheter du sel toutes les semaines et l'utilisateur cesse de l'ouvrir. |

Progression : **la V0 supprime la décision quotidienne**, la V1 révèle le
recouvrement.

---

## 13. Le contrat d'API

```
# Interprétation
POST /meal-plans/interpret     { text }
                               → { constraints: [ {type, label, value} ] }

# Génération
POST /meal-plans               { scope:  {type:"week",  week_start}
                                        |{type:"slot",  date, meal_type},
                                 member_ids?, guests?, constraints? }
                               → MealPlan

# Lecture
GET  /meal-plans?week_start=…  → MealPlan | null
GET  /meal-plans/{id}          → MealPlan

# Négociation
GET  /meal-plans/{id}/dishes/{dish_id}/alternatives   → candidats écartés
PUT  /meal-plans/{id}/dishes/{dish_id}                → remplacer
POST /meal-plans/{id}/dishes/{dish_id}/regenerate     { reason }
POST /meal-plans/{id}/dishes/{dish_id}/rating         { value }

# Contraintes — plus imbriqué sous /members/{id}
GET  /household/constraints
POST /household/constraints    { member_id?, allergen_code?, label?, severity }
DELETE /household/constraints/{id}
```

Deux choix qui méritent leur justification :

**Les alternatives passent par un endpoint dédié** plutôt que d'être embarquées
dans la réponse de génération. L'intention du §6 était d'éviter une
*régénération*, pas un aller-retour : une requête sans LLM répond en quelques
dizaines de millisecondes. Les embarquer alourdirait la lecture du plan — celle
dont la vue mobile a besoin — et les alternatives disparaîtraient au rechargement.

**Les contraintes sortent de `/members/{id}/constraints`.** Conséquence directe du
§10 : une aversion peut n'avoir aucun membre, donc l'URL ne peut plus être
imbriquée sous un membre.

`household_id` n'apparaît nulle part — il est dérivé de l'identité (I6).

---

## 14. Les écrans

| # | Écran | Contenu |
|---|---|---|
| 1 | Connexion | Bouton Google |
| 2 | Onboarding | Membres, allergies, aversions |
| 3 | Semaine | Grille ou liste, basculable |
| 4 | Génération | Texte libre → interprétation confirmable → attente |
| 5 | Panneau créneau | Alternatives, réparation dirigée, variantes |
| 6 | Réglages | Foyer, membres, contraintes, créneaux |

**Le goûter est hors périmètre V0** : objet distinct (§4.8), workflow propre,
prévu en phase 3. L'inclure doublerait la surface de l'interface pour une
fonctionnalité secondaire.

---

## 15. Ce que la V0 ne peut pas montrer

À garder en tête en la testant : **son silence sur ces points n'est pas un défaut
d'implémentation.**

| Absent | Pourquoi | Arrive en |
|---|---|---|
| Le recouvrement entre plats | Pas d'ingrédients, donc pas de base commune calculable | V1 |
| L'explication d'un choix | Rien de réel à expliquer, le pré-filtre est bouchonné | V1 |
| Toute garantie allergène | Ni référentiel, ni tags vérifiés | V1 |
| Le contrôle d'âge des plats | Pas de `suitable_stages` sans catalogue | V1 |
| Temps, difficulté, quantités | Viendraient du catalogue | V1 |

Ce que la V0 **prouve** en revanche : la boucle agentic complète, l'interprétation
d'intention, l'arbitrage sous enveloppe, la re-validation, les variantes de
service — et que l'interface tient debout.
