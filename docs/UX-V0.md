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

> **Conséquence API.** La vue semaine doit survivre à un rechargement. D'où
> `GET /meal-plans?week_start=…`, chargé au montage, plutôt qu'un front qui
> n'affiche que la réponse du `POST` de génération.
>
> Une version antérieure de ce paragraphe exigeait aussi que la vue « aujourd'hui »
> **ne télécharge pas sept jours** — ce que l'endpoint prescrit juste au-dessus
> fait précisément. La contradiction est levée en faveur de l'endpoint unique :
> une semaine pèse quelques kilo-octets, et un endpoint par jour multiplierait les
> chemins de lecture pour une économie invisible. La question redeviendra réelle
> quand un plat portera ses ingrédients.

### Comment les deux vues coexistent réellement

Le rendu serveur ne connaît pas la taille de l'écran. Trois exigences ci-dessus se
contredisent donc techniquement : deux arbres distincts, un défaut fixé par
l'écran, et un basculement mémorisé.

**Les deux arbres sont rendus, le CSS en masque un.** Sans cookie, le conteneur
porte `data-view="auto"` et la media query tranche : **le tout premier chargement
est correct sur n'importe quel appareil, sans une ligne de JavaScript.**

**Le choix explicite vit dans un cookie de session**, lu côté serveur, qui écrase
la media query. Un cookie sans `Max-Age` meurt avec la fenêtre — c'est
littéralement « la session seulement » — et contrairement à `sessionStorage` il
est lisible au rendu, donc il n'introduit aucun scintillement au rechargement.

Le prix est d'avoir les deux arbres dans le DOM. Avec neuf créneaux c'est
négligeable, et `display:none` sort la vue masquée de l'arbre d'accessibilité.
Cette solution ne tient que tant que les deux vues consomment **la même donnée** —
le jour où la vue liste ne chargera qu'un jour, il faudra que le serveur choisisse.

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

### En V0, le premier mécanisme n'existe pas

Sans catalogue il n'y a pas de candidats écartés : `GET …/alternatives` renvoie une
liste vide. **Le mécanisme que ce paragraphe décrit comme le plus fréquent est donc
absent de la V0**, et l'interface ne l'affiche pas — ni section vide, ni excuse.
Une section désactivée avec une explication apprend qu'il y a une fonctionnalité
cassée, et on cesse d'y regarder, y compris quand elle marche (même raisonnement
qu'au §11 sur l'absence d'explication).

Reste alors une échappatoire que ce paragraphe mentionne à peine et qui devient
centrale : **réécrire le titre du plat à la main.** L'utilisateur sait souvent ce
qu'il veut manger, et le lui laisser écrire est plus rapide que n'importe quelle
négociation avec un modèle.

D'où l'ordre du panneau en V0, du moins cher au plus cher : **titre éditable en
place**, puis *« propose autre chose »* avec la raison. C'est l'inverse de la
hiérarchie V1, où les alternatives passeront devant — et c'est correct, l'ordre
suit le coût réel du moment.

**Écriture immédiate, aucun brouillon.** Un plan n'est pas un document : un
mécanisme « modifier puis enregistrer » ajouterait un état, un risque de perdre
ses modifications et un bouton, pour un objet que l'utilisateur ne considère pas
comme un document.

---

## 7. L'attente

Le §6.5 impose **un seul appel LLM pour toute la semaine** — le modèle n'émet que
des identifiants. Il n'y a donc rien à streamer : la sortie arrive d'un bloc.

**Mesure réelle plutôt qu'estimation.** Une semaine complète — neuf créneaux, trois
mangeurs — a pris **182 secondes sur `qwen3:8b` en local, dont deux tentatives** :
l'enveloppe a rejeté la première proposition et la boucle de réparation a rattrapé.
L'estimation initiale de 20-30 secondes valait pour le modèle cloud, pas pour le
8B. **L'écart entre les deux déploiements est d'un facteur six**, ce qui interdit
tout seuil écrit en dur.

**Synchrone**, conformément au §9. Mais l'attente doit être bien faite : 25
secondes de roue qui tourne donnent l'impression que c'est cassé — le seuil où les
gens rechargent est autour de dix secondes.

