#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
deployment/challenge_launch.py
================================
Discord bot for the HOPEFX beta challenge program.

Usage
-----
    pip install discord.py
    python deployment/challenge_launch.py

Environment variables
---------------------
DISCORD_BOT_TOKEN        — Discord bot token (required to run the bot)
DISCORD_GUILD_ID         — Server/guild ID
DISCORD_ANNOUNCE_CHANNEL — Channel name for announcements (default: announcements)
CHALLENGE_MIN_PNL_PCT    — Pass threshold profit % (default 10.0)
CHALLENGE_MAX_DD_PCT     — Max allowed drawdown % (default 5.0)
CHALLENGE_MIN_DAYS       — Min trading days (default 4)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("challenge_bot")

# ── optional discord import ───────────────────────────────────────────────────
try:
    import discord
    from discord import app_commands
    from discord.ext import commands

    _DISCORD_AVAILABLE = True
except ImportError:
    _DISCORD_AVAILABLE = False
    discord = None  # type: ignore[assignment]
    app_commands = None  # type: ignore[assignment]
    commands = None  # type: ignore[assignment]
    logger.warning("discord.py not installed — ChallengeLauncher unavailable. pip install discord.py")


# ── config helpers ────────────────────────────────────────────────────────────


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _require(key: str) -> str:
    """Return env var value or raise RuntimeError (never sys.exit at import time)."""
    val = _env(key)
    if not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val


# ── persistence helpers ───────────────────────────────────────────────────────


def _load_json(path: Path, default: Any) -> Any:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)
    return default


def _save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str))


# ── pass criteria ─────────────────────────────────────────────────────────────


def _check_pass(
    pnl_pct: float,
    dd_pct: float,
    days: int,
    min_pnl: float = 10.0,
    max_dd: float = 5.0,
    min_days: int = 4,
) -> tuple[bool, str]:
    """Return (passed, reason_string)."""
    if pnl_pct < min_pnl:
        return False, f"P&L {pnl_pct:.2f}% < required {min_pnl:.1f}%"
    if dd_pct > max_dd:
        return False, f"Drawdown {dd_pct:.2f}% > max allowed {max_dd:.1f}%"
    if days < min_days:
        return False, f"Trading days {days} < required {min_days}"
    return True, "All criteria met"


# ── ChallengeLauncher class ───────────────────────────────────────────────────


