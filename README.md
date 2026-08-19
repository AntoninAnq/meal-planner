# Meal Planner

Planification de repas pour les foyers où **tout le monde ne mange pas la même
chose** — typiquement de jeunes enfants qui ne mangent pas le plat des adultes.

> **Lis `docs/ARCHITECTURE.md` avant de toucher au code.** C'est la colonne
> vertébrale du projet : décisions, justifications, et neuf invariants
> non négociables. Une décision qui contredit ce document doit d'abord modifier
> ce document.

**Statut : phase 2 — V1.** Le catalogue alimente réellement la planification :
pré-filtre SQL, trois signaux souples, arbitrage sur identifiants, re-validation.
Une semaine complète prend **~28 s** sur `qwen3:8b` en local, contre 182 s avant
le branchement — le catalogue a supprimé la boucle de rejeu, il ne l'a pas
alourdie (`docs/ARCHITECTURE.md` §14.6).

La mention « les allergies ne sont pas filtrées » a disparu de l'interface, parce
que le filtre est devenu réel. Ce qui la remplace n'est pas un bandeau reformulé :
déclarer une contrainte **re-valide le plan en cours** et marque les créneaux
concernés. Seul un plat écrit à la main garde une marque — c'est le seul qu'aucun
filtre ne peut couvrir.

## Démarrer

```bash
cp .env.example .env
# Renseigner POSTGRES_PASSWORD, SESSION_SECRET, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
docker compose up --build
```

Puis <http://localhost:8080>.

Deux préalables :

1. **Ollama tourne sur l'hôte**, pas dans un conteneur (`docs/ARCHITECTURE.md`
   §7.3) — le relancer en conteneur dupliquerait un modèle de 5 Go et la RAM qui
   va avec. `ollama pull qwen3:8b` suffit pour le développement.
2. **Client OAuth Google** (Google Cloud Console → APIs & Services →
   Credentials → OAuth client ID, type Web). URI de redirection autorisée,
   exactement : `http://localhost:8080/api/auth/callback`.

Générer les deux secrets — `.env.example` les laisse **vides**, et ni Postgres
ni l'API ne démarrent sans eux :

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"   # POSTGRES_PASSWORD
python -c "import secrets; print(secrets.token_urlsafe(48))"   # SESSION_SECRET
```

Les caractères spéciaux sont acceptés partout, `!`, `%`, `&` et `*` compris.

## Tests

La CI ne contient que deux couches, et **aucun appel LLM réel** — c'est lent,
coûteux, instable, et ça ne teste rien de reproductible.

```bash
cd backend
poetry install
poetry run pytest
```

| Couche | Contenu |
|---|---|
| Noyau déterministe | Stades de vie, portions, minimisation des prompts |
| Enveloppe | Le LLM est remplacé par `FakeLLMClient`, qui renvoie des sorties **hostiles** |

`FakeLLMClient` est la **troisième implémentation réelle** de l'interface LLM, au
même titre qu'Ollama et l'API cloud — pas un bouchon ajouté après coup. Sans
tests qui injectent des sorties invalides, le code de re-validation n'est jamais
exécuté avant le jour où il compte, et il sera faux.

## Structure

```
meal-planner/
├── docker-compose.yml     db / api / llm (hôte) / web + proxy
├── Caddyfile              origine unique : / → Next.js, /api → FastAPI
├── docs/ARCHITECTURE.md   ← la colonne vertébrale
├── backend/               tout le Python — pas seulement l'API
│   ├── app/domain/        entités et règles pures — ni SQL, ni HTTP, ni LLM
│   ├── app/llm/           l'interface unique et ses trois implémentations
│   ├── app/auth/          OAuth Google, cookie de session, foyer courant
│   ├── app/routers/       façade HTTP
│   ├── app/catalog/       collecte et résolution du catalogue (phase 1)
│   ├── migrations/        Alembic
│   └── tests/
├── web/                   Next.js App Router, i18n-ready (fr par défaut)
├── db/                    référentiel d'ingrédients et types de plat,
│                          versionnés (phases 1 et 2)
└── eval/                  fixtures figées + banc d'essai (phase 2)
```

Le dossier s'appelle `backend/` et non `api/` : la façade HTTP n'en est qu'un
sous-dossier. Le service Docker, le hostname `api:8000` et la route `/api`
gardent le nom `api`, eux.

## Catalogue (phase 1)

Le pipeline de collecte tourne dans **sa propre image**, sur un service que
`docker compose up` ne démarre jamais :

```bash
cp backend/sources.example.yaml sources.yaml     # la whitelist, ignorée par git

docker compose run --rm catalog ingest --source <clé> --limit 60 --dry-run
docker compose run --rm catalog ingest --source <clé>
docker compose run --rm catalog load-referential # db/ingredients.yaml, idempotent
docker compose run --rm catalog resolve          # rejouable, idempotent
docker compose run --rm catalog review           # les propositions I4, à confirmer
docker compose run --rm catalog dish-types       # rubrique source → moment du repas
docker compose run --rm catalog complexity       # temps + étapes + ingrédients → 1..3
docker compose run --rm catalog food-categories  # composition, pour le signal de rotation
```

`review` est le seul de ces sept qui demande un humain, et c'est voulu : il porte
sur des allergènes (I1). `dish-types` n'en porte aucun — sa relecture est celle
du diff de `db/dish_types.yaml`.

> **Ces commandes tournent sur le service `catalog`, pas sur `api`.** Le second
> monte `db/` en lecture seule, parce que l'API n'a aucune raison d'écrire dans
> le référentiel. `review` le vérifie avant de commencer et refuse avec la bonne
> commande plutôt que d'écrire à moitié.

La whitelist **n'est pas dans le dépôt** (`docs/ARCHITECTURE.md` §11.5) : elle
est montée depuis `./sources.yaml`, et son absence est une erreur explicite,
jamais un repli silencieux sur le modèle.

Une campagne annonce son allure avant la première requête, et son rapport dit ce
qu'elle n'a **pas** su faire — pages illisibles, JSON-LD réparé, champs absents,
plafond atteint. **À la fin de chaque campagne, les pages récupérées sont effacées et les
validateurs conservés** — rien du contenu de personne ne survit (I9). Mesuré :
11,58 Go de pages, 63 Mo de validateurs. `--keep-cache` s'y oppose, pour
travailler sur l'extracteur et pour rien d'autre.

Les requêtes conditionnelles sont envoyées, mais **aucune des sources testées ne
les honore** : une re-vérification coûtera donc une campagne entière (§11.4).

Il va chercher du contenu chez des tiers qui ne nous ont rien demandé. La
politique qu'on s'impose — cadence, absence de concurrence par domaine, arrêt sur
`429`, refus de contourner une protection anti-bot — est au §11.4 de
`docs/ARCHITECTURE.md`, et les sources testées, retenues **et écartées** sont au
§11.5.
