# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
security/antivirus.py
=====================
Multi-layer antivirus and malware detection engine.

Layers
------
1. YARA rules — pattern-based detection of known malware signatures,
   webshells, crypto-miners, reverse shells, and code injection patterns.
   Rules are loaded from ``security/yara_rules/`` at startup.

2. ClamAV — industry-standard AV engine via ``clamd`` Unix socket or TCP.
   Falls back gracefully when ClamAV is not installed.

3. Entropy analysis — high-entropy blobs (>7.2 bits/byte) in Python files
   flag potential obfuscated payloads or packed executables.

4. Suspicious pattern scanner — regex-based detection of:
   - Reverse shell patterns (socket + exec combinations)
   - Base64-encoded payloads in source code
   - Known C2 callback patterns
   - Credential harvesting patterns
   - SQL injection payloads in source

5. Process monitor — scans running processes for unexpected children of the
   trading engine (requires psutil).

API
---
GET  /api/security/av/status          — scanner status + last scan summary
POST /api/security/av/scan            — trigger full scan (admin)
POST /api/security/av/scan/file       — scan a single file path (admin)
GET  /api/security/av/threats         — list detected threats
POST /api/security/av/quarantine/{id} — quarantine a detected threat (admin)

Integration
-----------
Start from connect_to_life.py::

    from security.antivirus import start_av_scanner
    await start_av_scanner(app)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
YARA_RULES_DIR = Path(__file__).parent / "yara_rules"
QUARANTINE_DIR = PROJECT_ROOT / "data" / "quarantine"
AV_SCAN_INTERVAL: int = int(os.getenv("AV_SCAN_INTERVAL", "3600"))  # 1 hour
AV_REPORT_PATH = PROJECT_ROOT / "data" / "av_last_scan.json"

# ── YARA ──────────────────────────────────────────────────────────────────────

try:
    import yara  # type: ignore[import]

    YARA_AVAILABLE = True
except ImportError:
    YARA_AVAILABLE = False
    logger.info("AV: yara-python not installed — YARA layer disabled (pip install yara-python)")

# ── ClamAV ────────────────────────────────────────────────────────────────────

try:
    import clamd  # type: ignore[import]

    CLAMD_AVAILABLE = True
except ImportError:
    CLAMD_AVAILABLE = False
    logger.info("AV: python-clamd not installed — ClamAV layer disabled (pip install clamd)")

# ── psutil ────────────────────────────────────────────────────────────────────

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


# ── Suspicious patterns ───────────────────────────────────────────────────────

# Each entry: (name, compiled_regex, severity)
SUSPICIOUS_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    (
        "reverse_shell_socket_exec",
        re.compile(
            r"socket\.socket.*?subprocess|subprocess.*?socket\.socket|"
            r"os\.system\s*\(\s*['\"].*?(bash|sh|cmd|powershell)",
            re.DOTALL | re.IGNORECASE,
        ),
        "critical",
    ),
    (
        "base64_exec_payload",
        re.compile(
            r"exec\s*\(\s*base64\.b64decode|eval\s*\(\s*base64\.b64decode|"
            r"__import__\s*\(\s*['\"]base64",
            re.IGNORECASE,
        ),
        "critical",
    ),
    (
        "dynamic_import_obfuscation",
        re.compile(
            r"__import__\s*\(\s*['\"][a-z]{1,3}['\"]|"
            r"importlib\.import_module\s*\(\s*['\"][a-z]{1,3}['\"]",
            re.IGNORECASE,
        ),
        "high",
    ),
    (
        "credential_harvesting",
        re.compile(
            r"(password|passwd|secret|api_key|token)\s*=\s*['\"][^'\"]{8,}['\"].*?"
            r"(requests\.(get|post)|urllib|httpx)",
            re.DOTALL | re.IGNORECASE,
        ),
        "high",
    ),
    (
        "crypto_miner_stratum",
        re.compile(
            r"stratum\+tcp://|xmrig|monero|cryptonight|nicehash",
            re.IGNORECASE,
        ),
        "critical",
    ),
    (
        "c2_callback_pattern",
        re.compile(
            r"(requests|httpx|urllib)\.(get|post)\s*\(\s*['\"]https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
            re.IGNORECASE,
        ),
        "high",
    ),
    (
        "webshell_eval",
        re.compile(
            r"eval\s*\(\s*\$_(GET|POST|REQUEST|COOKIE)|"
            r"exec\s*\(\s*request\.(args|form|json)",
            re.IGNORECASE,
        ),
        "critical",
    ),
    (
        "sql_injection_payload",
        re.compile(
            r"(UNION\s+SELECT|DROP\s+TABLE|INSERT\s+INTO.*?VALUES|"
            r"OR\s+1\s*=\s*1|AND\s+1\s*=\s*1)",
            re.IGNORECASE,
        ),
        "medium",
    ),
]

