# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_llm_sandbox.py
==============================
Regression tests for the LLM strategy sandbox (_compile_strategy).

Each test verifies that a known bypass vector is blocked by the AST-based
checker.  If any test fails it means a bypass vector has been re-introduced.
"""

import ast

import pytest

from brain.llm_agent import _ast_sandbox_check, _compile_strategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _violations(code: str) -> list[str]:
    tree = ast.parse(code)
    return _ast_sandbox_check(tree)


def _blocked(code: str) -> bool:
    return len(_violations(code)) > 0


# ---------------------------------------------------------------------------
# Banned module imports — all forms
# ---------------------------------------------------------------------------


class TestBannedModuleImports:
    def test_import_os(self):
        assert _blocked("import os")

    def test_import_os_as_alias(self):
        assert _blocked("import os as _os")

    def test_from_os_import(self):
        assert _blocked("from os import system")

    def test_from_os_path_import(self):
        assert _blocked("from os.path import join")

    def test_import_subprocess(self):
        assert _blocked("import subprocess")

    def test_import_socket(self):
        assert _blocked("import socket")

    def test_import_requests(self):
        assert _blocked("import requests")

    def test_import_aiohttp(self):
        assert _blocked("import aiohttp")

    def test_import_httpx(self):
        assert _blocked("import httpx")

    def test_import_ctypes(self):
        assert _blocked("import ctypes")

    def test_import_importlib(self):
        assert _blocked("import importlib")

    def test_from_importlib_import(self):
        assert _blocked("from importlib import import_module")

    def test_import_pathlib(self):
        assert _blocked("from pathlib import Path")

    def test_import_shutil(self):
        assert _blocked("import shutil")

    def test_import_threading(self):
        assert _blocked("import threading")

    def test_import_multiprocessing(self):
        assert _blocked("import multiprocessing")

    def test_import_pickle(self):
        assert _blocked("import pickle")

    def test_import_sys(self):
        assert _blocked("import sys")


# ---------------------------------------------------------------------------
# Banned built-in calls
# ---------------------------------------------------------------------------


class TestBannedBuiltins:
    def test_eval(self):
        assert _blocked("eval('1+1')")

    def test_exec(self):
        assert _blocked("exec('import os')")

    def test_open(self):
        assert _blocked("open('/etc/passwd')")

    def test_compile(self):
        assert _blocked("compile('', '', 'exec')")

    def test_getattr(self):
        assert _blocked("getattr(object, '__class__')")


# ---------------------------------------------------------------------------
# Previously-confirmed bypass vectors (regression)
# ---------------------------------------------------------------------------


class TestBypassVectors:
    def test_importlib_bypass(self):
        """importlib.import_module('os') was not caught by the old string filter."""
        code = 'import importlib\nm = importlib.import_module("os")\nm.system("id")'
        assert _blocked(code)

    def test_getattr_split(self):
        """getattr(os, 'sys'+'tem') was not caught by the old string filter."""
        code = 'import os\ngetattr(os, "sys"+"tem")("id")'
        assert _blocked(code)

    def test_pathlib_write(self):
        """from pathlib import Path was not caught by the old string filter."""
        code = 'from pathlib import Path\nPath("/tmp/x").write_text("pwned")'
        assert _blocked(code)

    def test_ctypes_load(self):
        """import ctypes was not caught by the old string filter."""
        code = "import ctypes\nctypes.CDLL(None)"
        assert _blocked(code)


# ---------------------------------------------------------------------------
# Safe code must NOT be blocked
# ---------------------------------------------------------------------------


class TestSafeCode:
    @pytest.fixture(autouse=True)
    def _enable_code_exec(self, monkeypatch):
        # _compile_strategy fails closed unless LLM_CODE_EXECUTION_ENABLED is set.
        # These tests exercise the compile path itself, so enable it explicitly.
        monkeypatch.setattr("brain.llm_agent._LLM_CODE_EXEC_ENABLED", True)

    def test_numpy_allowed(self):
        code = (
            "import numpy as np\n"
            "class GeneratedStrategy:\n"
            "    def signal(self, data):\n"
            "        return float(np.mean(data))\n"
        )
        assert not _blocked(code)

    def test_pandas_allowed(self):
        code = (
            "import pandas as pd\n"
            "class GeneratedStrategy:\n"
            "    def signal(self, data):\n"
            "        return pd.Series(data).mean()\n"
        )
        assert not _blocked(code)

    def test_math_allowed(self):
        code = (
            "import math\nclass GeneratedStrategy:\n    def signal(self, data):\n        return math.log(max(data))\n"
        )
        assert not _blocked(code)

    def test_pure_python_allowed(self):
        code = "class GeneratedStrategy:\n    def signal(self, data):\n        return sum(data) / len(data)\n"
        assert not _blocked(code)

    def test_compile_strategy_safe_code(self):
        code = "class GeneratedStrategy:\n    def signal(self, data):\n        return 1.0\n"
        instance, err = _compile_strategy(code)
        assert err is None, f"Safe code was rejected: {err}"
        assert instance is not None
        assert instance.signal([1, 2, 3]) == 1.0

    def test_compile_strategy_blocked_code(self):
        code = "import os\nclass GeneratedStrategy:\n    pass\n"
        instance, err = _compile_strategy(code)
        assert instance is None
        assert err is not None
        assert "banned" in err.lower()

    def test_syntax_error_rejected(self):
        code = "def broken(:\n    pass\n"
        instance, err = _compile_strategy(code)
        assert instance is None
        assert "SyntaxError" in err


# ---------------------------------------------------------------------------
# The execution gate must fail closed by default
# ---------------------------------------------------------------------------


class TestCodeExecutionGate:
    def test_disabled_by_default(self, monkeypatch):
        """With the flag unset, even trivially-safe code must not execute."""
        monkeypatch.setattr("brain.llm_agent._LLM_CODE_EXEC_ENABLED", False)
        code = "class GeneratedStrategy:\n    def signal(self, data):\n        return 1.0\n"
        instance, err = _compile_strategy(code)
        assert instance is None
        assert err is not None
        assert "disabled" in err.lower()
