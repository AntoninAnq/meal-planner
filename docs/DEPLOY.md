# Mise en ligne

> Procédure **manuelle**, et elle le reste. La CI ne déploie pas, délibérément : automatiser un déploiement qui n'a jamais été fait à la main, c'est la façon classique de se retrouver avec une panne que personne ne sait diagnostiquer (`.github/workflows/ci.yml`). Ce document existe pour qu'il soit fait à la main une fois, correctement.

Tout ce qui suit a été **vérifié en local** — restauration sur une base vierge, image de production démarrée, écoute IPv6 constatée — sauf ce qui exige un compte chez l'hébergeur, signalé par ⚠️.

---

## 1. La forme

Quatre pièces. Trois viennent du dépôt, une est une base gérée.

```
                    ┌──────────────────┐
   navigateur  ───▶ │  proxy  (Caddy)  │   ← seul service public
                    └────────┬─────────┘
                       /api/*│  reste
                    ┌────────▼──┐  ┌──────────┐
                    │    api    │  │   web    │
                    │  FastAPI  │  │ Next.js  │
                    └─────┬─────┘  └────┬─────┘
                          │             │ Server Components → api
                    ┌─────▼─────┐       │ (réseau privé, jamais le navigateur)
                    │ Supabase  │◀──────┘
                    └───────────┘
```

**Le proxy n'est pas décoratif.** Il tient deux décisions d'architecture :

- **L'origine unique** (§11.1). `/` et `/api` sur le même hôte, donc le cookie de session reste *first-party* : pas de CORS avec `credentials`, pas de `SameSite=None`, pas de combat contre des protections navigateur qui se durcissent chaque année.
- **L'absence de délai de réponse** (§9). Le synchrone tient parce que rien dans `navigateur → Caddy → FastAPI` n'impose de timeout. Remplacer Caddy par des `rewrites` Next.js mettrait Node dans le chemin, avec son propre délai, sur une requête mesurée à 30 s en cloud et 182 s en local.

---

## 2. Supabase ⚠️

1. Créer le projet. Noter la **chaîne de connexion**.
2. **Choisir le port, et c'est la décision qui coûte cher si elle est prise sans le savoir :**

   | Port | Mode | `DATABASE_POOLED` |
   |---|---|---|
   | **5432** | session — *recommandé* | `false` |
   | 6543 | transaction | **`true`, obligatoire** |

   En mode transaction, chaque transaction peut tomber sur un backend différent : une requête préparée sur l'un manque sur le suivant. L'échec est `prepared statement "_pg3_0" already exists`, **intermittent** — il passe tous les tests de fumée et apparaît en charge, en production, avec l'allure d'un problème de base de données alors que c'est un problème de configuration.

   Avec un seul conteneur et `DATABASE_POOL_SIZE=5`, le mode **session** suffit et n'a aucun de ces défauts.

3. Les extensions `unaccent` et `pg_trgm` sont créées par la migration 0006 — rien à activer à la main.

## 3. Le schéma et le catalogue

Le schéma vient d'Alembic ; le catalogue vient d'un export. **Dans cet ordre.**

```sh
# 1. Le schéma, les extensions, et les valeurs semées par 0001
DATABASE_URL='postgresql+psycopg://…' alembic upgrade head

# 2. Le catalogue, sans une ligne de données de foyer
sh db/dump-catalogue.sh > catalogue.sql
psql 'postgresql://…' -v ON_ERROR_STOP=1 -f catalogue.sql
```

> **Pourquoi un script et pas le dump complet.** `pg_dump` sans filtre emporte `household`, `member`, `dietary_constraint` — et `dietary_constraint` est une **donnée de santé** (RGPD art. 9). Il n'y a aucune raison qu'une copie de celle d'une famille parte chez un hébergeur parce qu'on voulait y mettre les recettes.
>
> Le script exclut aussi `portion_coefficient` et `life_stage_threshold` : la migration 0001 les sème elle-même, et les dumper fait mourir le chargement sur `duplicate key value` **à mi-parcours**, recettes déjà chargées et ingrédients non. Il a fallu une restauration sur base vierge pour s'en apercevoir.

**Vérifié** sur une base vierge : 3 439 recettes, 727 vérifiées allergènes, 311 ingrédients, 596 alias, **0 foyer**, `alembic_version = 0014`.

