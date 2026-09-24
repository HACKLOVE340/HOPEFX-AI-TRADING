"""A0 dry-run defect 3 — ``retrain_horizon5.py`` could not be pointed at clean
data, could fall back to futures, and could not be kept out of the committed
artifacts.

Measured in the A0 dry run (docs/audit/plans/2026-09-24-a0-model-retrain.md):

* ``--use-cached`` always reached ``data/XAUUSD_50Y.csv`` first, the file
  ``ml/cached_series.py`` deliberately excludes, and the corrupt-history gate
  rightly refused it (1,972 of 12,909 bars move >20%). There was no
  ``--cached-csv`` to name the clean file instead.
* ``ml/train_advanced.fetch_gold_ohlcv`` falls back to ``yfinance`` — ``GC=F``
  by default, COMEX futures rather than spot — whenever the cache yields
  nothing. For XAUUSD that fallback must be impossible from this wrapper.
* ``_MODEL_DIR`` was ``ml/saved_models`` unconditionally, as was
  ``train_advanced``'s, so a rehearsal run rewrote the committed artifacts.

No test here trains a model or writes under ``ml/saved_models``: every red
case fails at argument parsing or at a patched boundary before any write.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import ml.train_advanced as ta
import scripts.retrain_horizon5 as rh5

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGED = _ROOT / "ml" / "saved_models"


def _parse(monkeypatch, *argv: str):
    monkeypatch.setattr(sys, "argv", ["retrain_horizon5.py", *argv])
    return rh5.parse_args()


# ── --cached-csv ───────────────────────────────────────────────────────────────


def test_cached_csv_defaults_to_the_file_cached_series_treats_as_clean(monkeypatch):
    from ml.cached_series import DEFAULT_FILES

    args = _parse(monkeypatch, "--use-cached")

    assert Path(args.cached_csv).resolve() == (_ROOT / "data" / DEFAULT_FILES["XAUUSD"][0]).resolve()
    assert Path(args.cached_csv).name != "XAUUSD_50Y.csv"


def test_cached_csv_can_be_chosen(monkeypatch, tmp_path):
    csv = tmp_path / "mine.csv"
    args = _parse(monkeypatch, "--use-cached", "--cached-csv", str(csv))
    assert Path(args.cached_csv) == csv


def _captured_training_command(monkeypatch, args) -> list[str]:
    seen: list[list[str]] = []

    class _Done:
        returncode = 0

    def _fake_run(cmd, check=False):
        seen.append([str(c) for c in cmd])
        return _Done()

    monkeypatch.setattr(rh5.subprocess, "run", _fake_run)
    rh5.run_training(args)
    assert seen, "run_training launched nothing — the harness observed no command"
    return seen[0]


def test_training_command_names_the_chosen_csv_and_forbids_download(monkeypatch, tmp_path):
    csv = tmp_path / "clean.csv"
    csv.write_text("date,open,high,low,close,volume\n")
    out = tmp_path / "out"
    args = _parse(monkeypatch, "--use-cached", "--cached-csv", str(csv), "--output-dir", str(out))

    cmd = _captured_training_command(monkeypatch, args)

    assert cmd[cmd.index("--cached-csv") + 1] == str(csv)
    assert "--no-download" in cmd, cmd
    assert Path(cmd[cmd.index("--model-dir") + 1]) == out


def test_training_command_forbids_download_even_without_use_cached(monkeypatch, tmp_path):
    """train_advanced defaults to the cache, then to yfinance. From this wrapper
    the second step must not exist whether or not --use-cached was typed."""
    args = _parse(monkeypatch, "--output-dir", str(tmp_path))

    cmd = _captured_training_command(monkeypatch, args)

    assert "--no-download" in cmd, cmd
    assert "--cached-csv" in cmd, cmd


def test_dry_run_loads_the_chosen_csv_and_never_downloads(monkeypatch, tmp_path):
    csv = tmp_path / "clean.csv"
    args = _parse(monkeypatch, "--dry-run", "--use-cached", "--cached-csv", str(csv), "--output-dir", str(tmp_path))
    seen: dict = {}

    def _fake_fetch(symbol, years, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop here")

    monkeypatch.setattr(ta, "fetch_gold_ohlcv", _fake_fetch)
    with pytest.raises(SystemExit):
        rh5.dry_run(args)

    assert seen, "dry_run never reached the loader — the harness observed nothing"
    assert seen["cached_csv"] == str(csv)
    assert seen["allow_download"] is False


def test_a_missing_cached_csv_refuses_before_training(monkeypatch, tmp_path):
    args = _parse(
        monkeypatch, "--use-cached", "--cached-csv", str(tmp_path / "absent.csv"), "--output-dir", str(tmp_path)
    )
    launched: list = []
    monkeypatch.setattr(rh5.subprocess, "run", lambda *a, **k: launched.append(a))

    with pytest.raises(SystemExit) as exc:
        rh5.run_training(args)

    assert exc.value.code != 0
    assert launched == []


# ── fetch_gold_ohlcv: no silent futures fallback ───────────────────────────────


def test_loader_refuses_the_yfinance_fallback_when_download_is_forbidden(monkeypatch, tmp_path):
    yf = pytest.importorskip("yfinance")
    calls: list = []
    monkeypatch.setattr(yf, "download", lambda *a, **k: calls.append(a))

    with pytest.raises(FileNotFoundError, match="refusing"):
        ta.fetch_gold_ohlcv("GC=F", 5, use_cached=True, cached_csv=str(tmp_path / "absent.csv"), allow_download=False)

    assert calls == [], "yfinance was called although download was forbidden"


def test_an_explicit_csv_is_not_silently_replaced_by_the_50y_file(monkeypatch, tmp_path):
    """Naming a file is the operator's choice. When it yields nothing in the
    window, the loader used to walk on to XAUUSD_50Y.csv."""
    csv = tmp_path / "old.csv"
    csv.write_text("date,open,high,low,close,volume\n1990-01-02,1,1,1,1,0\n")
    opened: list[str] = []
    real_read_csv = ta.pd.read_csv

    def _spy(path, *a, **k):
        opened.append(Path(path).name)
        return real_read_csv(path, *a, **k)

    monkeypatch.setattr(ta.pd, "read_csv", _spy)
    with pytest.raises(FileNotFoundError):
        ta.fetch_gold_ohlcv("GC=F", 5, use_cached=True, cached_csv=str(csv), allow_download=False)

    assert opened == ["old.csv"], opened


# ── output directory ───────────────────────────────────────────────────────────


def test_output_dir_defaults_to_the_packaged_directory(monkeypatch):
    monkeypatch.delenv("RETRAIN_OUTPUT_DIR", raising=False)
    args = _parse(monkeypatch)
    assert Path(args.output_dir).resolve() == _PACKAGED.resolve()


def test_output_dir_honours_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("RETRAIN_OUTPUT_DIR", str(tmp_path))
    args = _parse(monkeypatch)
    assert Path(args.output_dir) == tmp_path


def test_every_wrapper_write_lands_in_the_output_dir(monkeypatch, tmp_path):
    before = {p.name: p.read_bytes() for p in _PACKAGED.iterdir() if p.is_file()}
    args = _parse(monkeypatch, "--output-dir", str(tmp_path))
    report = {"oos": {"accuracy": 0.5}, "feature_count": 3}

    rh5.write_horizon_meta(args, report)

    written = sorted(p.name for p in tmp_path.iterdir())
    assert written == ["advanced_oos_meta.json", "horizon5_meta.json", "horizon5_training_report.json"], written
    after = {p.name: p.read_bytes() for p in _PACKAGED.iterdir() if p.is_file()}
    assert after == before, "write_horizon_meta touched ml/saved_models"


def test_train_advanced_model_dir_flag_redirects_model_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(ta, "MODEL_DIR", ta.MODEL_DIR)  # restored after the test

    def _stop(*a, **k):
        raise RuntimeError("stop before training")

    monkeypatch.setattr(ta, "fetch_gold_ohlcv", _stop)
    with pytest.raises(RuntimeError, match="stop before training"):
        ta.main(["--model-dir", str(tmp_path / "models"), "--no-download"])

    assert tmp_path / "models" == ta.MODEL_DIR


def test_archival_under_a_redirected_model_dir_uses_that_dirs_registry(monkeypatch, tmp_path):
    """archive_artifact_before_overwrite repoints registry entries by digest. A
    redirected run must repoint its own registry, never the shipped one."""
    monkeypatch.setattr(ta, "MODEL_DIR", tmp_path)
    reg = ta._archival_registry()
    assert reg is not None
    assert reg._path == tmp_path / "registry.json"