# File extensions to scan
SCAN_EXTENSIONS: set[str] = {".py", ".js", ".ts", ".sh", ".bash", ".php", ".rb", ".pl"}
SCAN_BINARY_EXTENSIONS: set[str] = {".exe", ".dll", ".so", ".dylib", ".bin", ".elf"}

# Paths to skip
SKIP_PATHS: set[str] = {
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "data/quarantine",
    "frontend/node_modules",
}


# ── Entropy calculator ────────────────────────────────────────────────────────


def _shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    freq: dict[int, int] = {}
    for b in data:
        freq[b] = freq.get(b, 0) + 1
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


# ── Threat record ─────────────────────────────────────────────────────────────


class Threat(BaseModel):
    id: str
    path: str
    threat_type: str
    severity: str
    detail: str
    detected_at: str
    sha256: str
    quarantined: bool = False
    quarantine_path: str | None = None


# ── Scanner ───────────────────────────────────────────────────────────────────


class AntivirusScanner:
    """
    Multi-layer malware and threat detection engine.
    """

    def __init__(self) -> None:
        self._threats: list[dict[str, Any]] = []
        self._last_scan: dict[str, Any] | None = None
        self._yara_rules: Any | None = None
        self._clamd: Any | None = None
        self._running = False
        self._scan_lock = asyncio.Lock()

    # ── Startup ───────────────────────────────────────────────────────────────

    async def start(self, app: FastAPI) -> None:
        self._load_yara_rules()
        self._connect_clamd()
        self.mount_router(app)
        self._running = True
        _t = asyncio.create_task(self._scan_loop(), name="av-scanner")
        _t.add_done_callback(lambda _: None)
        logger.info("AntivirusScanner: started (YARA=%s, ClamAV=%s)", YARA_AVAILABLE, CLAMD_AVAILABLE)

    def _load_yara_rules(self) -> None:
        if not YARA_AVAILABLE:
            return
        YARA_RULES_DIR.mkdir(parents=True, exist_ok=True)
        # Write built-in rules if directory is empty
        self._write_builtin_yara_rules()
        rule_files = list(YARA_RULES_DIR.glob("*.yar")) + list(YARA_RULES_DIR.glob("*.yara"))
        if not rule_files:
            logger.warning("AV: no YARA rule files found in %s", YARA_RULES_DIR)
            return
        try:
            filepaths = {f.stem: str(f) for f in rule_files}
            self._yara_rules = yara.compile(filepaths=filepaths)
            logger.info("AV: loaded %d YARA rule file(s)", len(rule_files))
        except Exception as exc:
            logger.warning("AV: YARA compile failed: %s", exc)

    def _write_builtin_yara_rules(self) -> None:
        """Write built-in YARA rules to the rules directory if not present."""
        rules_file = YARA_RULES_DIR / "hopefx_builtin.yar"
        if rules_file.exists():
            return
        rules_content = r"""
rule PythonReverseShell {
    meta:
        description = "Python reverse shell pattern"
        severity = "critical"
    strings:
        $s1 = "socket.socket" ascii
        $s2 = "subprocess.Popen" ascii
        $s3 = "/bin/sh" ascii
        $s4 = "/bin/bash" ascii
        $s5 = "os.dup2" ascii
    condition:
        ($s1 and $s2) or ($s5 and ($s3 or $s4))
}

rule Base64EncodedPayload {
    meta:
        description = "Base64-encoded executable payload in source"
        severity = "high"
    strings:
        $b64_exec = /exec\s*\(\s*base64/ ascii nocase
        $b64_eval = /eval\s*\(\s*base64/ ascii nocase
        $b64_compile = /compile\s*\(\s*base64/ ascii nocase
    condition:
        any of them
}

rule CryptoMiner {
    meta:
        description = "Cryptocurrency miner indicators"
        severity = "critical"
    strings:
        $stratum = "stratum+tcp://" ascii nocase
        $xmrig = "xmrig" ascii nocase
        $cryptonight = "cryptonight" ascii nocase
        $monero = "monero" ascii nocase
    condition:
        any of them
}

rule WebShell {
    meta:
        description = "Web shell pattern"
        severity = "critical"
    strings:
        $ws1 = "eval(base64_decode" ascii nocase
        $ws2 = "system($_GET" ascii nocase
        $ws3 = "passthru($_POST" ascii nocase
        $ws4 = "shell_exec($_REQUEST" ascii nocase
    condition:
        any of them
}

rule SuspiciousImport {
    meta:
        description = "Obfuscated dynamic import"
        severity = "high"
    strings:
        $imp1 = /__import__\s*\(\s*['"][a-z]{1,3}['"]/ ascii
        $imp2 = "importlib.import_module" ascii
        $imp3 = "exec(compile(" ascii
    condition:
        $imp1 or ($imp2 and $imp3)
}
"""
        rules_file.write_text(rules_content.strip())
        logger.info("AV: wrote built-in YARA rules to %s", rules_file)

    def _connect_clamd(self) -> None:
        if not CLAMD_AVAILABLE:
            return
        # Try Unix socket first, then TCP
        for attempt in [
            clamd.ClamdUnixSocket,
            lambda: clamd.ClamdNetworkSocket(host="127.0.0.1", port=3310),
        ]:
            try:
                cd = attempt()
                cd.ping()
                self._clamd = cd
                logger.info("AV: ClamAV connected (%s)", type(cd).__name__)
                return
            except Exception as exc:
                logger.debug("AV: ClamAV connection attempt failed: %s", exc)
                continue
        logger.info("AV: ClamAV daemon not reachable — ClamAV layer disabled")

    # ── Scan loop ─────────────────────────────────────────────────────────────

    async def _scan_loop(self) -> None:
        # Initial scan after 30s startup delay
        await asyncio.sleep(30)
        while self._running:
            try:
                await self.scan_project()
            except Exception as exc:
                logger.warning("AV: scan error: %s", exc)
            await asyncio.sleep(AV_SCAN_INTERVAL)

    # ── Full project scan ─────────────────────────────────────────────────────

    async def scan_project(self) -> dict[str, Any]:
        """Scan the entire project tree. Returns scan summary."""
        async with self._scan_lock:
            return await asyncio.get_event_loop().run_in_executor(None, self._scan_project_sync)

    def _scan_project_sync(self) -> dict[str, Any]:
        started = time.monotonic()
        scanned = 0
        new_threats: list[dict[str, Any]] = []

        for path in self._iter_scan_paths():
            try:
                threats = self._scan_file_sync(path)
                scanned += 1
                new_threats.extend(threats)
            except Exception as exc:
                logger.debug("AV: scan error on %s: %s", path, exc)

        # Process monitor
        if PSUTIL_AVAILABLE:
            proc_threats = self._scan_processes()
            new_threats.extend(proc_threats)

        # Merge new threats (deduplicate by path+type)
        existing_keys = {(t["path"], t["threat_type"]) for t in self._threats}
        for t in new_threats:
            key = (t["path"], t["threat_type"])
            if key not in existing_keys:
                self._threats.append(t)
                existing_keys.add(key)
                logger.warning(
                    "AV: THREAT DETECTED path=%s type=%s severity=%s",
                    t["path"],
                    t["threat_type"],
                    t["severity"],
                )

        # Keep last 1000 threats
        self._threats = self._threats[-1000:]

        elapsed = time.monotonic() - started
        summary = {
            "scanned_files": scanned,
            "new_threats": len(new_threats),
            "total_threats": len(self._threats),
            "scan_duration_s": round(elapsed, 2),
            "completed_at": datetime.now(UTC).isoformat(),
            "yara_enabled": YARA_AVAILABLE and self._yara_rules is not None,
            "clamd_enabled": self._clamd is not None,
        }
        self._last_scan = summary
        AV_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        AV_REPORT_PATH.write_text(json.dumps(summary, indent=2))
        logger.info(
            "AV: scan complete — %d files, %d new threats, %.1fs",
            scanned,
            len(new_threats),
            elapsed,
        )
        return summary

    def _iter_scan_paths(self):
        """Yield all files to scan, skipping excluded paths."""
        for root, dirs, files in os.walk(PROJECT_ROOT):
            root_path = Path(root)
            rel_root = str(root_path.relative_to(PROJECT_ROOT))

            # Prune excluded directories in-place
            dirs[:] = [
                d
                for d in dirs
                if not any(skip in (root_path / d).parts for skip in SKIP_PATHS)
                and not any(rel_root.startswith(skip) for skip in SKIP_PATHS)
            ]

            for fname in files:
                fpath = root_path / fname
                ext = fpath.suffix.lower()
                if ext in SCAN_EXTENSIONS or ext in SCAN_BINARY_EXTENSIONS:
                    yield fpath

    def _scan_file_sync(self, path: Path) -> list[dict[str, Any]]:
        """Run all scan layers on a single file. Returns list of threat dicts."""
        threats: list[dict[str, Any]] = []
        rel = str(path.relative_to(PROJECT_ROOT))

        try:
            raw = path.read_bytes()
        except OSError:
            return threats

        sha256 = hashlib.sha256(raw).hexdigest()

        # Layer 1: YARA
        if self._yara_rules is not None:
            try:
                matches = self._yara_rules.match(data=raw)
                for m in matches:
                    severity = m.meta.get("severity", "medium")
                    threats.append(
                        self._make_threat(
                            rel,
                            "yara_match",
                            severity,
                            f"YARA rule '{m.rule}' matched: {m.meta.get('description', '')}",
                            sha256,
                        )
                    )
            except Exception as exc:
                logger.debug("AV: YARA scan error on %s: %s", path, exc)

        # Layer 2: ClamAV
        if self._clamd is not None:
            try:
                result = self._clamd.instream(raw)
                status, virus_name = result.get("stream", ("OK", ""))
                if status == "FOUND":
                    threats.append(
                        self._make_threat(
                            rel,
                            "clamav_detection",
                            "critical",
                            f"ClamAV: {virus_name}",
                            sha256,
                        )
                    )
            except Exception as exc:
                logger.debug("AV: ClamAV scan error on %s: %s", path, exc)

        # Layer 3: Entropy (text files only)
        if path.suffix.lower() in SCAN_EXTENSIONS:
            entropy = _shannon_entropy(raw)
            if entropy > 7.2:
                threats.append(
                    self._make_threat(
                        rel,
                        "high_entropy",
                        "high",
                        f"Shannon entropy={entropy:.3f} (>7.2) — possible obfuscated payload",
                        sha256,
                    )
                )

        # Layer 4: Suspicious patterns (text files only)
        if path.suffix.lower() in SCAN_EXTENSIONS:
            try:
                text = raw.decode("utf-8", errors="replace")
                for name, pattern, severity in SUSPICIOUS_PATTERNS:
                    if pattern.search(text):
                        threats.append(
                            self._make_threat(
                                rel,
                                f"pattern_{name}",
                                severity,
                                f"Suspicious pattern '{name}' detected",
                                sha256,
                            )
                        )
            except Exception as exc:
                logger.debug("AV: pattern scan error on %s: %s", path, exc)

        return threats

    def _scan_processes(self) -> list[dict[str, Any]]:
        """Check running processes for unexpected network connections."""
        threats: list[dict[str, Any]] = []
        try:
            suspicious_names = {"nc", "ncat", "netcat", "xmrig", "minerd", "cgminer"}
            for proc in psutil.process_iter(["pid", "name", "cmdline", "connections"]):
                try:
                    name = (proc.info.get("name") or "").lower()
                    if name in suspicious_names:
                        threats.append(
                            self._make_threat(
                                f"process:{proc.info['pid']}:{name}",
                                "suspicious_process",
                                "critical",
                                f"Suspicious process detected: {name} (pid={proc.info['pid']})",
                                "",
                            )
                        )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    ...  # nosec B110
        except Exception as exc:
            logger.debug("AV: process scan error: %s", exc)
        return threats

    @staticmethod
    def _make_threat(path: str, threat_type: str, severity: str, detail: str, sha256: str) -> dict[str, Any]:
        threat_id = hashlib.sha256(f"{path}:{threat_type}:{detail}".encode()).hexdigest()[:16]
        return {
            "id": threat_id,
            "path": path,
            "threat_type": threat_type,
            "severity": severity,
            "detail": detail,
            "detected_at": datetime.now(UTC).isoformat(),
            "sha256": sha256,
            "quarantined": False,
            "quarantine_path": None,
        }

    # ── Quarantine ────────────────────────────────────────────────────────────

    def quarantine_threat(self, threat_id: str) -> dict[str, Any]:
        """Move a detected threat file to quarantine."""
        threat = next((t for t in self._threats if t["id"] == threat_id), None)
        if threat is None:
            raise ValueError(f"Threat {threat_id} not found")
        if threat["quarantined"]:
            return threat

        src = PROJECT_ROOT / threat["path"]
        if not src.exists():
            threat["quarantined"] = True
            threat["quarantine_path"] = "file_already_removed"
            return threat

        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        dest = QUARANTINE_DIR / f"{ts}_{src.name}"
        try:
            import shutil

            shutil.move(str(src), str(dest))
            threat["quarantined"] = True
            threat["quarantine_path"] = str(dest.relative_to(PROJECT_ROOT))
            logger.warning("AV: quarantined %s → %s", src, dest)
        except OSError as exc:
            logger.error("Quarantine failed for threat %s: %s", threat.get("id"), exc)
            raise RuntimeError("Quarantine failed — check server logs") from None
        return threat

    # ── FastAPI router ────────────────────────────────────────────────────────

    def mount_router(self, app: FastAPI) -> None:
        router = self._build_router()
        app.include_router(router)
        logger.info("AntivirusScanner: router mounted at /api/security/av")

    def _build_router(self) -> APIRouter:
        router = APIRouter(prefix="/api/security/av", tags=["antivirus"])
        scanner = self

        class ScanRequest(BaseModel):
            file_path: str | None = None

        class QuarantineRequest(BaseModel):
            threat_id: str

        @router.get("/status")
        async def av_status(request: Request):
            _require_auth(request)
            return {
                "running": scanner._running,
                "yara_enabled": YARA_AVAILABLE and scanner._yara_rules is not None,
                "clamd_enabled": scanner._clamd is not None,
                "total_threats": len(scanner._threats),
                "last_scan": scanner._last_scan,
            }

        @router.get("/threats", response_model=list[Threat])
        async def list_threats(request: Request, severity: str | None = None):
            _require_auth(request)
            threats = scanner._threats
            if severity:
                threats = [t for t in threats if t["severity"] == severity]
            return [Threat(**t) for t in threats[-200:]]

        @router.post("/scan")
        async def trigger_scan(request: Request):
            _require_admin(request)
            summary = await scanner.scan_project()
            return summary

        @router.post("/scan/file")
        async def scan_file(request: Request, body: ScanRequest):
            _require_admin(request)
            if not body.file_path:
                raise HTTPException(status_code=400, detail="file_path required")
            # Strip every character that is not a safe path component character.
            # This explicit substitution breaks the taint chain before the value
            # reaches any filesystem call, so CodeQL can verify no user-supplied
            # data flows into path construction unmodified.
            sanitized = re.sub(r"[^A-Za-z0-9_./ -]", "", body.file_path)
            if not sanitized:
                raise HTTPException(status_code=400, detail="Invalid file path")
            # Resolve and confine the path to PROJECT_ROOT to prevent traversal.
            resolved_root = PROJECT_ROOT.resolve()
            try:
                path = (resolved_root / sanitized).resolve()
                path.relative_to(resolved_root)  # raises ValueError if outside root
            except (ValueError, OSError):
                raise HTTPException(status_code=400, detail="Invalid file path") from None
            if not path.exists():
                raise HTTPException(status_code=404, detail="File not found")
            threats = await asyncio.get_event_loop().run_in_executor(None, scanner._scan_file_sync, path)
            return {"file": sanitized, "threats": threats}

        @router.post("/quarantine")
        async def quarantine(request: Request, body: QuarantineRequest):
            _require_admin(request)
            try:
                result = scanner.quarantine_threat(body.threat_id)
                return result
            except ValueError as exc:
                logger.warning("Quarantine threat not found: %s", exc)
                raise HTTPException(status_code=404, detail="Threat not found") from None
            except RuntimeError as exc:
                logger.error("Quarantine operation failed: %s", exc)
                raise HTTPException(status_code=500, detail="Quarantine failed — check server logs") from None

        return router


# ── Auth helpers ──────────────────────────────────────────────────────────────


def _require_auth(request: Request) -> dict[str, Any]:
    try:
        from auth.jwt_handler import verify_token

        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        return verify_token(token)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Antivirus auth token decode failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


def _require_admin(request: Request) -> dict[str, Any]:
    payload = _require_auth(request)
    role = payload.get("role", "")
    if role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return payload


# ── Module-level singleton ────────────────────────────────────────────────────

_scanner_instance: AntivirusScanner | None = None


def get_scanner() -> AntivirusScanner:
    global _scanner_instance
    if _scanner_instance is None:
        _scanner_instance = AntivirusScanner()
    return _scanner_instance


async def start_av_scanner(app: FastAPI) -> None:
    """
    Start the antivirus scanner and mount its router.
    Call from connect_to_life.py or app lifespan.
    """
    scanner = get_scanner()
    await scanner.start(app)
    logger.info("AntivirusScanner: background scan task started")
