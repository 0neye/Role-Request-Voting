from config import ACCEPTANCE_THRESHOLDS, IGNORE_VOTE_WEIGHT, VALID_ROLES
import re


class RoleRequest:
    def __init__(
        self, user_id: int, thread_id: int, title: str, end_time: int, role: str = None
    ):
        """
        Initialize a RoleRequest instance. Extracts role from title if not given.
        Dependent on 'VALID_ROLES' and 'IGNORE_VOTE_WEIGHT' constants in config.

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
        self.yes_votes: list = []  # List of usernames, vote #
        self.no_votes: list = []  # List of usernames, vote #

        # (int, bool) = (user_id, veto); user being the one to make the veto
        self.veto: None | (int, bool) = None
        self.ignore_vote_weight = False

        # Extract role from title if not provided
        if not self.role:
            for role in VALID_ROLES:
                match = re.search(role, self.title, re.IGNORECASE)
                if match:
                    self.role = role
                    break
            else:
                raise ValueError("Invalid role.")
        
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
            user_id=data["user_id"],
            thread_id=data["thread_id"],
            title=data["title"],
            end_time=data["end_time"],
            role = data["role"]
        )
        instance.bot_message_id = data["bot_message_id"]
        instance.yes_votes = data["yes_votes"]
        instance.no_votes = data["no_votes"]
        instance.veto = data["veto"]
        return instance

    def vote(self, user_id: int, votes: int):
        """
        Vote on the role request.

        Args:
            user_id (int): The ID of the user voting.
            votes (int): The number of votes. Negative are "no" votes.
        """

        if self.ignore_vote_weight:
            votes = (-1 if votes < 0 else 1)

        if votes < 0:
            self.no_votes.append((user_id, votes * -1))
        else:
            self.yes_votes.append((user_id, votes))

    def get_votes(self):
        """
        Get the total number of yes and no votes.

        Returns:
            tuple (yes_count, no_count): A tuple containing the count of yes votes and no votes.
        """

        yes_count = sum(vote[1] for vote in self.yes_votes)
        no_count = sum(vote[1] for vote in self.no_votes)
        return (yes_count, no_count)

    def has_voted(self, user_id: int):
        """
        Check if a user has already voted.

        Args:
            user_id (int): The ID of the user.

        Returns:
            bool: True if the user has voted, False otherwise.
        """

        return user_id in [vote[0] for vote in self.yes_votes + self.no_votes]

    def change_vote(self, user_id: int, new_votes: int):
        """
        Change an existing vote (or add a new one).

        Args:
            user_id (int): The ID of the user changing their vote.
            new_votes (int): The new number of votes. Negative are "no" votes.
        """

        if self.has_voted(user_id):
            self.yes_votes = [vote for vote in self.yes_votes if vote[0] != user_id]
            self.no_votes = [vote for vote in self.no_votes if vote[0] != user_id]
        self.vote(user_id, new_votes)

    def result(self):
        """
        Get the result of the role request. 
        Dependent on 'ACCEPTANCE_THRESHOLDS' constant in config.

        Returns:
            bool: True if the request is accepted, False otherwise.
        """

        if self.veto is None:
            yes_count, no_count = self.get_votes()
            percent_accept = ACCEPTANCE_THRESHOLDS[self.role]
            return (
                True
                if (yes_count / (no_count if no_count > 0 else 1)) >= percent_accept
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
            "veto": self.veto,
        }
