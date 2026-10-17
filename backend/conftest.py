"""Ensure the backend package root is importable in tests.

Lets ``python -m pytest backend/tests/...`` run from the worktree root (the form
used in the feature verification commands) resolve ``import app.core...``.
"""

import os
import sys

_BACKEND_ROOT = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)