| Principe | Détail |
|---|---|
| **Annoncer avant, pas pendant** | *« On prépare ta semaine — compte une trentaine de secondes »*, au clic. Une attente annoncée est deux fois plus courte qu'une attente subie. |
| **Messages ludiques** | Ton léger pendant l'arbitrage, dans les fichiers de traduction et jamais en dur. |
| **Ne jamais prétendre une progression** | Ton amusant, oui ; « plus que 20 % », non. Aucune barre factice : une barre qui avance seule puis se bloque à 90 % est pire que pas de barre. |
| **Seuil de bascule** | Passé environ le double du temps attendu, on abandonne le registre amusant : *« c'est plus long que d'habitude »*. Un message rigolo à la 90ᵉ seconde, quand le modèle est bloqué, est humiliant. **Le temps attendu vient de la configuration** (I8), jamais du code : 30 secondes en ligne, 180 en local. |

> **Le risque de l'attente synchrone est déjà couvert.** Si la connexion tombe à
> la 25ᵉ seconde, le plan **a déjà été écrit en base** ; seul le client ne l'a pas
> vu. C'est pourquoi la vue semaine charge par `GET` au montage : un rechargement
> récupère tout.

### « Arrêter d'attendre », et non « Annuler »

`generate_plan` ne fait qu'un `commit`, après le retour du modèle, et l'endpoint
FastAPI est synchrone : il n'est pas notifié d'une déconnexion. **Un client qui
abandonne n'interrompt rien — le plan sera écrit quand même.**

Un bouton nommé « Annuler » serait donc un mensonge dont l'utilisateur fait les
frais : il relance, se retrouve avec deux générations en vol, et la seconde écrase
la première.

| Règle | Détail |
|---|---|
| **Le bouton s'appelle « Arrêter d'attendre »** | Suivi de *« ta semaine continue de se préparer, elle apparaîtra ici »*. Trois mots de plus, et le problème disparaît. |
| **On rend la main, puis on interroge** | `GET /meal-plans?week_start=…` toutes les cinq secondes jusqu'à l'arrivée du plan. Abandonner l'attente ne perd donc **rien** — c'est meilleur qu'une annulation réelle, qui jetterait un appel LLM déjà payé. |
| **L'interrogation est bornée** | Si le modèle échoue, rien n'est jamais écrit et on interrogerait indéfiniment. Plafond à environ trois fois le temps attendu, puis message d'échec explicite. |
| **Une génération en vol à la fois** | Le bouton reste désactivé tant qu'une génération est en cours pour cette semaine, **y compris après avoir arrêté d'attendre**. Sinon on reconstruit exactement le problème qu'on vient d'éviter. |

Une annulation réelle — signal au serveur, interruption du travail — supposerait de
sortir du synchrone : file de tâches, identifiant de travail, jeton d'annulation.
Hors périmètre V0, et sans bénéfice puisque le résultat arrive de toute façon.

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

| Bloc | Contenu | Obligatoire |
|---|---|---|
| 1 | Les membres : **prénom + groupe d'âge** | Oui |
| 2 | « Quelqu'un a-t-il une allergie ? » avec un **« non » cliquable en un geste** | Posée, pas obligatoire |
| 3 | « Ce qu'on n'aime pas ici » — champ libre | Non |

Tout le reste (créneaux, affinage des contraintes) se règle depuis les réglages.

### Une seule page, trois blocs — pas trois étapes

Ce sont des **blocs sur une même page**, et non les étapes d'un assistant. C'est la
conséquence directe du refus ci-dessus : à ce stade l'utilisateur n'a aucune raison
de faire confiance au produit. **Une page unique montre le coût total d'un coup
d'œil** — *« trente secondes, et c'est tout ce qu'on me demande »*. Un assistant
cache sa longueur : chaque étape franchie peut en révéler une autre, et on ne sait
jamais quand ça s'arrête.

Deux conséquences d'interface :

- **Le bloc allergies s'active quand un membre existe.** Une allergie appartient à
  quelqu'un (§10), donc tant que la liste est vide il n'y a rien à quoi l'attacher.
  La page change de forme à mesure qu'on la remplit — l'ordre devient évident sans
  être numéroté.
