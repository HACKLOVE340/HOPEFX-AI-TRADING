# GitHub Copilot Instructions for HOPEFX AI Trading

## Project Overview
HOPEFX-AI-TRADING is an advanced AI-powered XAU/USD trading framework with machine learning, real-time analysis, multi-broker integration, and intelligent trade execution.

## Technology Stack
- **Language:** Python 3.8+
- **Key Frameworks:**
  - Machine Learning: TensorFlow 2.15.0, PyTorch 2.1.1, scikit-learn 1.3.2
  - Deep Learning: Keras 2.15.0, pytorch-lightning 2.1.2
  - Trading/Backtesting: backtrader 1.9.94, zipline 1.4.5, backtesting 0.3.3
  - Web APIs: Flask 3.0.0, FastAPI 0.109.0
  - Data Analysis: pandas 2.1.3, numpy 1.26.2
- **Databases:** SQLAlchemy 2.0.23, MongoDB (pymongo 4.6.0), Redis 5.0.1
- **Broker APIs:** alpaca-trade-api, python-binance, ccxt, Interactive-Brokers-API

## Installation & Setup

### Environment Setup
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration
```bash
# Copy environment template
cp .env.example .env

# Edit .env with your credentials and configuration
# Set required environment variables:
# - CONFIG_ENCRYPTION_KEY (for secure credential storage)
# - Broker API credentials
# - Database configuration
```

## Build & Test

### Running Tests
```bash
# Run all tests (when available)
pytest

# Run with coverage
pytest --cov=. --cov-report=html
```

### Linting & Code Quality
```bash
# Format code with Black
black .

# Check code style
flake8 .

# Run pylint
pylint config/ cache/ database/
```

## Code Style Guidelines

### Python Style
- Follow PEP 8 style guide
- Use **Black** for code formatting (line length: 88 characters)
- Use type hints for function parameters and return values
- Use docstrings for all modules, classes, and functions

### Docstring Format
Use Google-style docstrings:
```python
def function_name(param1: str, param2: int) -> bool:
    """
    Brief description of the function.
    
    Args:
        param1: Description of param1
        param2: Description of param2
    
    Returns:
        Description of return value
    
    Raises:
        ValueError: When invalid input is provided
    """
```

### Import Organization
```python
# Standard library imports
import os
import json

# Third-party imports
import pandas as pd
import numpy as np

# Local imports
from config.config_manager import ConfigManager
from cache.market_data_cache import MarketDataCache
```

