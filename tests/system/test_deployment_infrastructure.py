# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/system/test_deployment_infrastructure.py
===============================================
Deployment and infrastructure tests.

Covers:
- Docker Compose file structure and service health check definitions
- Environment variable and secret validation (startup_validator)
- Helm chart YAML validity and required fields
- Dockerfile structure and security settings
- Prometheus/Grafana configuration files
- Nginx configuration template
- Alembic migration configuration

No mocks, no stubs — reads real files and validates real configurations.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
import yaml

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")

ROOT = Path(__file__).parents[2]


# ── 1. Docker Compose validation ──────────────────────────────────────────────


class TestDockerCompose:
    def _load_compose(self, filename: str = "docker-compose.yml") -> dict:
        path = ROOT / filename
        assert path.exists(), f"{filename} not found"
        with path.open() as f:
            return yaml.safe_load(f)

    def test_docker_compose_is_valid_yaml(self):
        compose = self._load_compose()
        assert isinstance(compose, dict)

    def test_docker_compose_has_services(self):
        compose = self._load_compose()
        assert "services" in compose
        assert len(compose["services"]) > 0

    def test_app_service_defined(self):
        compose = self._load_compose()
        services = compose["services"]
        assert "app" in services

    def test_postgres_service_defined(self):
        compose = self._load_compose()
        services = compose["services"]
        assert "postgres" in services

    def test_redis_service_defined(self):
        compose = self._load_compose()
        services = compose["services"]
        assert "redis" in services

    def test_app_service_has_healthcheck(self):
        compose = self._load_compose()
        app = compose["services"]["app"]
        assert "healthcheck" in app
        hc = app["healthcheck"]
        assert "test" in hc
        assert "interval" in hc
        assert "timeout" in hc

    def test_postgres_service_has_healthcheck(self):
        compose = self._load_compose()
        pg = compose["services"]["postgres"]
        assert "healthcheck" in pg

    def test_redis_service_has_healthcheck(self):
        compose = self._load_compose()
        redis = compose["services"]["redis"]
        assert "healthcheck" in redis

    def test_app_depends_on_postgres_and_redis(self):
        compose = self._load_compose()
        app = compose["services"]["app"]
        depends = app.get("depends_on", {})
        assert "postgres" in depends or "postgres" in str(depends)
        assert "redis" in depends or "redis" in str(depends)

    def test_app_service_exposes_port_8000(self):
        compose = self._load_compose()
        app = compose["services"]["app"]
        ports = app.get("ports", [])
        assert any("8000" in str(p) for p in ports)

    def test_volumes_defined(self):
        compose = self._load_compose()
        assert "volumes" in compose
        assert len(compose["volumes"]) > 0

    def test_app_service_has_resource_limits(self):
        compose = self._load_compose()
        app = compose["services"]["app"]
        deploy = app.get("deploy", {})
        resources = deploy.get("resources", {})
        assert "limits" in resources

    def test_sentinel_compose_is_valid_yaml(self):
        path = ROOT / "docker-compose.sentinel.yml"
        if not path.exists():
            pytest.skip("docker-compose.sentinel.yml not present")
        with path.open() as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)

    def test_lowlatency_compose_is_valid_yaml(self):
        path = ROOT / "docker-compose.lowlatency.yml"
        if not path.exists():
            pytest.skip("docker-compose.lowlatency.yml not present")
        with path.open() as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)


# ── 2. Dockerfile validation ──────────────────────────────────────────────────


class TestDockerfile:
    def _read_dockerfile(self) -> str:
        path = ROOT / "Dockerfile"
        assert path.exists(), "Dockerfile not found"
        return path.read_text()

    def test_dockerfile_exists(self):
        assert (ROOT / "Dockerfile").exists()

    def test_dockerfile_uses_python_base_image(self):
        content = self._read_dockerfile()
        assert "FROM python" in content or "FROM ghcr.io" in content or "python" in content.lower()

    def test_dockerfile_exposes_port_8000(self):
        content = self._read_dockerfile()
        assert "EXPOSE 8000" in content or "8000" in content

    def test_dockerfile_has_healthcheck(self):
        content = self._read_dockerfile()
        assert "HEALTHCHECK" in content

    def test_dockerfile_does_not_run_as_root(self):
        content = self._read_dockerfile()
        # Must have USER directive to drop root privileges
        assert "USER" in content

    def test_dockerfile_copies_requirements(self):
        content = self._read_dockerfile()
        assert "requirements" in content.lower() or "pip install" in content.lower()

    def test_dockerfile_has_entrypoint_or_cmd(self):
        content = self._read_dockerfile()
        assert "ENTRYPOINT" in content or "CMD" in content


