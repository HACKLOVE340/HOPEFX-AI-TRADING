# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
This file has been superseded by the ``api/superadmin/`` package.

Python 3 always prefers the package directory over a same-named module file,
so this file is *never* imported at runtime.  It is kept only to preserve git
history and make the split explicit.

The canonical entry-point is::

    api/superadmin/__init__.py

which re-exports the ``router`` object under the same public name:

    from api.superadmin import router  # still works — unchanged
"""
