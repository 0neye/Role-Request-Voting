from config import ACCEPTANCE_THRESHOLDS, IGNORE_VOTE_WEIGHT, VALID_ROLES
import re
from datetime import datetime, timezone

class RoleRequest:
    def __init__(
        self, user_id: int, thread_id: int, title: str, end_time: int, role: str = None,
    ):
        """
        Initialize a RoleRequest instance. Extracts role from title if not given.
        Dependent on 'VALID_ROLES', 'ACCEPTANCE_THRESHOLDS' and 'IGNORE_VOTE_WEIGHT' constants in config.

        Args:
            user_id (int): The ID of the user making the request.
            thread_id (int): The ID of the thread (also the request ID).
            title (str): The title of the request (should contain the role if 'role' is None).
            end_time (int): The end time of the request as a timestamp.
            role (str, optional): The role being requested. Defaults to None.
        """

        self.user_id: int = user_id  # user ID
        self.thread_id = thread_id
        self.title: str = title
        self.end_time: str = end_time
        self.bot_message_id = None
        self.role = role
        self.yes_votes: list = []  # List of (userid, vote #)
        self.no_votes: list = []  # List of (userid, vote #)
        self.feedback: list = [] # List of (userid, feedback)
        self.num_users: int = 0 # Number of users that cast a vote

        # (int, bool) = (user_id, veto); user being the one to make the veto
        self.veto: None | (int, bool) = None
        self.ignore_vote_weight = False

        self.closed = False

        # Extract role from title if not provided
        if not self.role:
            for role in VALID_ROLES:
                match = re.search(role, self.title, re.IGNORECASE)
                if match:
                    self.role = role
                    break
            else:
                raise ValueError("Invalid role.")
        
        self.threshold = ACCEPTANCE_THRESHOLDS[self.role]
        self.ignore_vote_weight = self.role in IGNORE_VOTE_WEIGHT

    @classmethod
    def from_dict(cls, data: dict):
        """
        Create a RoleRequest instance from a dictionary.

        Args:
            data (dict): A dictionary containing the request data.

        Returns:
            RoleRequest: The created RoleRequest instance.
        """

        instance = cls(
            user_id=data.get("user_id"),
            thread_id=data.get("thread_id"),
            title=data.get("title"),
            end_time=data.get("end_time"),
            role=data.get("role"),
        )
        instance.bot_message_id = data.get("bot_message_id")
        instance.yes_votes = data.get("yes_votes") or []
        instance.no_votes = data.get("no_votes") or []
        instance.feedback = data.get("feedback") or []
        instance.num_users = data.get("num_users") or 0
        instance.veto = data.get("veto")
        instance.closed = data.get("closed") or int(instance.end_time) > int(datetime.now(timezone.utc).timestamp())

        return instance

    def vote(self, user_id: int, votes: int):
        """
        Vote on the role request.

        Args:
            user_id (int): The ID of the user voting.
            votes (int): The number of votes. Negative are "no" votes.
        """

        # Also checked in 'bot.py' get_user_votes()
        if self.ignore_vote_weight:
            votes = (-1 if votes < 0 else 1)

        if votes < 0:
            self.no_votes.append((user_id, votes * -1))
        else:
            self.yes_votes.append((user_id, votes))
        
        self._update_usercount()
    
    def vote_or_change(self, user_id: int, new_votes: int):
        """
        Vote on the role request, or change an existing vote.

        Args:
            user_id (int): The ID of the user voting or changing their vote.
            new_votes (int): The new number of votes. Negative are "no" votes.
        """

        if self.has_voted(user_id):
            self.yes_votes = [vote for vote in self.yes_votes if vote[0] != user_id]
            self.no_votes = [vote for vote in self.no_votes if vote[0] != user_id]
        self.vote(user_id, new_votes)

    def remove_vote(self, user_id: int):
        """
        Remove a user's vote from the role request.

        Args:
            user_id (int): The ID of the user whose vote should be removed.
        """
        self.yes_votes = [vote for vote in self.yes_votes if vote[0] != user_id]
        self.no_votes = [vote for vote in self.no_votes if vote[0] != user_id]
        self._update_usercount()

    def submit_feedback(self, user_id: int, feedback: str):
        """
        Submit feedback for this role request.

        Args:
            user_id (int): The ID of the user submitting the feedback.
            feedback (str): The feedback text.
        """

        self.feedback.append((user_id, feedback))

    def get_votes(self):
        """
        Get the total number of yes and no votes.

        Returns:
            tuple (yes_count, no_count): A tuple containing the count of yes votes and no votes.
        """

        yes_count = sum(vote[1] for vote in self.yes_votes) or 0
        no_count = sum(vote[1] for vote in self.no_votes) or 0
        return (yes_count, no_count)
    
    def _update_usercount(self):
        self.num_users = len(self.yes_votes) + len(self.no_votes)
        return

    def has_voted(self, user_id: int):
        """
        Check if a user has already voted.

        Args:
            user_id (int): The ID of the user.

        Returns:
            bool: True if the user has voted, False otherwise.
        """
        return user_id in [vote[0] for vote in self.yes_votes + self.no_votes]

    def has_submitted_feedback(self, user_id: int):
        """
        Check if a user has submitted feedback.

        Args:
            user_id (int): The ID of the user.

        Returns:
            bool: True if the user has submitted feedback, False otherwise.
        """
        return user_id in [feedback[0] for feedback in self.feedback]

    def result(self):
        """
        Get the result of the role request.

        Returns:
            bool: True if the request is accepted, False otherwise.
        """

        if self.veto is None:
            yes_count, no_count = self.get_votes()
            total = yes_count + no_count
            return (
                True
                if (yes_count / (total if total > 0 else 1)) >= self.threshold
                else False
            )
        else:
            return self.veto[1]

    def to_dict(self):
        """
        Convert the RoleRequest instance to a dictionary.

        Returns:
            dict: A dictionary representation of the RoleRequest instance.
        """

        return {
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "title": self.title,
            "end_time": self.end_time,
            "bot_message_id": self.bot_message_id,
            "role": self.role,
            "yes_votes": self.yes_votes,
            "no_votes": self.no_votes,
            "feedback": self.feedback,
            "num_users": self.num_users,
            "veto": self.veto,
            "closed": self.closed,
        }