class ChallengeLauncher:
    """
    Programmatic interface to the HOPEFX beta challenge Discord bot.

    Instantiate and call run() to start the bot, or use the individual
    helper methods for testing without a live Discord connection.
    """

    def __init__(
        self,
        bot_token: str | None = None,
        guild_id: int = 0,
        announce_channel: str = "announcements",
        min_pnl_pct: float = 10.0,
        max_dd_pct: float = 5.0,
        min_days: int = 4,
        data_dir: str | Path = "data",
    ) -> None:
        self.bot_token = bot_token or _env("DISCORD_BOT_TOKEN")
        self.guild_id = guild_id or int(_env("DISCORD_GUILD_ID", "0") or "0")
        self.announce_channel = announce_channel
        self.min_pnl_pct = min_pnl_pct
        self.max_dd_pct = max_dd_pct
        self.min_days = min_days

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.testers_file = self.data_dir / "beta_testers.json"
        self.results_file = self.data_dir / "challenge_results.json"
        self.status_file = self.data_dir / "paper_trading_status.json"

        self._bot: Any = None

    # ── public helpers (usable without Discord) ───────────────────────────────

    def check_pass(self, pnl_pct: float, dd_pct: float, days: int) -> tuple[bool, str]:
        """Evaluate whether a result meets the challenge pass criteria."""
        return _check_pass(pnl_pct, dd_pct, days, self.min_pnl_pct, self.max_dd_pct, self.min_days)

    def get_leaderboard(self, top_n: int = 10) -> list[dict]:
        """Return top-N testers sorted by best P&L, without Discord."""
        testers: dict[str, Any] = _load_json(self.testers_file, {})
        rows = []
        for uid, t in testers.items():
            if not t.get("results"):
                continue
            best = max(t["results"], key=lambda r: r["pnl_pct"])
            rows.append(
                {
                    "discord_id": uid,
                    "name": t.get("display_name", t.get("username", uid)),
                    "pnl_pct": best["pnl_pct"],
                    "dd_pct": best["drawdown_pct"],
                    "passed": t.get("passed", False),
                }
            )
        rows.sort(key=lambda r: r["pnl_pct"], reverse=True)
        return rows[:top_n]

    def register_tester(self, discord_id: str, username: str, display_name: str) -> dict:
        """Register a new beta tester (idempotent)."""
        testers: dict[str, Any] = _load_json(self.testers_file, {})
        if discord_id not in testers:
            testers[discord_id] = {
                "discord_id": discord_id,
                "username": username,
                "display_name": display_name,
                "joined_at": datetime.now(UTC).isoformat(),
                "passed": False,
                "results": [],
            }
            _save_json(self.testers_file, testers)
        return testers[discord_id]

    def submit_result(
        self,
        discord_id: str,
        username: str,
        pnl_pct: float,
        drawdown_pct: float,
        trading_days: int,
    ) -> dict:
        """Record a paper trading result and return the result entry."""
        testers: dict[str, Any] = _load_json(self.testers_file, {})
        if discord_id not in testers:
            raise ValueError(f"Tester {discord_id} not registered — call register_tester first")

        passed, reason = self.check_pass(pnl_pct, drawdown_pct, trading_days)
        entry = {
            "submitted_at": datetime.now(UTC).isoformat(),
            "pnl_pct": pnl_pct,
            "drawdown_pct": drawdown_pct,
            "trading_days": trading_days,
            "passed": passed,
            "reason": reason,
        }
        testers[discord_id]["results"].append(entry)
        if passed and not testers[discord_id]["passed"]:
            testers[discord_id]["passed"] = True
            testers[discord_id]["passed_at"] = datetime.now(UTC).isoformat()
        _save_json(self.testers_file, testers)

        all_results: list[dict] = _load_json(self.results_file, [])
        all_results.append({"discord_id": discord_id, "username": username, **entry})
        _save_json(self.results_file, all_results)
        return entry

    # ── Discord bot ───────────────────────────────────────────────────────────

    def _build_bot(self) -> Any:
        """Construct the discord.py Bot and register slash commands."""
        if not _DISCORD_AVAILABLE:
            raise RuntimeError("discord.py not installed. pip install discord.py")

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        bot = commands.Bot(command_prefix="!", intents=intents)
        tree = bot.tree
        launcher = self

        @bot.event
        async def on_ready():
            logger.info("Bot logged in as %s (ID: %s)", bot.user, bot.user.id)
            if launcher.guild_id:
                guild = discord.Object(id=launcher.guild_id)
                tree.copy_global_to(guild=guild)
                await tree.sync(guild=guild)
                logger.info("Slash commands synced to guild %d", launcher.guild_id)
            else:
                await tree.sync()
                logger.info("Slash commands synced globally (may take up to 1 hour)")

        @tree.command(name="join", description="Join the HOPEFX beta challenge program")
        async def join_cmd(interaction: discord.Interaction):
            uid = str(interaction.user.id)
            launcher.register_tester(uid, str(interaction.user), interaction.user.display_name)
            await interaction.response.send_message(
                f"Welcome to the **HOPEFX Beta Challenge**, **{interaction.user.display_name}**!\n\n"
                f"Rules: Profit >= {launcher.min_pnl_pct:.0f}% | DD <= {launcher.max_dd_pct:.0f}% | "
                f">= {launcher.min_days} trading days\n\n"
                f"Submit results with: `/result <pnl_pct> <drawdown_pct> <trading_days>`",
                ephemeral=False,
            )

        @tree.command(name="result", description="Submit your paper trading result")
        @app_commands.describe(
            pnl_pct="Your total P&L percentage (e.g. 12.5)",
            drawdown_pct="Your maximum drawdown percentage (e.g. 3.2)",
            trading_days="Number of days you traded (e.g. 10)",
        )
        async def result_cmd(
            interaction: discord.Interaction,
            pnl_pct: float,
            drawdown_pct: float,
            trading_days: int,
        ):
            uid = str(interaction.user.id)
            try:
                entry = launcher.submit_result(uid, str(interaction.user), pnl_pct, drawdown_pct, trading_days)
            except ValueError:
                await interaction.response.send_message("You're not registered yet. Use `/join` first.", ephemeral=True)
                return

            if entry["passed"]:
                testers: dict[str, Any] = _load_json(launcher.testers_file, {})
                first_pass = sum(1 for t in testers.values() if t.get("passed")) == 1
                embed = discord.Embed(
                    title="CHALLENGE PASSED!",
                    description=(
                        f"**{interaction.user.display_name}** passed!\n"
                        f"P&L: +{pnl_pct:.2f}% | DD: {drawdown_pct:.2f}% | Days: {trading_days}"
                    ),
                    color=discord.Color.gold(),
                )
                await interaction.response.send_message(embed=embed)
                if first_pass:
                    try:
                        await interaction.user.send(
                            "Congratulations! You're the FIRST to pass the HOPEFX Beta Challenge!\n"
                            "You've earned free lifetime access. The team will contact you shortly."
                        )
                    except discord.Forbidden:
                        logger.warning("Could not DM winner %s (DMs disabled)", interaction.user)
                    announce_ch = discord.utils.get(interaction.guild.text_channels, name=launcher.announce_channel)
                    if announce_ch:
                        await announce_ch.send(
                            f"FIRST PASSER: {interaction.user.mention} — "
                            f"P&L +{pnl_pct:.2f}% | DD {drawdown_pct:.2f}% | {trading_days} days"
                        )
            else:
                await interaction.response.send_message(
                    f"Result recorded: P&L {pnl_pct:+.2f}% | DD {drawdown_pct:.2f}% | Days {trading_days}\n"
                    f"Not passed: {entry['reason']}",
                    ephemeral=True,
                )

        @tree.command(name="leaderboard", description="Top 10 beta testers by P&L")
        async def leaderboard_cmd(interaction: discord.Interaction):
            rows = launcher.get_leaderboard(10)
            if not rows:
                await interaction.response.send_message("No testers registered yet. Use `/join`!", ephemeral=True)
                return
            medals = ["1.", "2.", "3."] + [f"{i}." for i in range(4, 11)]
            lines = ["**HOPEFX Beta Challenge Leaderboard**\n"]
            for i, row in enumerate(rows):
                badge = "[PASSED]" if row["passed"] else ""
                lines.append(
                    f"{medals[i]} {row['name']} — P&L: {row['pnl_pct']:+.2f}% | DD: {row['dd_pct']:.2f}% {badge}"
                )
            await interaction.response.send_message("\n".join(lines))

        @tree.command(name="status", description="Show current paper trading session status")
        async def status_cmd(interaction: discord.Interaction):
            if not launcher.status_file.exists():
                await interaction.response.send_message("No paper trading session found.", ephemeral=True)
                return
            try:
                s = json.loads(launcher.status_file.read_text())
            except Exception:
                await interaction.response.send_message("Status file unreadable.", ephemeral=True)
                return
            complete = s.get("complete", False)
            embed = discord.Embed(
                title=f"Paper Trading — {'COMPLETE' if complete else 'RUNNING'}",
                color=discord.Color.green() if complete else discord.Color.blue(),
            )
            embed.add_field(name="Balance", value=f"${s.get('current_balance', 0):,.2f}", inline=True)
            embed.add_field(name="Drawdown", value=f"{s.get('drawdown_pct', 0):.2f}%", inline=True)
            embed.add_field(name="Trades", value=str(s.get("trade_count", 0)), inline=True)
            embed.add_field(name="Elapsed Days", value=f"{s.get('elapsed_days', 0):.1f}", inline=True)
            await interaction.response.send_message(embed=embed)

        @tree.command(name="stats", description="Show challenge program statistics")
        async def stats_cmd(interaction: discord.Interaction):
            testers: dict[str, Any] = _load_json(launcher.testers_file, {})
            total = len(testers)
            passed = sum(1 for t in testers.values() if t.get("passed"))
            active = sum(1 for t in testers.values() if t.get("results"))
            embed = discord.Embed(title="HOPEFX Beta Challenge Stats", color=discord.Color.purple())
            embed.add_field(name="Registered", value=str(total), inline=True)
            embed.add_field(name="Active", value=str(active), inline=True)
            embed.add_field(name="Passed", value=str(passed), inline=True)
            embed.add_field(
                name="Pass Criteria",
                value=f"P&L >= {launcher.min_pnl_pct:.0f}% | DD <= {launcher.max_dd_pct:.0f}% | Days >= {launcher.min_days}",
                inline=False,
            )
            await interaction.response.send_message(embed=embed)

        self._bot = bot
        return bot

    def run(self, token: str | None = None) -> None:
        """Start the Discord bot. Blocks until the bot is stopped."""
        tok = token or self.bot_token
        if not tok:
            raise RuntimeError("DISCORD_BOT_TOKEN not set")
        bot = self._build_bot()
        logger.info(
            "Starting HOPEFX Challenge Bot | guild=%s | P&L>=%.0f%% DD<=%.0f%% days>=%d",
            self.guild_id or "global",
            self.min_pnl_pct,
            self.max_dd_pct,
            self.min_days,
        )
        bot.run(tok)


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        token = _require("DISCORD_BOT_TOKEN")
    except RuntimeError as e:
        logger.error("%s", e)
        sys.exit(1)

    ChallengeLauncher(
        bot_token=token,
        guild_id=int(_env("DISCORD_GUILD_ID", "0") or "0"),
        announce_channel=_env("DISCORD_ANNOUNCE_CHANNEL", "announcements"),
        min_pnl_pct=float(_env("CHALLENGE_MIN_PNL_PCT", "10.0")),
        max_dd_pct=float(_env("CHALLENGE_MAX_DD_PCT", "5.0")),
        min_days=int(_env("CHALLENGE_MIN_DAYS", "4")),
    ).run()
