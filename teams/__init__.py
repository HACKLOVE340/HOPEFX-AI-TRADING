"""
Phase 25: Multi-User/Teams Module

Provides team management, role-based access control, and shared resources
for collaborative trading environments.
"""

from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import logging
import hashlib
import hmac
import secrets

logger = logging.getLogger(__name__)


class UserRole(Enum):
    """User roles in the system"""
    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    TRADER = "trader"
    ANALYST = "analyst"
    VIEWER = "viewer"


class Permission(Enum):
    """System permissions"""
    # Trading permissions
    TRADE_EXECUTE = "trade:execute"
    TRADE_VIEW = "trade:view"

    # Strategy permissions
    STRATEGY_CREATE = "strategy:create"
    STRATEGY_EDIT = "strategy:edit"
    STRATEGY_DELETE = "strategy:delete"
    STRATEGY_VIEW = "strategy:view"
    STRATEGY_ACTIVATE = "strategy:activate"

    # Portfolio permissions
    PORTFOLIO_VIEW = "portfolio:view"
    PORTFOLIO_MANAGE = "portfolio:manage"

    # User management
    USER_INVITE = "user:invite"
    USER_MANAGE = "user:manage"
    USER_REMOVE = "user:remove"

    # Team management
    TEAM_SETTINGS = "team:settings"
    TEAM_BILLING = "team:billing"

    # Analytics
    ANALYTICS_VIEW = "analytics:view"
    ANALYTICS_EXPORT = "analytics:export"

    # Risk
    RISK_VIEW = "risk:view"
    RISK_MANAGE = "risk:manage"


# Role permission mapping
ROLE_PERMISSIONS: Dict[UserRole, Set[Permission]] = {
    UserRole.OWNER: {p for p in Permission},  # All permissions
    UserRole.ADMIN: {
        Permission.TRADE_EXECUTE, Permission.TRADE_VIEW,
        Permission.STRATEGY_CREATE, Permission.STRATEGY_EDIT,
        Permission.STRATEGY_DELETE, Permission.STRATEGY_VIEW,
        Permission.STRATEGY_ACTIVATE,
        Permission.PORTFOLIO_VIEW, Permission.PORTFOLIO_MANAGE,
        Permission.USER_INVITE, Permission.USER_MANAGE,
        Permission.ANALYTICS_VIEW, Permission.ANALYTICS_EXPORT,
        Permission.RISK_VIEW, Permission.RISK_MANAGE,
    },
    UserRole.MANAGER: {
        Permission.TRADE_EXECUTE, Permission.TRADE_VIEW,
        Permission.STRATEGY_CREATE, Permission.STRATEGY_EDIT,
        Permission.STRATEGY_VIEW, Permission.STRATEGY_ACTIVATE,
        Permission.PORTFOLIO_VIEW, Permission.PORTFOLIO_MANAGE,
        Permission.USER_INVITE,
        Permission.ANALYTICS_VIEW, Permission.ANALYTICS_EXPORT,
        Permission.RISK_VIEW,
    },
    UserRole.TRADER: {
        Permission.TRADE_EXECUTE, Permission.TRADE_VIEW,
        Permission.STRATEGY_VIEW, Permission.STRATEGY_ACTIVATE,
        Permission.PORTFOLIO_VIEW,
        Permission.ANALYTICS_VIEW,
        Permission.RISK_VIEW,
    },
    UserRole.ANALYST: {
        Permission.TRADE_VIEW,
        Permission.STRATEGY_VIEW,
        Permission.PORTFOLIO_VIEW,
        Permission.ANALYTICS_VIEW, Permission.ANALYTICS_EXPORT,
        Permission.RISK_VIEW,
    },
    UserRole.VIEWER: {
        Permission.TRADE_VIEW,
        Permission.STRATEGY_VIEW,
        Permission.PORTFOLIO_VIEW,
        Permission.ANALYTICS_VIEW,
    },
}


@dataclass
class TeamMember:
    """Team member profile"""
    user_id: str
    email: str
    display_name: str
    role: UserRole
    joined_at: datetime
    last_active: Optional[datetime] = None
    custom_permissions: Set[Permission] = field(default_factory=set)
    is_active: bool = True
    profile_image: Optional[str] = None
    settings: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Team:
    """Team/organization configuration"""
    team_id: str
    name: str
    owner_id: str
    members: Dict[str, TeamMember]  # user_id -> TeamMember
    created_at: datetime
    settings: Dict[str, Any] = field(default_factory=dict)
    shared_strategies: List[str] = field(default_factory=list)
    shared_portfolios: List[str] = field(default_factory=list)
    api_keys: List[str] = field(default_factory=list)
    max_members: int = 10
    subscription_tier: str = "free"


