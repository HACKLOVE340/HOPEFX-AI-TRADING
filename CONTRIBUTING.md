# CONTRIBUTING

Thank you for your interest in contributing to the HOPEFX AI Trading Framework!

## How to Contribute

### Reporting Issues

1. **Search existing issues** first to avoid duplicates
2. **Use issue templates** when available
3. **Provide details**:
   - Python version
   - Operating system
   - Error messages and stack traces
   - Steps to reproduce
   - Expected vs actual behavior

### Suggesting Features

1. **Check existing feature requests** in issues
2. **Describe the use case** and why it's valuable
3. **Provide examples** of how it would work
4. **Consider backwards compatibility**

### Pull Requests

1. **Fork the repository**
2. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Make your changes**
   - Follow the code style (see below)
   - Add tests for new functionality
   - Update documentation
   - Keep changes focused and atomic

4. **Test your changes**
   ```bash
   # Run tests
   pytest

   # Run linters
   black .
   flake8 .
   pylint hopefx
   ```

5. **Commit with clear messages**
   ```bash
   git commit -m "feat: add new trading strategy"
   ```

6. **Push to your fork**
   ```bash
   git push origin feature/your-feature-name
   ```

7. **Open a Pull Request**
   - Describe what changed and why
   - Reference related issues
   - Wait for review

## Development Setup

### 1. Clone and Install

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING

# Add upstream remote
git remote add upstream https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install in development mode
pip install -e ".[dev]"
```

### 2. Set Up Pre-commit Hooks (Optional)

```bash
# Install pre-commit
pip install pre-commit

# Set up hooks
pre-commit install
```

### 3. Run Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=term-missing

# Run specific test file
pytest tests/test_config.py
```

## Code Style

### Python Style Guide

We follow PEP 8 with some modifications:

- **Line length**: 100 characters (not 79)
- **Strings**: Use double quotes `"` for strings
- **Imports**: Organized in groups (standard library, third-party, local)
- **Type hints**: Use type hints for function signatures
- **Docstrings**: Use Google-style docstrings

### Example

```python
"""
Module docstring explaining what this module does.
"""

import os
from typing import Optional, Dict, Any

from fastapi import FastAPI
from pydantic import BaseModel

from config import ConfigManager


class TradingStrategy:
    """
    A trading strategy implementation.
    
    This class implements a trend-following strategy based on
    moving average crossovers.
    
    Attributes:
        name: Strategy name
        config: Configuration dictionary
    """
    
    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        """
        Initialize trading strategy.
        
        Args:
            name: Name of the strategy
            config: Optional configuration dictionary
        """
        self.name = name
        self.config = config or {}
    
    def generate_signal(self, data: Dict[str, Any]) -> str:
        """
        Generate trading signal from market data.
        
        Args:
            data: Market data dictionary
            
        Returns:
            Signal as string ('BUY', 'SELL', or 'HOLD')
            
        Raises:
            ValueError: If data is invalid
        """
        if not data:
            raise ValueError("Data cannot be empty")
        
        # Implementation here
        return "HOLD"
```

### Code Formatting

Use Black for automatic formatting:

```bash
# Format all Python files
black .

# Check without modifying
black --check .
```

### Linting

```bash
# Run flake8
flake8 .

# Run pylint
pylint hopefx config cache database

# Run mypy for type checking
mypy .
```

## Project Structure

```
HOPEFX-AI-TRADING/
├── config/          # Configuration management
├── cache/           # Market data caching
├── database/        # Database models
├── brokers/         # Broker integrations
├── strategies/      # Trading strategies
├── ml/              # Machine learning models
├── risk/            # Risk management
├── api/             # API endpoints
├── notifications/   # Notification system
├── tests/           # Test files
├── docs/            # Documentation
├── main.py          # Main entry point
├── app.py           # API server
├── cli.py           # CLI interface
└── setup.py         # Package setup
```

## Testing Guidelines

### Writing Tests

1. **Use pytest** for all tests
2. **Name test files** with `test_` prefix
3. **Name test functions** with `test_` prefix
4. **One test per behavior**
5. **Use fixtures** for common setup
6. **Mock external services** (APIs, databases)

