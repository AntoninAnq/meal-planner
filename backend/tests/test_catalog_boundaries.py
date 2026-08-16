"""The catalogue pipeline stays on its side of the wall.

`app/catalog/` and the HTTP API share one code tree — the collection pipeline
writes the very tables the allergen filter reads, and two definitions of
`recipe_allergen` would eventually drift (§12.2). Sharing the tree is therefore
the point; what must not be shared is the direction of dependency.

This is the backend twin of the `components/ui/` ↛ `lib/api` rule already
enforced on the web side, and it is checked the same way: mechanically, so the
day someone reaches across, the build says so.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

#: What the pipeline is allowed to reach for. Everything else — routers,
#: services, workflows, auth, the LLM clients — is the API's business.
CATALOG_MAY_IMPORT = {
    "app.catalog",  # itself
    "app.db.models",
    "app.db.session",
    "app.config",
    "app.domain",
}

#: Nothing served over HTTP may depend on a batch job that talks to the
#: internet.
API_PACKAGES = ("routers", "services", "workflows", "auth", "llm")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _python_files(*relative: str) -> list[Path]:
    root = APP.joinpath(*relative)
    return sorted(root.rglob("*.py")) if root.exists() else []


def test_the_api_never_imports_the_catalog_pipeline() -> None:
    offenders = [
        f"{path.relative_to(APP)} imports {module}"
        for package in API_PACKAGES
        for path in _python_files(package)
        for module in _imported_modules(path)
        if module == "app.catalog" or module.startswith("app.catalog.")
    ]
    assert not offenders, offenders


def test_the_catalog_pipeline_only_reaches_for_models_and_config() -> None:
    """Keeps the later extraction into its own project mechanical.

    The day the pipeline deserves its own deployment, moving it must be a
    `git mv` plus a shared package — not an untangling.
    """
    offenders = [
        f"{path.relative_to(APP)} imports {module}"
        for path in _python_files("catalog")
        for module in _imported_modules(path)
        if module.startswith("app.")
        and not any(module == allowed or module.startswith(f"{allowed}.")
                    for allowed in CATALOG_MAY_IMPORT)
    ]
    assert not offenders, offenders
