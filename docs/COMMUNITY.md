# HOPEFX Community Guide

> Building a community of traders and developers around open-source algorithmic trading.

---

## Official Channels

### GitHub (Primary)
All development, issues, and discussions happen on GitHub.

**Repository:** [https://github.com/HACKLOVE340/HOPEFX-AI-TRADING](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING)

- **Issues** — bug reports, feature requests
- **Discussions** — questions, strategy ideas, general chat
- **Pull Requests** — code contributions
- **Releases** — version announcements

### Telegram (Primary Community Channel)

The official HOPEFX community channel is on Telegram.

**Join:** Contact support@hopefx.io for the invite link after subscribing.

The platform posts trade signals and alerts to your own private Telegram bot.
Configure in `.env`:
```bash
TELEGRAM_BOT_TOKEN=your_bot_token    # From @BotFather
TELEGRAM_CHAT_ID=your_chat_id        # Your personal or group chat ID
```

Test after configuring:
```bash
curl -X POST http://localhost:8000/api/notifications/test \
  -H "Authorization: Bearer $TOKEN"
```

### Discord (Community Server)

A Discord server is available for subscribers. Contact support@hopefx.io
for the invite link after subscribing.

Channel structure:
```
#announcements    — releases and updates (read-only)
#general          — open discussion
#trading-signals  — paper trading signal sharing
#strategies       — strategy development and ideas
#ml-ai            — machine learning discussion
#backtesting      — backtest results and analysis
#prop-firm        — prop firm challenge discussion
#coding-help      — technical support
#bugs             — link to GitHub Issues
```

### YouTube
Video tutorials covering installation, strategy development, ML training, and deployment.

See [VIDEO_TUTORIALS.md](VIDEO_TUTORIALS.md) for the full episode list and scripts.

---

## Contributing Code

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contribution guide.

**Quick summary:**

```bash
# 1. Fork the repository on GitHub
# 2. Clone your fork
git clone https://github.com/YOUR_USERNAME/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING

# 3. Create a feature branch
git checkout -b feature/your-feature-name

# 4. Install dev dependencies
pip install -r requirements-dev.txt
pre-commit install

# 5. Make your changes and run tests
pytest tests/ -q

# 6. Commit and push
git add .
git commit -m "feat: describe your change"
git push origin feature/your-feature-name

# 7. Open a Pull Request on GitHub
```

**What we welcome:**
- New trading strategies (add to `strategies/`)
- Broker connectors (add to `brokers/`)
- ML feature engineering improvements (add to `ml/`)
- Bug fixes with regression tests
- Documentation improvements
- Translation of docs

**What requires discussion first (open an Issue):**
- Changes to the risk engine or kill switch
- Changes to the ML training pipeline
- New dependencies
- Breaking API changes

---

## Reporting Bugs

Use GitHub Issues: [github.com/HACKLOVE340/HOPEFX-AI-TRADING/issues](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/issues)

Include:
1. Python version (`python --version`)
2. OS and version
3. Full error traceback
4. Minimal reproduction steps
5. What you expected vs what happened

For security vulnerabilities, do **not** open a public issue. See [SECURITY.md](SECURITY.md) for the responsible disclosure process.

---

## Requesting Features

Open a GitHub Discussion or Issue with the label `enhancement`.

Describe:
- The problem you're trying to solve
- Your proposed solution
- Any alternatives you considered
- Whether you're willing to implement it

---

## Community Standards

All community spaces follow the [Code of Conduct](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/blob/main/CODE_OF_CONDUCT.md).

Key points:
- Be respectful and constructive
- No financial advice — share strategies as educational content only
- No spam or self-promotion without context
- No sharing of real API keys or credentials
- Paper trading signals only in community channels — never real account signals

---

## Getting Help

**Before asking:**
1. Check [FAQ.md](FAQ.md)
2. Check [DEBUGGING.md](DEBUGGING.md)
3. Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
4. Search existing GitHub Issues and Discussions

**When asking:**
- Include your Python version, OS, and error message
- Share the relevant section of your `.env` (redact all secrets)
- Describe what you tried already

---

## Sharing Your Work

We encourage sharing:
- Backtest results (with methodology — walk-forward, OOS period, N trades)
- Custom strategies (as code contributions or Discussions posts)
- Deployment setups (VPS configs, Docker Compose variants)
- Performance reports (paper trading only until you're comfortable)

When sharing backtest results, always include:
- OOS period (not in-sample)
- Number of trades (N)
- Sharpe standard error (SE = 1/sqrt(N))
- Whether walk-forward validation was used

---

## Sponsoring

HOPEFX is open-source under AGPL-3.0. If you use it commercially, a commercial license is required — see [LICENSE-COMMERCIAL.md](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/blob/main/LICENSE-COMMERCIAL.md).

To support development:
- Star the repository on GitHub
- Contribute code or documentation
- Report bugs with detailed reproduction steps
- Share the project with other traders and developers

---

*Last updated: 2026-04-01*
