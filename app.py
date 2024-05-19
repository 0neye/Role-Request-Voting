import os
from request import RoleRequest
import json
from config import STATE_FILE_NAME

class RequestsManager:
    def __init__(self):
        self.requests: dict = {}

    def add_request(self, user_id: int, thread_id: int, title: str, end_time: str, role: str = None) -> int:
        # Can throw ValueError if the role is invalid
        request = RoleRequest(user_id, thread_id, title, end_time, role)
        # Thread ID == Request ID
        self.requests[request.thread_id] = request
        self.save_state()
        return request.thread_id
    
    def update_bot_message_id(self, request_id: int, bot_message_id: int):
        try:
            self.requests[request_id].bot_message_id = bot_message_id
            self.save_state()
        except KeyError:
            raise ValueError("Invalid request ID.")
    
    def vote_on_request(self, request_id: int, user_id: int, votes: int):
        try:
            # Uses change_vote so this function can do double duty
            self.requests[request_id].change_vote(user_id, votes)
            self.save_state()
        except KeyError:
            raise ValueError("Invalid request ID.")
    
    def get_request(self, request_id: int) -> RoleRequest:
        try:
            return self.requests[request_id]
        except KeyError:
            raise ValueError("Invalid request ID.")

    def remove_request(self, request_id: int):
        try:
            del self.requests[request_id]
            self.save_state()
        except KeyError:
            raise ValueError("Invalid request ID.")

    def save_state(self):
        with open(STATE_FILE_NAME, 'w') as file:
            json.dump({request_id: request.to_dict() for request_id, request in self.requests.items()}, file)

    def load_state(self):
        if os.path.exists(STATE_FILE_NAME):
            with open(STATE_FILE_NAME, 'r') as file:
                file_content = file.read().strip()
                if not file_content:
                    self.requests = {}
                    print("File is empty or contains only whitespace. Starting Fresh.")
                    return
                
                self.requests = {int(request_id): RoleRequest.from_dict(data) for request_id, data in json.loads(file_content).items()}
            print("Loaded requests state from file.")
        else:
            self.requests = {}
            print("No requests state file found. Starting fresh.")