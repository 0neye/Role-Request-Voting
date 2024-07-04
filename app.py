import os
from request import RoleRequest
import json
from config import STATE_FILE_NAME


class RequestsManager:
    def __init__(self):
        """
        Initialize the RequestsManager class.
        """

        self.requests: dict = {}

    def add_request(
        self, user_id: int, thread_id: int, title: str, end_time: str, role: str = None
    ) -> int:
        """
        Add a new role request.

        Args:
            user_id (int): The ID of the user making the request.
            thread_id (int): The ID of the thread (also the request ID).
            title (str): The title of the request (should contain the role if 'role' is None).
            end_time (str): The end time of the request as a timestamp.
            role (str, optional): The role being requested. Defaults to None.

        Returns:
            int: The ID of the request (same as thread ID).
        """

        # Can throw ValueError if the role in the title is invalid
        request = RoleRequest(user_id, thread_id, title, end_time, role)
        # Thread ID == Request ID
        self.requests[request.thread_id] = request
        self.save_state()
        return request.thread_id

    def update_bot_message_id(self, request_id: int, bot_message_id: int):
        """
        Update the bot message ID for a request. Call this once you've sent a message.

        Args:
            request_id (int): The ID of the request.
            bot_message_id (int): The ID of the bot message.
        """

        try:
            self.requests[request_id].bot_message_id = bot_message_id
            self.save_state()
        except KeyError:
            raise ValueError("Invalid request ID.")

    def vote_on_request(self, request_id: int, user_id: int, votes: int):
        """
        Vote on a role request, or change an existing vote.

        Args:
            request_id (int): The ID of the request.
            user_id (int): The ID of the user voting.
            votes (int): The number of votes. Negative are "no" votes.
        """

        try:
            # Uses change_vote so this function can do double duty
            self.requests[request_id].vote_or_change(user_id, votes)
            self.save_state()
        except KeyError:
            raise ValueError("Invalid request ID.")
    
    def remove_vote_on_request(self, request_id: int, user_id: int):
        """
        Remove a user's vote from a role request.

        Args:
            request_id (int): The ID of the request.
            user_id (int): The ID of the user whose vote should be removed.
        """

        try:
            self.requests[request_id].remove_vote(user_id)
            self.save_state()
        except KeyError:
            raise ValueError("Invalid request ID.")

    def get_request(self, request_id: int) -> RoleRequest | None:
        """
        Get a role request by its ID.

        Args:
            request_id (int): The ID of the request.

        Returns:
            RoleRequest | None: The role request object or None if not found.
        """

        try:
            return self.requests[request_id]
        except KeyError:
            return None

    def remove_request(self, request_id: int):
        """
        Remove a role request by its ID.

        Args:
            request_id (int): The ID of the request.
        """

        try:
            del self.requests[request_id]
            self.save_state()
        except KeyError:
            raise ValueError("Invalid request ID.")

    def save_state(self):
        """
        Save the current state of 'self.requests' to a json file.
        Dependent on 'STATE_FILE_NAME' constant in config.
        """

        with open(STATE_FILE_NAME, "w") as file:
            json.dump(
                {
                    request_id: request.to_dict()
                    for request_id, request in self.requests.items()
                },
                file,
            )

    def load_state(self):
        """
        Load the state of 'self.requests' from a json file.
        Dependent on 'STATE_FILE_NAME' constant in config.
        """

        if os.path.exists(STATE_FILE_NAME):
            with open(STATE_FILE_NAME, "r") as file:
                file_content = file.read().strip()
                if not file_content:
                    self.requests = {}
                    print("File is empty or contains only whitespace. Starting Fresh.")
                    return

                self.requests = {
                    int(request_id): RoleRequest.from_dict(data)
                    for request_id, data in json.loads(file_content).items()
                }
            print("Loaded requests state from file.")
        else:
            self.requests = {}
            print("No requests state file found. Starting fresh.")
