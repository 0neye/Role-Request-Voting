import json
import os
from datetime import datetime, timezone
from typing import Optional

import discord

from config import ROLE_CATEGORIES, ROLE_HISTORY_FILE_NAME, RANK_ROLE_ORDER_INDEX, TRACKED_ROLE_NAMES


class RoleHistoryManager:
    def __init__(self, file_name: str = ROLE_HISTORY_FILE_NAME):
        """
        Initialize the role history manager.

        Args:
            file_name (str): The JSON file used for persistence.
        """

        self.file_name = file_name
        self.user_role_history: dict[int, dict] = {}

    def _timestamp(self) -> str:
        """
        Get the current UTC timestamp in ISO format.

        Returns:
            str: The current UTC timestamp.
        """

        return datetime.now(timezone.utc).isoformat()

    def _build_empty_user_record(self, user_id: int) -> dict:
        """
        Build a new empty record for a user.

        Args:
            user_id (int): The Discord user ID.

        Returns:
            dict: An initialized user record.
        """

        return {
            "user_id": user_id,
            "roles": {},
            "updated_at": self._timestamp(),
        }

    def _normalize_role_record(self, role_record: dict) -> dict:
        """
        Normalize a stored role record for forward compatibility.

        Args:
            role_record (dict): The stored role record.

        Returns:
            dict: The normalized role record.
        """

        role_name = role_record.get("role_name", "")
        category = role_record.get("category", ROLE_CATEGORIES.get(role_name, "other"))
        raw_role_id = role_record.get("role_id", 0)

        # Keep legacy or partially populated records loadable instead of failing
        try:
            normalized_role_id = int(raw_role_id or 0)
        except (TypeError, ValueError):
            normalized_role_id = 0

        return {
            "role_id": normalized_role_id,
            "role_name": role_name,
            "category": category,
            "last_seen_at": role_record.get("last_seen_at", self._timestamp()),
        }

    def save_state(self):
        """
        Save the current role history to disk.
        """

        with open(self.file_name, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "users": {
                        user_id: user_record
                        for user_id, user_record in self.user_role_history.items()
                    }
                },
                file,
                indent=4,
            )

    def load_state(self):
        """
        Load the current role history from disk.
        """

        if not os.path.exists(self.file_name):
            self.user_role_history = {}
            return

        with open(self.file_name, "r", encoding="utf-8") as file:
            file_content = file.read().strip()

        if not file_content:
            self.user_role_history = {}
            return

        data = json.loads(file_content)
        raw_users = data.get("users", data) if isinstance(data, dict) else {}

        normalized_users = {}
        for user_id, user_record in raw_users.items():
            if not isinstance(user_record, dict):
                continue

            normalized_roles = {}
            for role_id, role_record in (user_record.get("roles") or {}).items():
                if not isinstance(role_record, dict):
                    continue

                normalized_role = self._normalize_role_record(role_record)
                normalized_roles[str(normalized_role["role_id"] or role_id)] = normalized_role

            normalized_users[int(user_id)] = {
                "user_id": int(user_record.get("user_id", user_id)),
                "roles": normalized_roles,
                "updated_at": user_record.get("updated_at", self._timestamp()),
            }

        self.user_role_history = normalized_users

    def get_user_history(self, user_id: int) -> Optional[dict]:
        """
        Get stored role history for a user.

        Args:
            user_id (int): The Discord user ID.

        Returns:
            Optional[dict]: The stored user record if one exists.
        """

        return self.user_role_history.get(user_id)

    def snapshot_member_roles(
        self,
        member: discord.Member,
        additional_roles: Optional[list[discord.Role]] = None,
    ) -> dict:
        """
        Save the member's currently tracked roles as the latest known snapshot.

        Args:
            member (discord.Member): The member whose roles should be recorded.
            additional_roles (Optional[list[discord.Role]]): Extra roles to force
                into the snapshot when the cached member roles are not yet updated.

        Returns:
            dict: The updated user record.
        """

        user_record = self.user_role_history.get(member.id) or self._build_empty_user_record(member.id)
        snapshot_time = self._timestamp()
        tracked_roles = {}

        # Store the latest observed tracked-role set so restores match the
        # member's most recently known state instead of every role ever seen
        roles_to_snapshot = {role.id: role for role in member.roles}

        # Include explicitly supplied roles so post-grant snapshots do not depend
        # on the gateway cache updating before persistence runs
        for additional_role in additional_roles or []:
            roles_to_snapshot[additional_role.id] = additional_role

        for role in roles_to_snapshot.values():
            if role.name not in TRACKED_ROLE_NAMES:
                continue

            tracked_roles[str(role.id)] = {
                "role_id": role.id,
                "role_name": role.name,
                "category": ROLE_CATEGORIES.get(role.name, "other"),
                "last_seen_at": snapshot_time,
            }

        user_record["roles"] = tracked_roles
        user_record["updated_at"] = snapshot_time
        self.user_role_history[member.id] = user_record
        self.save_state()

        return user_record

    def _resolve_stored_role(self, guild: discord.Guild, role_record: dict) -> Optional[discord.Role]:
        """
        Resolve a stored role record back to a live Discord role.

        Args:
            guild (discord.Guild): The guild to search in.
            role_record (dict): The stored role record.

        Returns:
            Optional[discord.Role]: The resolved Discord role if it still exists.
        """

        role_id = role_record.get("role_id")
        role_name = role_record.get("role_name")

        if role_id:
            resolved_role = guild.get_role(int(role_id))
            if resolved_role is not None:
                return resolved_role

        if role_name:
            return discord.utils.get(guild.roles, name=role_name)

        return None

    def _get_effective_category(self, role_record: dict, resolved_role: Optional[discord.Role]) -> str:
        """
        Get the category that should be used for restore decisions.

        Args:
            role_record (dict): The stored role record.
            resolved_role (Optional[discord.Role]): The resolved Discord role if it exists.

        Returns:
            str: The role category used for restore logic.
        """

        if resolved_role is not None:
            return ROLE_CATEGORIES.get(
                resolved_role.name,
                role_record.get("category") or "other",
            )

        return (
            role_record.get("category")
            or ROLE_CATEGORIES.get(role_record.get("role_name", ""), "other")
        )

    def _get_rank_sort_key(self, role_record: dict, resolved_role: Optional[discord.Role]) -> tuple[int, int, int]:
        """
        Build a sort key for choosing the highest rank role.

        Args:
            role_record (dict): The stored role record.
            resolved_role (Optional[discord.Role]): The resolved Discord role if it exists.

        Returns:
            tuple[int, int, int]: A key where larger values mean higher priority.
        """

        role_name = role_record.get("role_name", "")
        fallback_rank_index = RANK_ROLE_ORDER_INDEX.get(role_name, len(RANK_ROLE_ORDER_INDEX))
        fallback_score = -fallback_rank_index

        if resolved_role is not None:
            return (1, resolved_role.position, fallback_score)

        return (0, 0, fallback_score)

    def get_restore_roles(self, member: discord.Member) -> tuple[Optional[discord.Role], list[discord.Role], list[str]]:
        """
        Resolve the stored roles that should be restored for a member.

        Args:
            member (discord.Member): The returning guild member.

        Returns:
            tuple[Optional[discord.Role], list[discord.Role], list[str]]:
                The highest rank role, additional roles, and skipped-role messages.
        """

        user_record = self.get_user_history(member.id)
        if user_record is None:
            return None, [], []

        rank_candidates: list[tuple[dict, Optional[discord.Role]]] = []
        additional_roles: dict[int, discord.Role] = {}
        skipped_roles: list[str] = []

        for role_record in user_record.get("roles", {}).values():
            resolved_role = self._resolve_stored_role(member.guild, role_record)
            effective_category = self._get_effective_category(role_record, resolved_role)
            role_name = role_record.get("role_name", f"#{role_record.get('role_id', 'unknown')}")

            if effective_category not in {"rank", "additional"}:
                continue

            if resolved_role is None:
                skipped_roles.append(f"Stored role '{role_name}' no longer exists")
                continue

            if resolved_role.name not in TRACKED_ROLE_NAMES:
                skipped_roles.append(f"Role '{resolved_role.name}' is no longer configured for restore")
                continue

            if effective_category == "rank":
                rank_candidates.append((role_record, resolved_role))
                continue

            additional_roles[resolved_role.id] = resolved_role

        highest_rank_role = None
        if rank_candidates:
            highest_rank_role = max(
                rank_candidates,
                key=lambda candidate: self._get_rank_sort_key(candidate[0], candidate[1]),
            )[1]

        additional_role_list = sorted(
            additional_roles.values(),
            key=lambda role: role.position,
            reverse=True,
        )

        return highest_rank_role, additional_role_list, skipped_roles
