import os
import dotenv
from groq import Groq
from config import PERCENT_ACCEPT

dotenv.load_dotenv()
API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(
    api_key=API_KEY,
)
print("Groq client loaded.")

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

        # I'm lazy and wanted to try out groq
        chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": "Based on the user message, extract the word mentioned. Either 'Excelsior', 'Adept', 'Expert', or 'Paragon'. Do NOT respond with anything else, ever.",
            },
            {
                "role": "user",
                "content": f"\"{self.title}\"\nRespond with the first matching value. If none is given respond with 'Excelsior'.",
            }
        ],
        model="llama3-8b-8192",
        temperature=0.2,
        stream=False,
        stop=None,
        timeout=2
        )
        self.role = chat_completion.choices[0].message.content.strip().capitalize()

        self.id: int = hash(self.user_id + self.end_time)
        print(f"New Request: {self.id} for {self.role}: '{self.title}'")


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
        yes_count, no_count = self.get_votes()
        return True if (yes_count / (no_count if no_count > 0 else 1)) >= PERCENT_ACCEPT else False

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "title": self.title,
            "end_time": self.end_time,
            "bot_message_id": self.bot_message_id,
            "role": self.role,
            "yes_votes": self.yes_votes,
            "no_votes": self.no_votes
        }