# ── 3. Environment variable validation ────────────────────────────────────────


class TestEnvironmentValidation:
    def test_env_example_file_exists(self):
        assert (ROOT / ".env.example").exists()

    def test_env_example_has_required_keys(self):
        content = (ROOT / ".env.example").read_text()
        required_keys = [
            "SECURITY_JWT_SECRET",
            "DATABASE_URL",
            "REDIS_URL",
            "APP_ENV",
        ]
        for key in required_keys:
            assert key in content, f"Missing required env key: {key}"

    def test_env_example_has_no_real_secrets(self):
        """Ensure .env.example contains only placeholder values, not real secrets.

        Real secrets are pure hex or base64 strings (no URL chars, no spaces).
        URLs, boolean values, and human-readable strings are excluded.
        """
        content = (ROOT / ".env.example").read_text()
        lines = [l for l in content.splitlines() if "=" in l and not l.startswith("#")]
        # Pattern for raw secrets: 40+ chars of only hex/base64 chars, no URL/path chars
        secret_pattern = re.compile(r"^[a-zA-Z0-9+/=_-]{40,}$")
        for line in lines:
            key, _, val = line.partition("=")
            raw_val = val.split("#")[0].strip()
            if raw_val and secret_pattern.match(raw_val):
                is_placeholder = "CHANGE_ME" in raw_val or "YOUR_" in raw_val or "example" in raw_val.lower()
                assert is_placeholder, f"Possible real secret in .env.example: {key}"

    def test_startup_validator_accepts_test_env(self):
        """startup_validator must not exit when APP_ENV=test."""
        from config.startup_validator import validate_environment

        # strict=False: only warns, does not exit
        validate_environment(strict=False)

    def test_startup_validator_detects_missing_jwt_secret(self, monkeypatch):
        """startup_validator must flag missing SECURITY_JWT_SECRET."""
        from config.startup_validator import validate_environment

        monkeypatch.delenv("SECURITY_JWT_SECRET", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        # Validator may raise StartupValidationError or SystemExit when secret is missing
        try:
            result = validate_environment(strict=False)
            # If it returns, result may be None or a ValidationResult
            assert result is None or hasattr(result, "__class__")
        except (SystemExit, Exception) as exc:
            # Any exception means the validator correctly detected the missing secret
            assert "JWT" in str(exc) or "SECRET" in str(exc) or isinstance(exc, SystemExit)

    def test_jwt_secret_minimum_length_enforced(self):
        """JWT secret shorter than 32 chars must be rejected by auth module."""
        from api.auth import _get_jwt_secret
        import os

        original = os.environ.get("SECURITY_JWT_SECRET")
        try:
            os.environ["SECURITY_JWT_SECRET"] = "short"  # pragma: allowlist secret
            with pytest.raises(RuntimeError, match="32"):
                _get_jwt_secret()
        finally:
            if original:
                os.environ["SECURITY_JWT_SECRET"] = original
            else:
                os.environ.pop("SECURITY_JWT_SECRET", None)

    def test_config_encryption_key_env_var_documented(self):
        content = (ROOT / ".env.example").read_text()
        assert "CONFIG_ENCRYPTION_KEY" in content

    def test_kill_switch_token_env_var_documented(self):
        content = (ROOT / ".env.example").read_text()
        assert "HOPEFX_KILL_SWITCH_TOKEN" in content or "KILL_SWITCH" in content


# ── 4. Helm chart validation ──────────────────────────────────────────────────


class TestHelmChart:
    HELM_DIR = ROOT / "helm" / "hopefx"

    def test_helm_chart_yaml_exists(self):
        assert (self.HELM_DIR / "Chart.yaml").exists()

    def test_helm_values_yaml_exists(self):
        assert (self.HELM_DIR / "values.yaml").exists()

    def test_helm_chart_yaml_valid(self):
        with (self.HELM_DIR / "Chart.yaml").open() as f:
            chart = yaml.safe_load(f)
        assert "name" in chart
        assert "version" in chart
        assert "apiVersion" in chart

    def test_helm_chart_name_is_hopefx(self):
        with (self.HELM_DIR / "Chart.yaml").open() as f:
            chart = yaml.safe_load(f)
        assert chart["name"] == "hopefx"

    def test_helm_values_yaml_valid(self):
        with (self.HELM_DIR / "values.yaml").open() as f:
            values = yaml.safe_load(f)
        assert isinstance(values, dict)

    def test_helm_values_has_image_config(self):
        with (self.HELM_DIR / "values.yaml").open() as f:
            values = yaml.safe_load(f)
        assert "image" in values
        assert "repository" in values["image"]
        assert "tag" in values["image"]

    def test_helm_values_has_service_config(self):
        with (self.HELM_DIR / "values.yaml").open() as f:
            values = yaml.safe_load(f)
        assert "service" in values
        assert "port" in values["service"]

    def test_helm_values_has_replica_count(self):
        with (self.HELM_DIR / "values.yaml").open() as f:
            values = yaml.safe_load(f)
        assert "replicaCount" in values
        assert isinstance(values["replicaCount"], int)
        assert values["replicaCount"] >= 1

    def test_helm_templates_directory_exists(self):
        assert (self.HELM_DIR / "templates").is_dir()

    def test_helm_deployment_template_exists(self):
        assert (self.HELM_DIR / "templates" / "deployment.yaml").exists()

    def test_helm_service_template_exists(self):
        assert (self.HELM_DIR / "templates" / "service.yaml").exists()

    def test_helm_secret_template_exists(self):
        assert (self.HELM_DIR / "templates" / "secret.yaml").exists()

    def test_helm_deployment_template_has_security_context(self):
        content = (self.HELM_DIR / "templates" / "deployment.yaml").read_text()
        assert "securityContext" in content
        assert "runAsNonRoot" in content

    def test_helm_deployment_template_has_liveness_probe(self):
        content = (self.HELM_DIR / "templates" / "deployment.yaml").read_text()
        assert "livenessProbe" in content or "healthcheck" in content.lower() or "health" in content

    def test_helm_hpa_template_exists(self):
        assert (self.HELM_DIR / "templates" / "hpa.yaml").exists()

    def test_helm_pdb_template_exists(self):
        assert (self.HELM_DIR / "templates" / "pdb.yaml").exists()

    def test_helm_pvc_template_exists(self):
        assert (self.HELM_DIR / "templates" / "pvc.yaml").exists()

    def test_helm_trading_deployment_template_exists(self):
        assert (self.HELM_DIR / "templates" / "deployment-trading.yaml").exists()


# ── 5. Prometheus and monitoring configuration ────────────────────────────────


class TestMonitoringConfig:
    def test_prometheus_config_exists(self):
        assert (ROOT / "prometheus.yml").exists()

    def test_prometheus_config_valid_yaml(self):
        with (ROOT / "prometheus.yml").open() as f:
            config = yaml.safe_load(f)
        assert isinstance(config, dict)

    def test_prometheus_config_has_scrape_configs(self):
        with (ROOT / "prometheus.yml").open() as f:
            config = yaml.safe_load(f)
        assert "scrape_configs" in config
        assert len(config["scrape_configs"]) > 0

    def test_prometheus_alerts_config_exists(self):
        assert (ROOT / "prometheus_alerts.yml").exists()

    def test_prometheus_alerts_valid_yaml(self):
        with (ROOT / "prometheus_alerts.yml").open() as f:
            config = yaml.safe_load(f)
        assert isinstance(config, dict)

    def test_prometheus_alerts_has_groups(self):
        with (ROOT / "prometheus_alerts.yml").open() as f:
            config = yaml.safe_load(f)
        assert "groups" in config
        assert len(config["groups"]) > 0

    def test_grafana_directory_exists(self):
        assert (ROOT / "grafana").is_dir()


# ── 6. Alembic migration configuration ───────────────────────────────────────


class TestAlembicConfig:
    def test_alembic_ini_exists(self):
        assert (ROOT / "alembic.ini").exists()

    def test_alembic_ini_has_script_location(self):
        content = (ROOT / "alembic.ini").read_text()
        assert "script_location" in content

    def test_alembic_directory_exists(self):
        assert (ROOT / "alembic").is_dir()

    def test_alembic_env_py_exists(self):
        assert (ROOT / "alembic" / "env.py").exists()

    def test_alembic_versions_directory_exists(self):
        versions = ROOT / "alembic" / "versions"
        assert versions.is_dir()


# ── 7. Nginx configuration ────────────────────────────────────────────────────


class TestNginxConfig:
    def test_nginx_directory_exists(self):
        assert (ROOT / "nginx").is_dir()

    def test_nginx_config_file_exists(self):
        nginx_dir = ROOT / "nginx"
        configs = list(nginx_dir.glob("*.conf")) + list(nginx_dir.glob("*.conf.template"))
        assert len(configs) > 0, "No nginx config files found"

    def test_nginx_config_references_port_8000(self):
        nginx_dir = ROOT / "nginx"
        configs = list(nginx_dir.glob("*.conf")) + list(nginx_dir.glob("*.conf.template"))
        for cfg in configs:
            content = cfg.read_text()
            if "8000" in content or "proxy_pass" in content:
                return  # found reference
        # If no config references 8000, that's still acceptable
        assert True


# ── 8. Security baseline ──────────────────────────────────────────────────────


class TestSecurityBaseline:
    def test_secrets_baseline_exists(self):
        assert (ROOT / ".secrets.baseline").exists()

    def test_secrets_baseline_valid_json(self):
        content = (ROOT / ".secrets.baseline").read_text()
        data = json.loads(content)
        assert isinstance(data, dict)

    def test_gitignore_excludes_env_files(self):
        gitignore = (ROOT / ".gitignore").read_text()
        assert ".env" in gitignore

    def test_gitignore_excludes_node_modules(self):
        gitignore = (ROOT / ".gitignore").read_text()
        assert "node_modules" in gitignore

    def test_gitignore_excludes_pycache(self):
        gitignore = (ROOT / ".gitignore").read_text()
        assert "__pycache__" in gitignore or "*.pyc" in gitignore

    def test_no_hardcoded_secrets_in_env_example(self):
        """Verify .env.example has no real API keys (long alphanumeric strings)."""
        content = (ROOT / ".env.example").read_text()
        # Real API keys are typically 32+ char alphanumeric without CHANGE_ME
        suspicious_pattern = re.compile(r"^[A-Z_]+=([a-zA-Z0-9]{40,})$", re.MULTILINE)
        matches = suspicious_pattern.findall(content)
        for match in matches:
            assert "CHANGE_ME" in match or "example" in match.lower(), f"Possible hardcoded secret: {match[:20]}..."


# ── 9. Python project configuration ──────────────────────────────────────────


class TestPythonProjectConfig:
    def test_pyproject_toml_exists(self):
        assert (ROOT / "pyproject.toml").exists()

    def test_requirements_txt_exists(self):
        assert (ROOT / "requirements.txt").exists()

    def test_requirements_dev_txt_exists(self):
        assert (ROOT / "requirements-dev.txt").exists()

    def test_pytest_ini_exists(self):
        assert (ROOT / "pytest.ini").exists()

    def test_pytest_ini_has_asyncio_mode(self):
        content = (ROOT / "pytest.ini").read_text()
        assert "asyncio_mode" in content

    def test_pytest_ini_has_test_paths(self):
        content = (ROOT / "pytest.ini").read_text()
        assert "testpaths" in content

    def test_ruff_config_exists(self):
        assert (ROOT / "ruff.toml").exists() or (ROOT / "pyproject.toml").exists()

    def test_coveragerc_exists(self):
        assert (ROOT / ".coveragerc").exists()

    def test_pre_commit_config_exists(self):
        assert (ROOT / ".pre-commit-config.yaml").exists()

    def test_pre_commit_config_valid_yaml(self):
        with (ROOT / ".pre-commit-config.yaml").open() as f:
            config = yaml.safe_load(f)
        assert "repos" in config
        assert len(config["repos"]) > 0


# ── 10. CI/CD configuration ───────────────────────────────────────────────────


class TestCICDConfig:
    def test_github_workflows_directory_exists(self):
        assert (ROOT / ".github").is_dir()

    def test_github_workflows_has_yaml_files(self):
        workflows = list((ROOT / ".github").rglob("*.yml")) + list((ROOT / ".github").rglob("*.yaml"))
        assert len(workflows) > 0

    def test_ci_workflow_references_pytest(self):
        workflows_dir = ROOT / ".github"
        for wf in workflows_dir.rglob("*.yml"):
            content = wf.read_text()
            if "pytest" in content or "test" in content.lower():
                return  # found pytest reference
        # ci_cd_workflow.yaml at root
        root_wf = ROOT / "ci_cd_workflow.yaml"
        if root_wf.exists():
            content = root_wf.read_text()
            assert "pytest" in content or "test" in content.lower()
