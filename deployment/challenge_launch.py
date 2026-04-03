#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
deployment/challenge_launch.py
================================
Discord bot for the HOPEFX beta challenge program.

What it does
------------
1. Invites beta testers via a /join command — records them in data/beta_testers.json
2. Tracks paper trading results submitted via /result <pnl_pct> <drawdown_pct>
3. Rewards the first tester to pass FTMO-equivalent rules with free lifetime access
   (sends a DM + posts to #announcements channel)
4. /leaderboard — shows top 10 testers ranked by P&L %
5. /status — shows current paper trading session status from
   data/paper_trading_status.json (written by paper_trading_starter.py)

FTMO-equivalent pass criteria (configurable via env vars)
----------------------------------------------------------
CHALLENGE_MIN_PNL_PCT    — minimum profit % to pass (default 10.0)
CHALLENGE_MAX_DD_PCT     — maximum drawdown % allowed (default 5.0)
CHALLENGE_MIN_DAYS       — minimum trading days (default 4)

Environment variables
---------------------
DISCORD_BOT_TOKEN        — Discord bot token (required)
DISCORD_GUILD_ID         — Server/guild ID (required)
DISCORD_ANNOUNCE_CHANNEL — Channel name for announcements (default: announcements)
CHALLENGE_MIN_PNL_PCT    — Pass threshold profit % (default 10.0)
CHALLENGE_MAX_DD_PCT     — Max allowed drawdown % (default 5.0)
CHALLENGE_MIN_DAYS       — Min trading days (default 4)

Usage
-----
    pip install discord.py
    python deployment/challenge_launch.py

Invite URL (replace CLIENT_ID):
    https://discord.com/api/oauth2/authorize?client_id=CLIENT_ID&permissions=2048&scope=bot%20applications.commands
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

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
    logger.error("discord.py not installed. Run: pip install discord.py\nThen re-run this script.")
    sys.exit(1)

# ── paths ─────────────────────────────────────────────────────────────────────
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
TESTERS_FILE = DATA_DIR / "beta_testers.json"
RESULTS_FILE = DATA_DIR / "challenge_results.json"
STATUS_FILE = DATA_DIR / "paper_trading_status.json"


# ── config ────────────────────────────────────────────────────────────────────
def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _require(key: str) -> str:
    val = _env(key)
    if not val:
        logger.error("Missing required env var: %s", key)
        sys.exit(1)
    return val


BOT_TOKEN = _require("DISCORD_BOT_TOKEN")
GUILD_ID = int(_env("DISCORD_GUILD_ID", "0") or "0")
ANNOUNCE_CHANNEL = _env("DISCORD_ANNOUNCE_CHANNEL", "announcements")
MIN_PNL_PCT = float(_env("CHALLENGE_MIN_PNL_PCT", "10.0"))
MAX_DD_PCT = float(_env("CHALLENGE_MAX_DD_PCT", "5.0"))
MIN_DAYS = int(_env("CHALLENGE_MIN_DAYS", "4"))


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


def _check_pass(pnl_pct: float, dd_pct: float, days: int) -> tuple[bool, str]:
    """Return (passed, reason_string)."""
    if pnl_pct < MIN_PNL_PCT:
        return False, f"P&L {pnl_pct:.2f}% < required {MIN_PNL_PCT:.1f}%"
    if dd_pct > MAX_DD_PCT:
        return False, f"Drawdown {dd_pct:.2f}% > max allowed {MAX_DD_PCT:.1f}%"
    if days < MIN_DAYS:
        return False, f"Trading days {days} < required {MIN_DAYS}"
    return True, "All criteria met"


# ── bot setup ─────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


@bot.event
async def on_ready():
    logger.info("Bot logged in as %s (ID: %s)", bot.user, bot.user.id)
    if GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
        logger.info("Slash commands synced to guild %d", GUILD_ID)
    else:
        await tree.sync()
        logger.info("Slash commands synced globally (may take up to 1 hour)")


# ── /join ─────────────────────────────────────────────────────────────────────


@tree.command(name="join", description="Join the HOPEFX beta challenge program")
async def join_cmd(interaction: discord.Interaction):
    testers: dict[str, Any] = _load_json(TESTERS_FILE, {})
    uid = str(interaction.user.id)

    if uid in testers:
        await interaction.response.send_message(
            f"✅ You're already registered, **{interaction.user.display_name}**!\n"
            f"Joined: {testers[uid]['joined_at']}\n"
            f"Use `/result` to submit your paper trading results.",
            ephemeral=True,
        )
        return

    testers[uid] = {
        "discord_id": uid,
        "username": str(interaction.user),
        "display_name": interaction.user.display_name,
        "joined_at": datetime.now(UTC).isoformat(),
        "passed": False,
        "results": [],
    }
    _save_json(TESTERS_FILE, testers)
    logger.info("New beta tester: %s (%s)", interaction.user, uid)

    await interaction.response.send_message(
        f"🎉 Welcome to the **HOPEFX Beta Challenge**, **{interaction.user.display_name}**!\n\n"
        f"**Rules to pass (FTMO-equivalent):**\n"
        f"• Profit ≥ **{MIN_PNL_PCT:.0f}%** on paper account\n"
        f"• Max drawdown ≤ **{MAX_DD_PCT:.0f}%**\n"
        f"• Minimum **{MIN_DAYS}** trading days\n\n"
        f"**First to pass gets free lifetime access!** 🏆\n\n"
        f"Submit results with: `/result <pnl_pct> <drawdown_pct> <trading_days>`",
        ephemeral=False,
    )


# ── /result ───────────────────────────────────────────────────────────────────


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
    testers: dict[str, Any] = _load_json(TESTERS_FILE, {})
    uid = str(interaction.user.id)

    if uid not in testers:
        await interaction.response.send_message("You're not registered yet. Use `/join` first.", ephemeral=True)
        return

    passed, reason = _check_pass(pnl_pct, drawdown_pct, trading_days)

    # Record result
    result_entry = {
        "submitted_at": datetime.now(UTC).isoformat(),
        "pnl_pct": pnl_pct,
        "drawdown_pct": drawdown_pct,
        "trading_days": trading_days,
        "passed": passed,
        "reason": reason,
    }
    testers[uid]["results"].append(result_entry)
    if passed and not testers[uid]["passed"]:
        testers[uid]["passed"] = True
        testers[uid]["passed_at"] = datetime.now(UTC).isoformat()
    _save_json(TESTERS_FILE, testers)

    # Also append to challenge_results.json for audit trail
    all_results: list[dict] = _load_json(RESULTS_FILE, [])
    all_results.append(
        {
            "discord_id": uid,
            "username": str(interaction.user),
            **result_entry,
        }
    )
    _save_json(RESULTS_FILE, all_results)

    if passed:
        # Check if this is the FIRST passer
        first_pass = sum(1 for t in testers.values() if t.get("passed")) == 1

        embed = discord.Embed(
            title="🏆 CHALLENGE PASSED!",
            description=(
                f"**{interaction.user.display_name}** has passed the HOPEFX Beta Challenge!\n\n"
                f"P&L: **+{pnl_pct:.2f}%** | DD: **{drawdown_pct:.2f}%** | "
                f"Days: **{trading_days}**"
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"Submitted {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")

        await interaction.response.send_message(embed=embed)

        if first_pass:
            # DM the winner
            try:
                await interaction.user.send(
                    "🎉 **Congratulations!** You're the FIRST to pass the HOPEFX Beta Challenge!\n"
                    "You've earned **free lifetime access** to HOPEFX AI Trading.\n"
                    "The team will contact you shortly to activate your account."
                )
            except discord.Forbidden:
                logger.warning("Could not DM winner %s (DMs disabled)", interaction.user)

            # Post to announcements channel
            announce_ch = discord.utils.get(interaction.guild.text_channels, name=ANNOUNCE_CHANNEL)
            if announce_ch:
                await announce_ch.send(
                    f"🏆 **FIRST FTMO PASSER!** 🏆\n"
                    f"Congratulations to **{interaction.user.mention}** for being the FIRST "
                    f"to pass the HOPEFX Beta Challenge!\n"
                    f"They've earned **free lifetime access** to HOPEFX AI Trading! 🎉\n\n"
                    f"Results: P&L **+{pnl_pct:.2f}%** | DD **{drawdown_pct:.2f}%** | "
                    f"**{trading_days}** trading days"
                )
            logger.info(
                "FIRST PASSER: %s — P&L=%.2f%% DD=%.2f%%",
                interaction.user,
                pnl_pct,
                drawdown_pct,
            )
    else:
        await interaction.response.send_message(
            f"📊 **Result recorded** for **{interaction.user.display_name}**\n\n"
            f"P&L: {pnl_pct:+.2f}% | DD: {drawdown_pct:.2f}% | Days: {trading_days}\n\n"
            f"❌ **Not passed yet:** {reason}\n\n"
            f"Keep trading! Requirements: ≥{MIN_PNL_PCT:.0f}% P&L, "
            f"≤{MAX_DD_PCT:.0f}% DD, ≥{MIN_DAYS} days",
            ephemeral=True,
        )


# ── /leaderboard ──────────────────────────────────────────────────────────────


@tree.command(name="leaderboard", description="Top 10 beta testers by P&L")
async def leaderboard_cmd(interaction: discord.Interaction):
    testers: dict[str, Any] = _load_json(TESTERS_FILE, {})

    if not testers:
        await interaction.response.send_message(
            "No testers registered yet. Be the first — use `/join`!", ephemeral=True
        )
        return

    # Best result per tester
    rows: ClassVar[list[dict]] = []
    for uid, t in testers.items():
        if not t.get("results"):
            continue
        best = max(t["results"], key=lambda r: r["pnl_pct"])
        rows.append(
            {
                "name": t.get("display_name", t.get("username", uid)),
                "pnl_pct": best["pnl_pct"],
                "dd_pct": best["drawdown_pct"],
                "passed": t.get("passed", False),
            }
        )

    rows.sort(key=lambda r: r["pnl_pct"], reverse=True)
    top10 = rows[:10]

    lines = ["**🏆 HOPEFX Beta Challenge Leaderboard**\n"]
    medals = ["🥇", "🥈", "🥉"] + ["  "] * 7
    for i, row in enumerate(top10):
        badge = "✅" if row["passed"] else "  "
        lines.append(
            f"{medals[i]} **{i + 1}.** {row['name']} — "
            f"P&L: **{row['pnl_pct']:+.2f}%** | DD: {row['dd_pct']:.2f}% {badge}"
        )

    await interaction.response.send_message("\n".join(lines))


# ── /status ───────────────────────────────────────────────────────────────────


@tree.command(name="status", description="Show current paper trading session status")
async def status_cmd(interaction: discord.Interaction):
    if not STATUS_FILE.exists():
        await interaction.response.send_message(
            "No paper trading session found.\nStart one with: `python scripts/paper_trading_starter.py`",
            ephemeral=True,
        )
        return

    try:
        s = json.loads(STATUS_FILE.read_text())
    except Exception:
        await interaction.response.send_message("Status file unreadable.", ephemeral=True)
        return

    complete = s.get("complete", False)
    status_icon = "✅ COMPLETE" if complete else "🔄 RUNNING"
    embed = discord.Embed(
        title=f"📊 Paper Trading Status — {status_icon}",
        color=discord.Color.green() if complete else discord.Color.blue(),
    )
    embed.add_field(name="Balance", value=f"${s.get('current_balance', 0):,.2f}", inline=True)
    embed.add_field(name="Start Balance", value=f"${s.get('start_balance', 0):,.2f}", inline=True)
    embed.add_field(name="Drawdown", value=f"{s.get('drawdown_pct', 0):.2f}%", inline=True)
    embed.add_field(name="Trades", value=str(s.get("trade_count", 0)), inline=True)
    embed.add_field(name="Elapsed Days", value=f"{s.get('elapsed_days', 0):.1f}", inline=True)
    embed.add_field(name="Updated", value=s.get("updated_at", "unknown"), inline=False)
    embed.set_footer(text="HOPEFX AI Trading — Paper Mode")

    await interaction.response.send_message(embed=embed)


# ── /stats ────────────────────────────────────────────────────────────────────


@tree.command(name="stats", description="Show challenge program statistics")
async def stats_cmd(interaction: discord.Interaction):
    testers: dict[str, Any] = _load_json(TESTERS_FILE, {})
    total = len(testers)
    passed = sum(1 for t in testers.values() if t.get("passed"))
    active = sum(1 for t in testers.values() if t.get("results"))

    embed = discord.Embed(
        title="📈 HOPEFX Beta Challenge Stats",
        color=discord.Color.purple(),
    )
    embed.add_field(name="Total Registered", value=str(total), inline=True)
    embed.add_field(name="Active Testers", value=str(active), inline=True)
    embed.add_field(name="Passed", value=str(passed), inline=True)
    embed.add_field(
        name="Pass Criteria",
        value=(f"P&L ≥ {MIN_PNL_PCT:.0f}% | DD ≤ {MAX_DD_PCT:.0f}% | Days ≥ {MIN_DAYS}"),
        inline=False,
    )
    embed.set_footer(text="First passer earns free lifetime access!")
    await interaction.response.send_message(embed=embed)


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(
        "Starting HOPEFX Challenge Bot | guild=%s | pass_criteria=P&L≥%.0f%% DD≤%.0f%% days≥%d",
        GUILD_ID or "global",
        MIN_PNL_PCT,
        MAX_DD_PCT,
        MIN_DAYS,
    )
    bot.run(BOT_TOKEN)
