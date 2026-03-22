# scripts/security_audit.py
"""
Security audit script to check for secrets and vulnerabilities.
Run before every deployment.
"""
#!/usr/bin/env python3
import ast
import os
import re
import sys
from pathlib import Path

# Patterns that indicate hardcoded secrets
DANGEROUS_PATTERNS = [
    (r'password\s*=\s*["\'][^"\']+["\']', "Hardcoded password"),
    (r'api_key\s*=\s*["\'][^"\']+["\']', "Hardcoded API key"),
    (r'secret\s*=\s*["\'][^"\']+["\']', "Hardcoded secret"),
    (r'token\s*=\s*["\'][^"\']+["\']', "Hardcoded token"),
    (r'default.*key.*=.*["\'][^"\']+["\']', "Default key fallback"),
    (r'["\']dev-key[^"\']*["\']', "Development key"),
    (r'["\']test-key[^"\']*["\']', "Test key"),
    (r'["\']password123["\']', "Weak password"),
    (r'["\']admin["\']', "Default admin"),
    (r'["\']123456["\']', "Weak numeric"),
    (r'os\.getenv\([^)]+\)\s+or\s+["\']', "Env fallback to string"),
    (r'Field\(default\s*=\s*["\'][^"\']{8,}["\']', "Pydantic default secret"),
]

# Files to skip
SKIP_FILES = {".git", "__pycache__", ".venv", "venv", "node_modules"}


def scan_file(filepath: Path) -> list[tuple[int, str, str]]:
    """Scan single file for secrets."""
    issues = []
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
    except (UnicodeDecodeError, IOError):
        return issues
    
    for line_num, line in enumerate(lines, 1):
        for pattern, description in DANGEROUS_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                # Skip comments explaining the pattern
                if line.strip().startswith('#') and 'security' in line.lower():
                    continue
                # Skip docstrings
                if line.strip().startswith('"""') or line.strip().startswith("'''"):
                    continue
                issues.append((line_num, description, line.strip()))
    
    return issues


def check_env_file() -> list[str]:
    """Check .env file exists and is not committed."""
    issues = []
    
    env_file = Path('.env')
    env_example = Path('.env.example')
    
    if not env_file.exists():
        issues.append("CRITICAL: .env file not found")
    
    if env_file.exists():
        # Check if .env is in .gitignore
        gitignore = Path('.gitignore')
        if gitignore.exists():
            with open(gitignore) as f:
                if '.env' not in f.read():
                    issues.append("CRITICAL: .env not in .gitignore")
        
        # Check for default/example values
        with open(env_file) as f:
            content = f.read()
            if 'your-' in content or 'example' in content.lower():
                issues.append("WARNING: .env contains placeholder values")
            if 'dev-key' in content or 'test-key' in content:
                issues.append("CRITICAL: .env contains development keys")
    
    return issues


def main() -> int:
    """Run security audit."""
    print("="*80)
    print("HOPEFX SECURITY AUDIT")
    print("="*80)
    
    all_issues = []
    
    # Scan Python files
    print("\n[1/3] Scanning Python files for hardcoded secrets...")
    for py_file in Path('src').rglob('*.py'):
        if any(skip in str(py_file) for skip in SKIP_FILES):
            continue
        
        issues = scan_file(py_file)
        for line_num, desc, line in issues:
            all_issues.append(f"{py_file}:{line_num}: {desc}")
            print(f"  ❌ {py_file}:{line_num}: {desc}")
            print(f"     {line[:80]}...")
    
    # Check environment files
    print("\n[2/3] Checking environment files...")
    env_issues = check_env_file()
    for issue in env_issues:
        all_issues.append(issue)
        prefix = "❌" if "CRITICAL" in issue else "⚠️"
        print(f"  {prefix} {issue}")
    
    # Check for common mistakes
    print("\n[3/3] Checking for security anti-patterns...")
    
    # Check CORS
    api_main = Path('src/hopefx/api/main.py')
    if api_main.exists():
        content = api_main.read_text()
        if 'allow_methods=["*"]' in content:
            all_issues.append("CORS allows all methods (security risk)")
            print("  ❌ CORS allow_methods=[*] detected")
        if 'allow_origins=["*"]' in content:
            all_issues.append("CORS allows all origins (security risk)")
            print("  ❌ CORS allow_origins=[*] detected")
    
    # Check for debug mode
    settings_file = Path('src/hopefx/config/settings.py')
    if settings_file.exists():
        content = settings_file.read_text()
        if 'debug: bool = True' in content:
            all_issues.append("Debug mode default is True")
            print("  ❌ Debug mode defaults to True")
    
    # Summary
    print("\n" + "="*80)
    print("AUDIT SUMMARY")
    print("="*80)
    
    critical = [i for i in all_issues if 'CRITICAL' in i or 'dev-key' in i]
    warnings = [i for i in all_issues if i not in critical]
    
    print(f"\nCritical issues: {len(critical)}")
    print(f"Warnings: {len(warnings)}")
    
    if critical:
        print("\n❌ AUDIT FAILED - Fix critical issues before deployment")
        return 1
    elif warnings:
        print("\n⚠️  AUDIT PASSED WITH WARNINGS")
        return 0
    else:
        print("\n✅ AUDIT PASSED - No security issues found")
        return 0


if __name__ == "__main__":
    sys.exit(main())