### Naming Conventions
- Classes: `PascalCase` (e.g., `ConfigManager`, `MarketDataCache`)
- Functions/Methods: `snake_case` (e.g., `load_config`, `cache_ohlcv`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_TTL`, `MAX_RETRIES`)
- Private members: prefix with `_` (e.g., `_build_key`, `_cipher`)

## Architecture & Design Patterns

### Configuration Management
- Use `ConfigManager` from `config/config_manager.py` for all configuration
- Encrypt sensitive credentials using the built-in `EncryptionManager`
- Never hardcode API keys, passwords, or secrets in source code
- Load configuration at application startup

### Caching
- Use `MarketDataCache` from `cache/market_data_cache.py` for market data
- Supports multiple timeframes (1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1M)
- Implements TTL (Time-To-Live) for automatic cache expiration
- Provides statistics and monitoring capabilities

### Database Models
- Use SQLAlchemy for database models
- Define models in `database/models.py`
- Follow the existing model patterns for consistency

### Logging
- Use Python's built-in `logging` module
- Configure logging via `LoggingConfig` in configuration
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Include context in log messages (symbol, timeframe, operation)

## Security Best Practices

### Credential Management
- **NEVER** commit credentials, API keys, or secrets to version control
- Use environment variables or encrypted configuration
- Use `.env` file for local development (excluded in `.gitignore`)
- Set `CONFIG_ENCRYPTION_KEY` environment variable for encryption

### API Security
- Always use sandbox/testnet mode for development and testing
- Set `sandbox_mode: true` in API configurations
- Validate and sanitize all external inputs
- Implement rate limiting for API calls

### Trading Safety
- Default to `paper_trading_mode: true`
- Require explicit opt-in for live trading (`trading_enabled: true`)
- Implement daily loss limits and risk per trade limits
- Never bypass risk management controls

## Workflow & Development Process

### Before Making Changes
1. Review existing code structure and patterns
2. Check for similar implementations in the codebase
3. Understand the configuration and dependencies
4. Run linters and tests to establish baseline

### Making Changes
1. Follow the existing code structure and patterns
2. Add type hints to all new functions and methods
3. Write comprehensive docstrings
4. Implement proper error handling with logging
5. Encrypt sensitive data when necessary
6. Use configuration management for settings

### After Making Changes
1. Format code with Black: `black .`
2. Check with flake8: `flake8 .`
3. Run pylint on modified modules
4. Test your changes thoroughly
5. Update documentation if needed

### Commit Messages
- Use clear, descriptive commit messages
- Follow conventional commits format: `type(scope): description`
- Types: feat, fix, docs, style, refactor, test, chore
- Examples:
  - `feat(cache): add multi-timeframe caching support`
  - `fix(config): handle missing encryption key gracefully`
  - `docs(readme): update installation instructions`

## File and Directory Restrictions

### Do Not Modify
- `.env.example` - Template file for environment variables
- `LICENSE` - Project license file
- Database migration files (when present)
- Credential files in `.gitignore`

### Do Not Create/Edit in Source Control
- `.env` - Contains sensitive credentials
- `*.pyc`, `__pycache__/` - Python bytecode
- `logs/` - Log files directory
- `data/` - Local data storage
- `*.db` - SQLite database files
- Virtual environment directories (`venv/`, `env/`)

## Trading-Specific Guidelines

### Market Data
- Always validate timestamps and ensure data is sorted
- Handle missing data gracefully with logging
- Use appropriate timeframes for different strategies
- Cache frequently accessed market data

### Risk Management
- Never remove or bypass existing risk controls
- Validate position sizes and leverage limits
- Implement stop-loss and take-profit logic
- Log all trading decisions and risk calculations

### Broker Integration
- Handle API rate limits appropriately
- Implement retry logic with exponential backoff
- Log all API calls and responses (excluding sensitive data)
- Use sandbox/testnet APIs for development

### Machine Learning
- Document model architecture and hyperparameters
- Version control trained models separately
- Validate model inputs and outputs
- Monitor model performance metrics
- Implement confidence thresholds for predictions

## Dependencies

### Adding New Dependencies
1. Research the package thoroughly
2. Check for security vulnerabilities
3. Verify license compatibility
4. Add to `requirements.txt` with specific version
5. Update documentation if needed
6. Test compatibility with existing packages

### Updating Dependencies
- Update one package at a time when possible
- Test thoroughly after updates
- Document breaking changes
- Update version numbers in `requirements.txt`

## Testing Guidelines

### Test Structure
- Place tests in `tests/` directory (when present)
- Mirror the source code structure
- Name test files as `test_<module_name>.py`

### Test Coverage
- Aim for high test coverage (80%+)
- Test both success and failure cases
- Test edge cases and boundary conditions
- Mock external API calls and database operations

### Testing Financial Logic
- Use known test cases with verified results
- Test risk calculations with extreme values
- Verify proper handling of market data gaps
- Test timezone and timestamp handling

## Additional Notes

### Performance Considerations
- Use NumPy/pandas for numerical operations
- Implement caching for expensive computations
- Use async/await for I/O-bound operations
- Profile code before optimizing

### Error Handling
- Use try-except blocks for external API calls
- Log errors with full context
- Return meaningful error messages
- Fail gracefully without exposing sensitive information

### Documentation
- Keep README.md up to date
- Document complex algorithms and business logic
- Include usage examples in docstrings
- Maintain inline comments for non-obvious code

## Resources

- Python PEP 8 Style Guide: https://www.python.org/dev/peps/pep-0008/
- Black Code Formatter: https://black.readthedocs.io/
- Type Hints (PEP 484): https://www.python.org/dev/peps/pep-0484/
- SQLAlchemy Documentation: https://docs.sqlalchemy.org/
- Redis Python Documentation: https://redis-py.readthedocs.io/
