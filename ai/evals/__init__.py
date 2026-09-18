# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The eval suite, the score it produces, and what that score permits.

* `cases` — the committed test inputs.
* `suite` — running them and scoring the result.
* `runner` — asking the real model chain, and filing the report.
* `gate` — what a score permits, bounded by its age.
* `store` — where the report lives between processes and across restarts.
* `schedule` — running the suite on an interval, off unless enabled.
"""

from .schedule import budgeted_run, interval_s, run_forever

__all__ = ["budgeted_run", "interval_s", "run_forever"]