Depuis 0013, 1 984 de ces recettes sont **retirées** (`deprecated_at` non nul) : leur source ne répond plus. Une inscription neuve donne donc 9 créneaux et **664 recettes éligibles par stade de vie**, dont 388 vérifiées allergènes — au-dessus du plancher de 60 candidats, mais c'est le chiffre à surveiller si la variété des semaines déçoit.

Le fichier `catalogue.sql` fait ~6 Mo et **n'a pas sa place dans le dépôt** — il est régénérable en une commande.

> ⚠️ **Régénérer, jamais réutiliser un ancien dump.** `pg_dump --data-only` écrit la liste des colonnes telle qu'elle était le jour du dump. Un export antérieur à la migration 0013 ne contient donc pas `recipe.deprecated_at` : le chargement met la colonne à NULL partout, et `cuisine-libre` — dont le site répond 404, 1 984 recettes — redevient proposable en production. L'ordre du §3 y contribue : 0013 marque une table `recipe` encore vide, et c'est le dump qui apporte les lignes. Un export régénéré porte la colonne et les horodatages, vérifié.

> La pipeline catalogue ne tourne **jamais** en production : le service `catalog` est derrière un `profiles` dans Compose, donc `docker compose up` ne le démarre pas, et il n'est pas déployé du tout. Il sort chercher chez des tiers (I9).

## 4. Les trois services ⚠️

Un service par répertoire, tous depuis ce dépôt.

| Service | Build | Public |
|---|---|---|
| `api` | `backend/Dockerfile` | non |
| `web` | `web/Dockerfile` (cible par défaut = production) | non |
| `proxy` | `Dockerfile.proxy` | **oui** — le domaine pointe ici |

**Sur Railway le réseau privé est en IPv6 seul.** Un service qui écoute sur `0.0.0.0` démarre, répond à sa propre sonde de santé, et reste injoignable depuis les autres : la panne se lit comme « le proxy est mal configuré » et n'en est pas une. D'où `BIND_HOST=::` et `HOSTNAME=::` ci-dessous — `::` accepte les deux familles.

### api

```
DATABASE_URL=postgresql+psycopg://…      # le préfixe +psycopg compte
DATABASE_POOLED=false                    # true si port 6543
SESSION_SECRET=…                         # openssl rand -base64 48 — sans défaut, l'API ne démarre pas sans
ENVIRONMENT=prod                         # ce qui met Secure sur le cookie
APP_BASE_URL=https://…                   # l'URI de redirection OAuth en dérive
GOOGLE_CLIENT_ID=…
GOOGLE_CLIENT_SECRET=…
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=…
ANTHROPIC_MODEL=claude-haiku-4-5
GENERATION_DAILY_LIMIT=50                # §11.7 — recalculer si le modèle change
BIND_HOST=::
PORT=8000
LOG_LEVEL=INFO                           # DEBUG le temps d'une investigation
```

Commande de démarrage : `alembic upgrade head && uvicorn app.main:app --host :: --port 8000`.

> Migrer au démarrage est un anti-patron **au-delà d'un exemplaire** — deux conteneurs qui démarrent ensemble lancent deux migrations. À un seul exemplaire c'est le compromis juste : une pièce en moins, et une migration oubliée est impossible.

### web

```
INTERNAL_API_BASE_URL=http://api.railway.internal:8000
HOSTNAME=::
PORT=3000
GENERATION_EXPECTED_SECONDS=30           # 30 en cloud, 180 sur le 8B local (§9)
FEEDBACK_URL=                            # formulaire hébergé, ou vide (§11.7)
```

### proxy

```
PORT=…                                   # celui que l'hébergeur impose
API_UPSTREAM=api.railway.internal:8000
WEB_UPSTREAM=web.railway.internal:3000
```

L'hébergeur termine TLS à sa périphérie, donc Caddy écoute en HTTP simple derrière. Pour lui faire faire le certificat, remplacer l'adresse du site par le domaine — le bloc commenté est dans le `Caddyfile`.

## 5. Google OAuth ⚠️

Ajouter `https://<domaine>/api/auth/callback` aux URI de redirection autorisées. Elle doit correspondre **exactement** à `APP_BASE_URL` + `/api/auth/callback` : c'est `Settings.oauth_redirect_uri` qui la calcule, et Google compare caractère par caractère.

## 6. Ce qu'on regarde après le premier déploiement

```
GET  /            → la promesse et le bouton Google
     connexion    → un foyer est créé, l'onboarding s'ouvre
     génération   → une semaine, en une dizaine de secondes en cloud
GET  /api/auth/logout → 405   (seul POST déconnecte — sinon une balise <img> suffit)
```

