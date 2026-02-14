"""
User Profile Management

Handles user profiles, verification, and social connections.
"""

from typing import Dict, Optional
from datetime import datetime


class UserProfile:
    """User profile data"""
    def __init__(self, user_id: str, display_name: str):
        self.user_id = user_id
        self.display_name = display_name
        self.bio = ""
        self.avatar_url = ""
        self.verification_level = "none"
        self.followers_count = 0
        self.following_count = 0
        self.created_at = datetime.utcnow()


class ProfileManager:
    """Manages user profiles and social connections"""

    def __init__(self):
        self.profiles: Dict[str, UserProfile] = {}
        self.following: Dict[str, set] = {}  # user_id -> set of following_ids

    def create_profile(self, user_id: str, display_name: str) -> UserProfile:
        """Create a new user profile"""
        profile = UserProfile(user_id, display_name)
        self.profiles[user_id] = profile
        return profile

    def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """Get user profile"""
        return self.profiles.get(user_id)

    def update_profile(self, user_id: str, **kwargs) -> bool:
        """Update user profile"""
        if user_id not in self.profiles:
            return False

        profile = self.profiles[user_id]
        for key, value in kwargs.items():
            if hasattr(profile, key):
                setattr(profile, key, value)

        return True

    def follow_user(self, follower_id: str, following_id: str) -> bool:
        """Follow another user"""
        if follower_id not in self.following:
            self.following[follower_id] = set()

        if following_id not in self.following[follower_id]:
            self.following[follower_id].add(following_id)

            # Update counts
            if follower_id in self.profiles:
                self.profiles[follower_id].following_count += 1
            if following_id in self.profiles:
                self.profiles[following_id].followers_count += 1

            return True
        return False

    def unfollow_user(self, follower_id: str, following_id: str) -> bool:
        """Unfollow a user"""
        if follower_id in self.following and following_id in self.following[follower_id]:
            self.following[follower_id].remove(following_id)

            # Update counts
            if follower_id in self.profiles:
                self.profiles[follower_id].following_count -= 1
            if following_id in self.profiles:
                self.profiles[following_id].followers_count -= 1

            return True
        return False
