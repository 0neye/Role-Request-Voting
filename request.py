from config import PERCENT_ACCEPT, VALID_ROLES
import re

class RoleRequest:
    def __init__(self, user_id: int, thread_id: int, title: str, end_time: int):
        self.user_id: int = user_id # user ID
        self.thread_id = thread_id
        self.title: str = title
        self.end_time: str = end_time
        self.bot_message_id = None
        self.role: str = None
        self.yes_votes: list = [] # List of usernames, vote #
        self.no_votes: list = [] # List of usernames, vote #
        # (int, bool) = (user_id, veto); user being the one to make the veto
        self.veto: None | (int, bool) = None


        # Extract role from title
        for role in VALID_ROLES:
            match = re.search(role, self.title, re.IGNORECASE)
            if match:
                self.role = role
                break
        else:
            raise ValueError("Invalid role.")
        

        print(f"New Request: {self.user_id} for {self.role}: '{self.title}'")


    @classmethod
    def from_dict(cls, data):
        instance = cls(
            user_id=data["user_id"],
            thread_id=data["thread_id"],
            title=data["title"],
            end_time=data["end_time"],
        )
        instance.bot_message_id=data["bot_message_id"]
        instance.role = data["role"]
        instance.yes_votes = data["yes_votes"]
        instance.no_votes = data["no_votes"]
        instance.veto = data["veto"]
        return instance

    def vote(self, user_id: int, votes: int):
        if user_id in [vote[0] for vote in self.yes_votes + self.no_votes]:
            raise ValueError(f"You have already voted.")
        
        # Negative are no votes, positive are yes votes
        if votes < 0:
            self.no_votes.append((user_id, votes*-1))
        else:
            self.yes_votes.append((user_id, votes))

    def get_votes(self):
        yes_count = sum(vote[1] for vote in self.yes_votes)
        no_count = sum(vote[1] for vote in self.no_votes)
        return (yes_count, no_count)

    def result(self):
        if self.veto is None:
            yes_count, no_count = self.get_votes()
            return True if (yes_count / (no_count if no_count > 0 else 1)) >= PERCENT_ACCEPT else False
        else:
            return self.veto[1]

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "title": self.title,
            "end_time": self.end_time,
            "bot_message_id": self.bot_message_id,
            "role": self.role,
            "yes_votes": self.yes_votes,
            "no_votes": self.no_votes,
            "veto": self.veto
        }
