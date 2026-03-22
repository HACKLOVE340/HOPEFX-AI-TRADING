"""
Multi-User Team Management
- Team creation and management
- Permission control
- Shared strategies
"""

from dataclasses import dataclass
from typing import Dict, List
from enum import Enum
from datetime import datetime
import logging
import uuid

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
        self.members: Dict[str, TeamMember] = {}
        self.created_at = datetime.now()
        self.strategies = []
    
    def add_member(self, user_id: str, username: str, email: str, 
                  role: UserRole = UserRole.TRADER) -> TeamMember:
        """Add team member"""
        member = TeamMember(user_id, username, email, role, datetime.now())
        self.members[user_id] = member
        logger.info(f"Member added: {username} ({role.value})")
        return member
    
    def remove_member(self, user_id: str) -> bool:
        """Remove team member"""
        if user_id in self.members:
            del self.members[user_id]
            logger.info(f"Member removed: {user_id}")
            return True
        return False
    
    def change_role(self, user_id: str, new_role: UserRole) -> bool:
        """Change member role"""
        if user_id in self.members:
            self.members[user_id].role = new_role
            logger.info(f"Role changed for {user_id}: {new_role.value}")
            return True
        return False
    
    def get_member(self, user_id: str) -> TeamMember:
        """Get team member"""
        return self.members.get(user_id)
    
    def list_members(self) -> List[TeamMember]:
        """List all members"""
        return list(self.members.values())
    
    def share_strategy(self, strategy_id: str, with_users: List[str]):
        """Share strategy with team members"""
        for user_id in with_users:
            if user_id in self.members:
                logger.info(f"Strategy {strategy_id} shared with {user_id}")

class TeamManager:
    """Manage teams"""
    
    def __init__(self):
        self.teams: Dict[str, Team] = {}
    
    def create_team(self, name: str, creator_id: str) -> Team:
        """Create new team"""
        team_id = str(uuid.uuid4())
        team = Team(team_id, name, creator_id)
        self.teams[team_id] = team
        logger.info(f"Team created: {name}")
        return team
    
    def get_team(self, team_id: str) -> Team:
        """Get team"""
        return self.teams.get(team_id)
    
    def list_user_teams(self, user_id: str) -> List[Team]:
        """List teams for user"""
        return [t for t in self.teams.values() if user_id in t.members]