- **Le « non » est pré-sélectionné**, pas à cocher. Deux boutons radio dont
  « personne ici n'a d'allergie » est déjà retenu : la question est *posée*, elle
  est à l'écran, et elle ne coûte aucun geste au cas majoritaire. Les 14 allergènes
  réglementaires n'apparaissent qu'après avoir répondu « oui ».

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

**Cette exigence impose un état persistant.** Déduire « l'onboarding est fait » du
seul fait qu'il existe des membres a un trou qui n'est pas tordu : quelqu'un saisit
ses deux membres, se fait interrompre, revient plus tard. Il a des membres, donc on
l'envoie sur la semaine — **la question des allergies ne lui sera jamais posée.**
C'est exactement l'exigence de ce paragraphe qu'on abandonnerait, dans le seul cas
où elle avait une chance de servir. Une déduction ne sait d'ailleurs détecter que
« zéro membre », jamais « bloc 2 sur 3 » : l'onboarding devient non reprenable.

D'où **`household_settings.onboarded_at`**, posé à la fin du parcours — y compris
quand la réponse aux allergies est « non », puisque c'est précisément ce qu'il faut
enregistrer.

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
                               → { constraints: [ {kind, label, detail?} ] }

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

# Réglages du foyer
GET   /household/settings      → { snacks_enabled, max_dishes_soft_limit,
                                   onboarded_at }
PATCH /household/settings      { snacks_enabled?, max_dishes_soft_limit?,
                                 onboarding_complete? }
```

Quatre choix qui méritent leur justification :

**Les alternatives passent par un endpoint dédié** plutôt que d'être embarquées
dans la réponse de génération. L'intention du §6 était d'éviter une
*régénération*, pas un aller-retour : une requête sans LLM répond en quelques
dizaines de millisecondes. Les embarquer alourdirait la lecture du plan — celle
dont la vue mobile a besoin — et les alternatives disparaîtraient au rechargement.

**Les contraintes sortent de `/members/{id}/constraints`.** Conséquence directe du
§10 : une aversion peut n'avoir aucun membre, donc l'URL ne peut plus être
imbriquée sous un membre.

**La fin de l'onboarding passe par `PATCH /household/settings`, pas par un verbe
dédié.** `household_settings` porte déjà les réglages du foyer, et l'écran 6 devra
de toute façon écrire dessus pour le goûter et la limite de plats. Un
`POST /household/onboarding-complete` créerait un second chemin d'écriture vers la
même ligne.

Noter que la charge utile porte `onboarding_complete` — **une intention, pas une
date**. Un client n'écrit jamais une valeur d'horloge serveur : elle serait fausse
de son propre décalage, et rien ne l'empêcherait d'être arbitraire. `true` horodate,
`false` efface — ce qui rend l'onboarding rejouable pendant le développement.

**`MealPlanOut.violations` porte des objets, pas des chaînes — et il est stocké.**

```
violations: [ { code, detail, day_of_week?, meal_type? } ]
```

Les violations décrivent le plan écrit, donc **elles vivent avec lui**, dans une
colonne de `meal_plan`. Elles n'existaient d'abord que dans la réponse du `POST` —
or la vue charge par `GET`, délibérément, parce que c'est ce qui rend une réponse
perdue survivable. Un simple rechargement perdait donc exactement l'information qui
dit que le plan est incomplet : le plan survivait, l'avertissement non. Les lire
depuis le stockage fait coïncider les deux chemins par construction plutôt que par
discipline.

Une génération limitée à un créneau ne remplace que **ses** violations : celles des
autres créneaux décrivent toujours ce qu'il y a dans l'assiette, exactement comme
les plats.

L'API renvoie délibérément un plan rejeté **avec ce qui ne va pas** plutôt que de
faire semblant qu'il est passé. Encore faut-il que le front puisse en faire quelque
chose. Les 12 codes (`eater_not_served`, `too_many_dishes`…) ne veulent rien dire
pour un foyer, mais **la seule réaction utile est par créneau** — régénérer
celui-là, ou écrire le plat soi-même. Un bandeau qui signale un problème quelque
part parmi neuf créneaux donne de l'inquiétude sans cible : c'est moins utile que
le silence.

L'interface affiche donc un message non technique (*« deux repas n'ont pas pu être
complétés »*) et **marque les créneaux concernés dans la grille**. Les codes
restent dans les logs, où ils servent au harness d'évaluation.

`household_id` n'apparaît nulle part — il est dérivé de l'identité (I6).

> **Ce que le 503 de génération ne doit pas dire.** Le message d'erreur remontait
> l'exception brute, ce qui a mis `http://host.docker.internal:11434` dans un
> navigateur. Un nom d'hôte interne ne sort pas : message générique côté client,
> exception complète dans les logs.

