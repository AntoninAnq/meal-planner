"""Catalogue collection pipeline — phase 1.

Runs in its OWN image (`Dockerfile.catalog`) and its own Compose service, which
`docker compose up` never starts: this is a batch job that reaches out to the
internet, something the API does not do.

It shares the code tree with the API — and only in one direction. It may import
`app.db.models`, `app.db.session`, `app.config` and `app.domain`; nothing served
over HTTP may import it. Both halves of that rule are checked in
`tests/test_catalog_boundaries.py`.

The reason for sharing at all: this pipeline writes the very tables the allergen
filter reads (`recipe_allergen`, `recipe_ingredient`, `ingredient_allergen`).
Two definitions of those would drift, and the one that drifts is the one that
protects a child.
"""
