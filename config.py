DEFAULT_VOTE = 1

# Role to vote count mapping
ROLE_VOTES = {
    "Excelsior": DEFAULT_VOTE,
    "Adept": 2,
    "Expert": 3,
    "Paragon": 4
}

# Roles that can use restricted commands
COMMAND_WHITELISTED_ROLES = [
    "Custodian (admin)",
    "Sentinel (mod)",
    "Paragon"
]

# Roles to be voted on
VALID_ROLES = [
    "Adept",
    "Expert",
    "Paragon",
    "Artisan",
    "Visionary"
]

# Thread tags (incase you have different names for your tags)
THREAD_TAGS = {
    "Approved": "Approved",
    "Denied": "Denied"
}


PERCENT_ACCEPT = 0.9 # % required to approve a request
VOTE_TIME_PERIOD = 60 # * 60 * 60 * 24 * 7  # 7 days in seconds
CHECK_TIME = 50 # how often you want to check if the voting period has ended; in seconds

CHANNEL_ID = 1234633395578077285  # Forum channel ID # TODO: Revert back to 0
STATE_FILE_NAME = 'requests_state.json'
DEV_MODE = True # for ease of testing, turns off many checks #TODO: Revert to False before submitting merge