---

## 14. Les écrans

| # | Écran | Contenu | URL |
|---|---|---|---|
| 1 | Connexion | Bouton Google | `/` sans session |
| 2 | Onboarding | Membres, allergies, aversions — une page, trois blocs | `/onboarding` |
| 3 | Semaine | Grille ou liste, basculable | `/?week=2026-08-10` |
| 4 | Génération | Texte libre → interprétation confirmable → attente | **dans l'écran 3** |
| 5 | Panneau créneau | Titre éditable, réparation dirigée, variantes, invités | `/?week=…&slot=3-dinner` |
| 6 | Réglages | Foyer, membres, contraintes, créneaux | `/settings` |

**L'écran 4 n'est pas un écran.** La génération vit **dans** l'écran de la semaine :
on compose sa semaine en la regardant, et une fenêtre modale recouvrirait
précisément ce qu'on est en train de commenter. Le champ de saisie est proéminent
quand il n'y a pas de plan — c'est le premier écran que voit quelqu'un qui sort de
l'onboarding — et se replie en une ligne, *« une précision pour cette semaine ? »*,
une fois la semaine remplie. **La présence du plan suffit à décider**, aucun état
supplémentaire n'est nécessaire.

L'attente s'affiche à la place de la grille, donc **là où le résultat va
apparaître**, et non dans une fenêtre qui va disparaître.

La génération **d'un seul créneau et le mode invités** ne passent pas par là : ils
partent du panneau de l'écran 5, déjà ouvert sur le créneau concerné. Même
endpoint, même code client, portée différente — exactement ce que décrit le §4.

**L'URL porte la semaine et le créneau ouvert.** Rechargement, retour arrière et
lien partagé retombent sur le même état, et un `<dialog>` piloté par l'URL n'a pas
d'état propre à désynchroniser.

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
| Les alternatives instantanées | Le pré-filtre est bouchonné : aucun candidat écarté à montrer (§6) | V1 |
| L'explication d'un choix | Rien de réel à expliquer, le pré-filtre est bouchonné | V1 |
| Toute garantie allergène | Ni référentiel, ni tags vérifiés | V1 |
| Le contrôle d'âge des plats | Pas de `suitable_stages` sans catalogue | V1 |
| Temps, difficulté, quantités | Viendraient du catalogue | V1 |

### L'absence de garantie allergène doit être dite dans l'interface

`ARCHITECTURE.md` §10.2 n'acceptait la V0 sans garantie qu'à la condition d'un usage
par le fondateur seul. Cette condition tombe dès que l'app est donnée à tester à
d'autres foyers — ce qui est le but.

**La mention doit donc quitter la documentation et entrer dans l'écran**, à deux
endroits : là où les allergies se saisissent (bloc 2 de l'onboarding, et les
réglages), et sur le plan généré. Le contenu est le même et il est littéral : *les
allergies déclarées ne sont pas filtrées, les plats proposés ne sont vérifiés par
personne.*

C'est le seul endroit de la V0 où l'interface parle plus fort que d'habitude. Une
garantie absente qui n'est écrite que dans un fichier d'architecture n'a jamais
protégé un enfant allergique. La mention disparaît en V1, quand le filtre devient
réel.

---

Ce que la V0 **prouve** en revanche : la boucle agentic complète, l'interprétation
d'intention, l'arbitrage sous enveloppe, la re-validation, les variantes de
service — et que l'interface tient debout.