@dataclass
class TeamInvitation:
    """Pending team invitation"""
    invitation_id: str
    team_id: str
    email: str
    role: UserRole
    invited_by: str
    created_at: datetime
    expires_at: datetime
    token: str
    accepted: bool = False


@dataclass
class ActivityLog:
    """User activity log entry"""
    log_id: str
    team_id: str
    user_id: str
    action: str
    resource_type: str
    resource_id: str
    details: Dict[str, Any]
    timestamp: datetime
    ip_address: Optional[str] = None


class TeamManager:
    """
    Team Management System

    Handles multi-user environments with role-based access control.

    Features:
    - Team creation and management
    - Role-based access control
    - User invitations
    - Shared resources (strategies, portfolios)
    - Activity logging
    - API key management
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize team manager."""
        self.config = config or {}
        self.teams: Dict[str, Team] = {}
        self.invitations: Dict[str, TeamInvitation] = {}
        self.activity_logs: List[ActivityLog] = []

        logger.info("Team Manager initialized")

    def create_team(
        self,
        name: str,
        owner_email: str,
        owner_name: str,
        owner_id: Optional[str] = None
    ) -> Team:
        """
        Create a new team.

        Args:
            name: Team name
            owner_email: Owner's email
            owner_name: Owner's display name
            owner_id: Optional owner user ID

        Returns:
            New team object
        """
        team_id = f"team_{len(self.teams) + 1}_{int(datetime.now().timestamp())}"
        owner_id = owner_id or f"user_{int(datetime.now().timestamp())}"

        # Create owner as first member
        owner = TeamMember(
            user_id=owner_id,
            email=owner_email,
            display_name=owner_name,
            role=UserRole.OWNER,
            joined_at=datetime.now(),
            last_active=datetime.now()
        )

        team = Team(
            team_id=team_id,
            name=name,
            owner_id=owner_id,
            members={owner_id: owner},
            created_at=datetime.now(),
            settings={
                'notifications_enabled': True,
                'two_factor_required': False,
                'allowed_ip_ranges': [],
            }
        )

        self.teams[team_id] = team
        self._log_activity(team_id, owner_id, 'create_team', 'team', team_id, {'name': name})

        logger.info(f"Created team: {name} (ID: {team_id})")
        return team

    def invite_member(
        self,
        team_id: str,
        email: str,
        role: UserRole,
        invited_by: str
    ) -> Optional[TeamInvitation]:
        """
        Send an invitation to join a team.

        Args:
            team_id: Team ID
            email: Invitee's email
            role: Role to assign
            invited_by: User ID of inviter

        Returns:
            Invitation object
        """
        team = self.teams.get(team_id)
        if not team:
            logger.error(f"Team not found: {team_id}")
            return None

        # Check if inviter has permission
        inviter = team.members.get(invited_by)
        if not inviter or not self.has_permission(team_id, invited_by, Permission.USER_INVITE):
            logger.error(f"User {invited_by} does not have invite permission")
            return None

        # Check team member limit
        if len(team.members) >= team.max_members:
            logger.error(f"Team {team_id} has reached member limit")
            return None

        # Create invitation
        invitation = TeamInvitation(
            invitation_id=f"inv_{int(datetime.now().timestamp())}_{secrets.token_hex(4)}",
            team_id=team_id,
            email=email,
            role=role,
            invited_by=invited_by,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=7),
            token=secrets.token_urlsafe(32)
        )

        self.invitations[invitation.invitation_id] = invitation
        self._log_activity(
            team_id, invited_by, 'invite_member', 'invitation',
            invitation.invitation_id, {'email': email, 'role': role.value}
        )

        logger.info(f"Created invitation for {email} to team {team_id}")
        return invitation

    def accept_invitation(
        self,
        invitation_token: str,
        user_id: str,
        display_name: str
    ) -> Optional[TeamMember]:
        """
        Accept a team invitation.

        Args:
            invitation_token: Invitation token
            user_id: New user's ID
            display_name: New user's display name

        Returns:
            New team member object
        """
        # Find invitation by token
        invitation = None
        for inv in self.invitations.values():
            if inv.token == invitation_token and not inv.accepted:
                invitation = inv
                break

        if not invitation:
            logger.error("Invalid or expired invitation token")
            return None

        if invitation.expires_at < datetime.now():
            logger.error("Invitation has expired")
            return None

        team = self.teams.get(invitation.team_id)
        if not team:
            logger.error(f"Team not found: {invitation.team_id}")
            return None

        # Create new member
        member = TeamMember(
            user_id=user_id,
            email=invitation.email,
            display_name=display_name,
            role=invitation.role,
            joined_at=datetime.now(),
            last_active=datetime.now()
        )

        team.members[user_id] = member
        invitation.accepted = True

        self._log_activity(
            team.team_id, user_id, 'accept_invitation', 'user',
            user_id, {'role': invitation.role.value}
        )

        logger.info(f"User {user_id} joined team {invitation.team_id}")
        return member

    def remove_member(
        self,
        team_id: str,
        user_id: str,
        removed_by: str
    ) -> bool:
        """
        Remove a member from a team.

        Args:
            team_id: Team ID
            user_id: User ID to remove
            removed_by: User ID performing the removal

        Returns:
            Success status
        """
        team = self.teams.get(team_id)
        if not team:
            return False

        # Check permissions
        if not self.has_permission(team_id, removed_by, Permission.USER_REMOVE):
            logger.error(f"User {removed_by} cannot remove members")
            return False

        # Cannot remove owner
        if user_id == team.owner_id:
            logger.error("Cannot remove team owner")
            return False

        if user_id in team.members:
            del team.members[user_id]
            self._log_activity(
                team_id, removed_by, 'remove_member', 'user',
                user_id, {}
            )
            logger.info(f"Removed user {user_id} from team {team_id}")
            return True

        return False

    def change_role(
        self,
        team_id: str,
        user_id: str,
        new_role: UserRole,
        changed_by: str
    ) -> bool:
        """
        Change a member's role.

        Args:
            team_id: Team ID
            user_id: User ID to change
            new_role: New role to assign
            changed_by: User ID performing the change

        Returns:
            Success status
        """
        team = self.teams.get(team_id)
        if not team:
            return False

        # Check permissions
        if not self.has_permission(team_id, changed_by, Permission.USER_MANAGE):
            logger.error(f"User {changed_by} cannot manage users")
            return False

        # Cannot change owner's role
        if user_id == team.owner_id:
            logger.error("Cannot change owner's role")
            return False

        member = team.members.get(user_id)
        if not member:
            return False

        old_role = member.role
        member.role = new_role

        self._log_activity(
            team_id, changed_by, 'change_role', 'user',
            user_id, {'old_role': old_role.value, 'new_role': new_role.value}
        )

        logger.info(f"Changed role for {user_id} from {old_role} to {new_role}")
        return True

    def has_permission(
        self,
        team_id: str,
        user_id: str,
        permission: Permission
    ) -> bool:
        """
        Check if a user has a specific permission.

        Args:
            team_id: Team ID
            user_id: User ID
            permission: Permission to check

        Returns:
            True if user has permission
        """
        team = self.teams.get(team_id)
        if not team:
            return False

        member = team.members.get(user_id)
        if not member or not member.is_active:
            return False

        # Check role permissions
        role_perms = ROLE_PERMISSIONS.get(member.role, set())
        if permission in role_perms:
            return True

        # Check custom permissions
        if permission in member.custom_permissions:
            return True

        return False

    def get_user_permissions(
        self,
        team_id: str,
        user_id: str
    ) -> Set[Permission]:
        """Get all permissions for a user."""
        team = self.teams.get(team_id)
        if not team:
            return set()

        member = team.members.get(user_id)
        if not member:
            return set()

        # Combine role permissions and custom permissions
        role_perms = ROLE_PERMISSIONS.get(member.role, set())
        return role_perms.union(member.custom_permissions)

    def share_strategy(
        self,
        team_id: str,
        strategy_id: str,
        shared_by: str
    ) -> bool:
        """Share a strategy with the team."""
        team = self.teams.get(team_id)
        if not team:
            return False

        if not self.has_permission(team_id, shared_by, Permission.STRATEGY_CREATE):
            return False

        if strategy_id not in team.shared_strategies:
            team.shared_strategies.append(strategy_id)
            self._log_activity(
                team_id, shared_by, 'share_strategy',
                'strategy', strategy_id, {}
            )
            logger.info(f"Strategy {strategy_id} shared with team {team_id}")
            return True

        return False

    def share_portfolio(
        self,
        team_id: str,
        portfolio_id: str,
        shared_by: str
    ) -> bool:
        """Share a portfolio with the team."""
        team = self.teams.get(team_id)
        if not team:
            return False

        if not self.has_permission(team_id, shared_by, Permission.PORTFOLIO_MANAGE):
            return False

        if portfolio_id not in team.shared_portfolios:
            team.shared_portfolios.append(portfolio_id)
            self._log_activity(
                team_id, shared_by, 'share_portfolio',
                'portfolio', portfolio_id, {}
            )
            logger.info(f"Portfolio {portfolio_id} shared with team {team_id}")
            return True

        return False

    def generate_api_key(
        self,
        team_id: str,
        generated_by: str,
        name: str = "API Key"
    ) -> Optional[Dict[str, str]]:
        """Generate an API key for the team."""
        team = self.teams.get(team_id)
        if not team:
            return None

        if not self.has_permission(team_id, generated_by, Permission.TEAM_SETTINGS):
            return None

        api_key = secrets.token_urlsafe(32)
        # Use PBKDF2-HMAC for secure API key hashing (CodeQL compliant)
        # Generate a random 32-byte salt per NIST recommendations
        salt = secrets.token_bytes(32)
        # Use PBKDF2 with SHA-256, 600000 iterations per OWASP 2023 recommendations
        api_key_hash = hashlib.pbkdf2_hmac(
            'sha256',
            api_key.encode(),
            salt,
            600000
        ).hex()
        # Store salt:hash format for later verification
        api_key_stored = f"{salt.hex()}:{api_key_hash}"

        team.api_keys.append(api_key_stored)

        self._log_activity(
            team_id, generated_by, 'generate_api_key',
            'api_key', api_key_hash[:16], {'name': name}
        )

        # Return the actual key only once
        return {
            'key': api_key,
            'key_id': api_key_hash[:16],
            'name': name,
            'created_at': datetime.now().isoformat()
        }

    def verify_api_key(self, team_id: str, api_key: str) -> bool:
        """
        Verify an API key against stored hashes.

        Args:
            team_id: Team ID
            api_key: API key to verify

        Returns:
            True if API key is valid
        """
        team = self.teams.get(team_id)
        if not team:
            return False

        for stored_key in team.api_keys:
            if ':' in stored_key:
                # New format: salt:hash (PBKDF2)
                salt_hex, stored_hash = stored_key.split(':', 1)
                salt = bytes.fromhex(salt_hex)
                computed_hash = hashlib.pbkdf2_hmac(
                    'sha256',
                    api_key.encode(),
                    salt,
                    600000
                ).hex()
                if hmac.compare_digest(computed_hash, stored_hash):
                    return True
            else:
                # Legacy format entries using plain SHA-256 are no longer accepted.
                # They are skipped here to enforce use of PBKDF2-based API keys only.
                continue

        return False

    def _log_activity(
        self,
        team_id: str,
        user_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: Dict[str, Any]
    ):
        """Log team activity."""
        log = ActivityLog(
            log_id=f"log_{len(self.activity_logs) + 1}",
            team_id=team_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            timestamp=datetime.now()
        )
        self.activity_logs.append(log)

    def get_activity_log(
        self,
        team_id: str,
        user_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get team activity log."""
        logs = [
            log for log in self.activity_logs
            if log.team_id == team_id
        ]

        if user_id:
            logs = [log for log in logs if log.user_id == user_id]

        logs = logs[-limit:]

        return [
            {
                'log_id': log.log_id,
                'user_id': log.user_id,
                'action': log.action,
                'resource_type': log.resource_type,
                'resource_id': log.resource_id,
                'details': log.details,
                'timestamp': log.timestamp.isoformat()
            }
            for log in logs
        ]

    def get_team_summary(self, team_id: str) -> Optional[Dict[str, Any]]:
        """Get team summary."""
        team = self.teams.get(team_id)
        if not team:
            return None

        return {
            'team_id': team.team_id,
            'name': team.name,
            'created_at': team.created_at.isoformat(),
            'member_count': len(team.members),
            'max_members': team.max_members,
            'subscription_tier': team.subscription_tier,
            'shared_strategies': len(team.shared_strategies),
            'shared_portfolios': len(team.shared_portfolios),
            'api_keys_count': len(team.api_keys),
            'members': [
                {
                    'user_id': m.user_id,
                    'display_name': m.display_name,
                    'role': m.role.value,
                    'is_active': m.is_active,
                    'joined_at': m.joined_at.isoformat(),
                }
                for m in team.members.values()
            ]
        }


def create_teams_router(manager: 'TeamManager'):
    """
    Create a FastAPI router for the Teams / Multi-User module.

    Args:
        manager: TeamManager instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
    from typing import Optional

    router = APIRouter(prefix="/api/teams", tags=["Teams"])

    class CreateTeamRequest(BaseModel):
        name: str
        owner_email: str
        owner_name: str
        owner_id: Optional[str] = None

    class InviteRequest(BaseModel):
        email: str
        role: str = "trader"
        invited_by: str

    class AcceptInviteRequest(BaseModel):
        invitation_token: str
        user_id: str
        display_name: str

    class ChangeRoleRequest(BaseModel):
        new_role: str
        changed_by: str

    @router.post("/")
    async def create_team(req: CreateTeamRequest):
        """Create a new team."""
        team = manager.create_team(
            name=req.name,
            owner_email=req.owner_email,
            owner_name=req.owner_name,
            owner_id=req.owner_id,
        )
        return {
            "team_id": team.team_id,
            "name": team.name,
            "created_at": team.created_at.isoformat(),
        }

    @router.get("/{team_id}")
    async def get_team(team_id: str):
        """Get a team summary."""
        summary = manager.get_team_summary(team_id)
        if summary is None:
            raise HTTPException(status_code=404, detail=f"Team {team_id} not found")
        return summary

    @router.post("/{team_id}/invite")
    async def invite_member(team_id: str, req: InviteRequest):
        """Invite a user to the team."""
        try:
            role = UserRole(req.role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid role '{req.role}'")
        invitation = manager.invite_member(
            team_id=team_id,
            email=req.email,
            role=role,
            invited_by=req.invited_by,
        )
        if invitation is None:
            raise HTTPException(status_code=400, detail="Could not create invitation")
        return {
            "invitation_id": invitation.invitation_id,
            "email": invitation.email,
            "role": invitation.role.value,
            "expires_at": invitation.expires_at.isoformat(),
            "token": invitation.token,
        }

    @router.post("/invitations/accept")
    async def accept_invitation(req: AcceptInviteRequest):
        """Accept a team invitation using the invitation token."""
        member = manager.accept_invitation(
            invitation_token=req.invitation_token,
            user_id=req.user_id,
            display_name=req.display_name,
        )
        if not member:
            raise HTTPException(status_code=400, detail="Invalid or expired invitation token")
        return {"status": "accepted", "user_id": member.user_id, "role": member.role.value}

    @router.delete("/{team_id}/members/{user_id}")
    async def remove_member(team_id: str, user_id: str, removed_by: str = "admin"):
        """Remove a member from the team."""
        success = manager.remove_member(team_id, user_id, removed_by)
        if not success:
            raise HTTPException(status_code=404, detail="Team or member not found")
        return {"status": "removed"}

    @router.put("/{team_id}/members/{user_id}/role")
    async def change_role(team_id: str, user_id: str, req: ChangeRoleRequest):
        """Change a member's role."""
        try:
            new_role = UserRole(req.new_role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid role '{req.new_role}'")
        success = manager.change_role(team_id, user_id, new_role, req.changed_by)
        if not success:
            raise HTTPException(status_code=404, detail="Team or member not found")
        return {"status": "updated", "role": new_role.value}

    @router.get("/{team_id}/members/{user_id}/permissions")
    async def get_permissions(team_id: str, user_id: str):
        """Get a member's effective permissions."""
        permissions = manager.get_user_permissions(team_id, user_id)
        if permissions is None:
            raise HTTPException(status_code=404, detail="Team or member not found")
        return {"team_id": team_id, "user_id": user_id, "permissions": list(permissions)}

    @router.get("/{team_id}/activity")
    async def get_activity(team_id: str, user_id: Optional[str] = None, limit: int = 50):
        """Get team activity log."""
        return manager.get_activity_log(team_id, user_id=user_id, limit=limit)

    return router


# Module exports
__all__ = [
    'TeamManager',
    'Team',
    'TeamMember',
    'TeamInvitation',
    'UserRole',
    'Permission',
    'ROLE_PERMISSIONS',
    'ActivityLog',
    'create_teams_router',
]
