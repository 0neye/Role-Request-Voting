VOTE_TIME_PERIOD = 10 # 60 * 60 * 24 * 7  # 7 days
EXCELSIOR_VOTE = 1
ADEPT_VOTE = 2
EXPERT_VOTE = 3
PARAGON_VOTE = 4
PERCENT_ACCEPT = 0.9

# Role to vote count mapping
ROLE_VOTES = {
    "Excelsior": EXCELSIOR_VOTE,
    "Adept": ADEPT_VOTE,
    "Expert": EXPERT_VOTE,
    "Paragon": PARAGON_VOTE
}

#CHANNEL_ID = 1239797645372035124  # Forum channel ID
CHANNEL_ID = 1234633395578077285 # TODO: remove this before sending pull request and uncomment the above line
STATE_FILE_NAME = 'requests_state.json'