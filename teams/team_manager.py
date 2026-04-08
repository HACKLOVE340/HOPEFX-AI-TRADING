# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Multi-User Team Management
- Team creation and management
- Permission control
- Shared strategies
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum

logger = logging.getLogger(__name__)


class UserRole(Enum):
    """User roles"""

    ADMIN = "admin"
    MANAGER = "manager"
    TRADER = "trader"
    VIEWER = "viewer"


@dataclass
class TeamMember:
    """Team member"""

    user_id: str
    username: str
    email: str
    role: UserRole
    joined_at: datetime


class Team:
    """Trading team"""

    def __init__(self, team_id: str, name: str, creator_id: str):
        self.team_id = team_id
        self.name = name
        self.creator_id = creator_id
        self.members: dict[str, TeamMember] = {}
        self.created_at = datetime.now(UTC)
        self.strategies = []

    def add_member(self, user_id: str, username: str, email: str, role: UserRole = UserRole.TRADER) -> TeamMember:
        """Add team member"""
        member = TeamMember(user_id, username, email, role, datetime.now(UTC))
        self.members[user_id] = member
        logger.info("Member added: %s (%s)", username, role.value)

        return member

    def remove_member(self, user_id: str) -> bool:
        """Remove team member"""
        if user_id in self.members:
            del self.members[user_id]
            logger.info("Member removed: %s", user_id)

            return True
        return False

    def change_role(self, user_id: str, new_role: UserRole) -> bool:
        """Change member role"""
        if user_id in self.members:
            self.members[user_id].role = new_role
            logger.info("Role changed for %s: %s", user_id, new_role.value)

            return True
        return False

    def get_member(self, user_id: str) -> TeamMember:
        """Get team member"""
        return self.members.get(user_id)

    def list_members(self) -> list[TeamMember]:
        """List all members"""
        return list(self.members.values())

    def share_strategy(self, strategy_id: str, with_users: list[str]):
        """Share strategy with team members"""
        for user_id in with_users:
            if user_id in self.members:
                logger.info("Strategy %s shared with %s", strategy_id, user_id)


class TeamManager:
    """Manage teams"""

    def __init__(self):
        self.teams: dict[str, Team] = {}

    def create_team(self, name: str, creator_id: str) -> Team:
        """Create new team"""
        team_id = str(uuid.uuid4())
        team = Team(team_id, name, creator_id)
        self.teams[team_id] = team
        logger.info("Team created: %s", name)

        return team

    def get_team(self, team_id: str) -> Team:
        """Get team"""
        return self.teams.get(team_id)

    def list_user_teams(self, user_id: str) -> list[Team]:
        """List teams for user"""
        return [t for t in self.teams.values() if user_id in t.members]