### Example Test

```python
"""Tests for configuration manager"""

import pytest
import os
from config import ConfigManager, EncryptionManager


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create temporary configuration directory"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def encryption_key():
    """Provide test encryption key"""
    return "test-key-minimum-32-characters-long"


def test_config_manager_init(temp_config_dir, encryption_key):
    """Test ConfigManager initialization"""
    os.environ['CONFIG_ENCRYPTION_KEY'] = encryption_key
    
    manager = ConfigManager(str(temp_config_dir))
    
    assert manager.config_dir == temp_config_dir
    assert manager.encryption is not None


def test_encryption_roundtrip(encryption_key):
    """Test encryption and decryption"""
    os.environ['CONFIG_ENCRYPTION_KEY'] = encryption_key
    
    em = EncryptionManager()
    original = "sensitive-data"
    
    encrypted = em.encrypt(original)
    decrypted = em.decrypt(encrypted)
    
    assert decrypted == original
    assert encrypted != original


def test_password_hashing(encryption_key):
    """Test password hashing and verification"""
    os.environ['CONFIG_ENCRYPTION_KEY'] = encryption_key
    
    em = EncryptionManager()
    password = "test123"
    
    hashed = em.hash_password(password)
    
    assert em.verify_password("test123", hashed) is True
    assert em.verify_password("wrong", hashed) is False
```

## Documentation

### Docstrings

Use Google-style docstrings:

```python
def calculate_position_size(
    account_balance: float,
    risk_percent: float,
    stop_loss_pips: float
) -> float:
    """
    Calculate position size based on risk parameters.
    
    Uses the fixed fractional position sizing method to determine
    the appropriate position size given account balance and risk.
    
    Args:
        account_balance: Total account balance in base currency
        risk_percent: Percentage of account to risk (e.g., 2.0 for 2%)
        stop_loss_pips: Stop loss distance in pips
        
    Returns:
        Position size in lots
        
    Raises:
        ValueError: If any parameter is negative or zero
        
    Example:
        >>> calculate_position_size(10000, 2.0, 50)
        0.04
    """
    if account_balance <= 0 or risk_percent <= 0 or stop_loss_pips <= 0:
        raise ValueError("All parameters must be positive")
    
    # Implementation
    return 0.04
```

### README and Guides

- Keep documentation up to date
- Add examples for new features
- Update installation guide if dependencies change
- Include usage examples

## Commit Messages

Follow conventional commits:

```
type(scope): subject

body

footer
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

### Examples

```
feat(strategies): add MACD crossover strategy

Implement a new strategy based on MACD indicator crossovers.
Includes entry/exit logic and risk management.

Closes #123

---

fix(cache): resolve thread safety issue in statistics

Add proper locking around cache statistics updates to prevent
race conditions in concurrent access.

Fixes #456

---

docs(readme): update installation instructions

Add section for Windows installation and update
Python version requirements to 3.8+.
```

## Review Process

### What We Look For

1. **Code Quality**
   - Follows style guide
   - Well-documented
   - Properly tested
   - No unnecessary complexity

2. **Functionality**
   - Solves the problem
   - No regressions
   - Handles edge cases
   - Error handling

3. **Testing**
   - Adequate test coverage
   - Tests pass
   - Tests are meaningful

4. **Documentation**
   - Code is documented
   - README updated if needed
   - Examples provided

### Response Time

- We aim to review PRs within 1 week
- Complex PRs may take longer
- Tag maintainers if no response after 2 weeks

## Security

### Reporting Vulnerabilities

**DO NOT** open public issues for security vulnerabilities.

Instead:
1. Email: security@hopefx.ai
2. Provide details privately
3. Wait for confirmation before disclosure

### Security Best Practices

- Never commit credentials
- Use environment variables for sensitive data
- Encrypt sensitive data at rest
- Validate all user input
- Use parameterized queries
- Keep dependencies updated

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## Questions?

- Open a discussion on GitHub
- Check existing documentation
- Ask in pull request comments

Thank you for contributing! 🎉