> **Une configuration incohérente ne démarre pas**, et c'est voulu. En prod, `Settings` refuse : un `APP_BASE_URL` en `https://` sans `ENVIRONMENT=prod` — le cas où le cookie partirait sans `Secure` alors que tout fonctionne par ailleurs —, un `SESSION_SECRET` de moins de 32 caractères, des identifiants Google absents, un `LLM_PROVIDER` **non défini** (il vaudrait `fake`, qui répond `{}` : des semaines vides pleines de violations, qui se lisent comme un modèle en panne), et `anthropic` sans `ANTHROPIC_API_KEY`. Si l'API ne démarre pas, son message dit lequel des cinq.
>
> **Déployer avant d'avoir la clé** reste possible : `LLM_PROVIDER=fake` explicitement. Écrit noir sur blanc c'est un choix, et le refus ne porte que sur le défaut implicite. La séquence déploiement → création de la clé → redéploiement ne demande **aucune modification de code** : le client LLM est construit à la première génération, pas au démarrage, et le redémarrage du conteneur suffit à prendre la nouvelle valeur.

Puis, la seule requête à connaître par cœur — **ce que ça coûte vraiment** :

```sql
select date_trunc('day', created_at) as jour,
       count(*)                      as appels,
       sum(input_tokens)             as entree,
       sum(output_tokens)            as sortie,
       count(*) filter (where not succeeded) as echecs
from generation_log
group by 1 order by 1 desc;
```

À la grille Haiku 4.5 : `entrée × 1 € / 1M + sortie × 5 € / 1M`. Le banc donne 3 490 / 640 pour une semaine, soit **~0,7 centime l'appel** — et 1,2 quand l'enveloppe rejoue.

## 6 bis. Réagir, et depuis où

**Les commandes d'exploitation n'ont besoin que de `DATABASE_URL`.** Elles se lancent donc **depuis votre poste, contre la base de production** — pas besoin d'un shell chez l'hébergeur, ce qui est précisément ce qu'on ne veut pas chercher le jour où il faut couper quelqu'un.

```sh
export DATABASE_URL='postgresql+psycopg://…'   # celle de Supabase
cd backend

poetry run python -m app.admin list                 # qui est là, et qui dépense
poetry run python -m app.admin find 335C-58F8       # le foyer derrière un code de support
poetry run python -m app.admin limit <foyer> 0      # arrêter la dépense, semaines lisibles
poetry run python -m app.admin limit <foyer> 500    # au contraire, un plafond haut
poetry run python -m app.admin revoke google:…      # fermer la porte
poetry run python -m app.admin restore google:…     # rouvrir
```

Trois sanctions, de la plus douce à la plus dure : plafond à 0, plafond bas, révocation. Un plafond bas freine un bot présumé **sans couper un vrai foyer** — c'est le bon premier geste, parce qu'un faux positif reste utilisable. `revoke` garde la ligne d'accès, donc l'identité coupée ne peut pas se réinscrire en se reconnectant.

Un foyer qui signale un bug donne le **code affiché dans son écran Réglages**. `find` le traduit en `household_id`, et toutes les lignes de log de ses requêtes portent ce code — `logs | grep 335C-58F8`.

> Le plafond global reste `GENERATION_DAILY_LIMIT`. L'inscription est ouverte (§11.7) et le quota est **par foyer** : il n'existe aucun plafond à l'échelle de l'instance, donc quelqu'un qui industrialiserait la création de comptes Google se verrait sur la facture avant de se voir ailleurs. C'est un risque accepté, pas un oubli.

## 6 ter. Les sauvegardes

Elles dépendent de l'offre Supabase, et **c'est à vérifier avant d'avoir de vraies familles dedans** : `dietary_constraint` est une donnée de santé, `member.birth_date` une date de naissance de mineur. Une restauration doit avoir été essayée une fois, pas seulement configurée.

## 7. Ce que la mise en ligne débloque

**Comparer les modèles.** Le banc (`eval/`) a été bâti pour ça et n'a jamais tourné sur autre chose que `qwen3:8b` — une variable d'environnement l'en séparait, et le coût. Deux échecs connus attendent cette mesure : la variante bébé identique sur tous les créneaux, et la répétition demandée jamais honorée. Trois réécritures de prompt n'ont rien changé, ce qui désigne le modèle comme sujet.

Et §15 rouvre alors la **réparation déterministe d'une assignation**, explicitement repoussée « après la comparaison de modèles ».
