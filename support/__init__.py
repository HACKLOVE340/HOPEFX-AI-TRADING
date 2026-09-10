# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Customer support: who answers, and when a human must.

`support.triage` decides. It does not answer and it cannot act — see that
module's docstring for why the separation is the whole safety argument.

**This package deliberately does not re-export the `triage` function.** It did,
and that shadowed its own submodule: `from support import triage` and
`import support.triage as mod` both returned the *function*, because
`import a.b as c` resolves `b` as an attribute of `a` before falling back to
`sys.modules`. A test caught it while reaching for `DEPARTMENT_ROUTES` and got
an `AttributeError` on a function — but the same collision would have hit any
caller that wanted the module, and it would have read as a typo rather than as
a package that overwrote its own name.

Import the callable from the module it lives in::

    from support.triage import triage
"""

from support.triage import DEPARTMENT_ROUTES, TriageResult

__all__ = ["DEPARTMENT_ROUTES", "TriageResult"]
