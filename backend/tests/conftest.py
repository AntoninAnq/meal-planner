"""The one variable the suite needs before it can even be collected.

`app/main.py` builds `Settings()` at import time, on purpose: a deployment
missing a secret must refuse to start rather than serve without one. The cost
is that importing the application at all requires a configuration, and
`SESSION_SECRET` is the only field with no default.

That cost lands on the CI runner, which has no `.env`. It has already been paid
once — a single module importing `app.main` stopped the whole suite at
collection, and 348 tests that had nothing to do with configuration never ran.
`test_admin_authorisation.py` has to import the application, since what it
checks is the set of routes actually registered; so the environment is provided
here instead, once, for every test.

Set unconditionally rather than only when absent: no test may depend on the
value of the developer's own secret, and a suite that behaves differently
depending on the machine's environment is exactly what `test_config_guardrails`
was written after. That file clears every `Settings` field itself, so what is
set here cannot reach the cases that assert on a missing configuration.
"""

from __future__ import annotations

import os

os.environ["SESSION_SECRET"] = "tests-do-not-sign-anything-a-browser-will-read"
