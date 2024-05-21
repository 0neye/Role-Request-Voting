VOTE_TIME_PERIOD = 60 # * 60 * 60 * 24 * 7  # 7 days in seconds
DEFAULT_VOTE = 1
ADEPT_VOTE = 2
EXPERT_VOTE = 3
PARAGON_VOTE = 4

PERCENT_ACCEPT = 0.9
CHECK_TIME = 60 # in seconds

# Role to vote count mapping
ROLE_VOTES = {
    "Excelsior": DEFAULT_VOTE,
    "Adept": ADEPT_VOTE,
    "Expert": EXPERT_VOTE,
    "Paragon": PARAGON_VOTE
}

# Roles that can veto a request/end it early
VETOER_ROLES = [
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

CHANNEL_ID = 1240462346808463362  # Forum channel ID
STATE_FILE_NAME = 'requests_state.json'
DEV_MODE = True # for ease of testing, turns off many checks