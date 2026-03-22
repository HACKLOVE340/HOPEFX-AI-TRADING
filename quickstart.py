# File 19: Create a quickstart script for one-command setup

quickstart_content = '''#!/usr/bin/env python3
"""
HOPEFX Quickstart Script
One-command setup and demo runner.
"""

import subprocess
import sys
import os
from pathlib import Path

def run_command(cmd, description):
    """Run a shell command with error handling."""
    print(f"\\n{'='*60}")
    print(f"📦 {description}")
    print(f"{'='*60}")
    print(f"$ {' '.join(cmd)}\\n")
    
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print(f"❌ Failed: {description}")
        return False
    return True

def main():
    """Main quickstart flow."""
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   HOPEFX AI Trading Framework - Quickstart                   ║
║   Alpha Prototype - Paper Trading Demo                       ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    # Check Python version
    if sys.version_info < (3, 8):
        print("❌ Python 3.8+ required")
        return 1
    
    # Setup paths
    base_dir = Path(__file__).parent
    os.chdir(base_dir)
    
    # Step 1: Create virtual environment (optional but recommended)
    venv_path = base_dir / "venv"
    if not venv_path.exists():
        print("📁 Creating virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", "venv"])
        print("✅ Virtual environment created")
        print("   Activate with: source venv/bin/activate (Linux/Mac)")
        print("                  venv\\Scripts\\activate (Windows)")
    
    # Step 2: Install dependencies
    if not run_command([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"], 
                      "Installing dependencies"):
        print("⚠️  Some dependencies may have failed (optional packages)")
    
    # Step 3: Setup environment
    env_file = base_dir / ".env"
    if not env_file.exists():
        print("\\n📄 Creating .env file from template...")
        env_example = base_dir / ".env.example"
        if env_example.exists():
            env_content = env_example.read_text()
            # Generate secure keys
            import secrets
            key = secrets.token_hex(32)
            salt = secrets.token_hex(16)
            env_content = env_content.replace(
                "CONFIG_ENCRYPTION_KEY=replace_with_64_char_hex_key_for_development",
                f"CONFIG_ENCRYPTION_KEY={key}"
            )
            env_content = env_content.replace(
                "CONFIG_SALT=replace_with_32_char_hex_salt",
                f"CONFIG_SALT={salt}"
            )
            env_file.write_text(env_content)
            print("✅ .env file created with secure keys")
        else:
            print("⚠️  .env.example not found, skipping")
    else:
        print("✅ .env file already exists")
    
    # Step 4: Create directories
    print("\\n📁 Creating directories...")
    for dir_name in ["logs", "data", "results", "credentials"]:
        Path(dir_name).mkdir(exist_ok=True)
    print("✅ Directories ready")
    
    # Step 5: Run tests
    print("\\n🧪 Running tests...")
    test_result = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"])
    if test_result.returncode == 0:
        print("✅ Tests passed")
    else:
        print("⚠️  Some tests failed (non-critical for demo)")
    
    # Step 6: Run paper trading demo
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   🚀 Running Paper Trading Demo (60 seconds)                 ║
║                                                              ║
║   This will simulate XAUUSD trading with:                    ║
║   - Synthetic price data                                     ║
║   - ML signal generation                                     ║
║   - Paper order execution                                    ║
║   - P&L tracking                                             ║
║                                                              ║
║   Press Ctrl+C to stop early                                 ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    demo_result = subprocess.run([
        sys.executable, "scripts/xauusd_bot.py",
        "--mode", "paper",
        "--symbol", "XAUUSD",
        "--duration", "1",
        "--capital", "10000"
    ])
    
    if demo_result.returncode == 0:
        print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   ✅ Demo Complete!                                          ║
║                                                              ║
║   Next steps:                                                ║
║   1. Check results: cat results/xauusd_paper_results.json    ║
║   2. Run backtest: python examples/backtest_example.py       ║
║   3. Start API: python app.py                                ║
║   4. Docker: docker compose up                               ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
        """)
    else:
        print("❌ Demo failed")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''

with open('/mnt/kimi/output/hopefx_upgrade/quickstart.py', 'w') as f:
    f.write(quickstart_content)

print("✅ quickstart.py created - One-command setup and demo")
