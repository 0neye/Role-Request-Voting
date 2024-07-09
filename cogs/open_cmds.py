import discord
from discord.ext import commands
from bot import logger, app
from config import ACCEPTANCE_THRESHOLDS, CHANNEL_ID, IGNORE_VOTE_WEIGHT, ROLE_VOTES, VALID_ROLES

# Bunch of setup for the help command
# Create a string that lists the acceptance thresholds and the roles associated with each threshold
thresholds_str = "\n".join(
    f"{percent1 * 100}%: "  # Convert the threshold to a percentage string
    + ", ".join(
        [
            role  # List the roles
            # Iterate over the acceptance thresholds
            for role, percent2 in ACCEPTANCE_THRESHOLDS.items()
            if percent1 == percent2  # Match roles with the same threshold
        ]
    )
    # Ensure unique and sorted thresholds
    for percent1 in set(sorted(ACCEPTANCE_THRESHOLDS.values()))
)

# Create a dictionary of roles and their vote weights, including only valid roles and "Excelsior"
relevant_roles = {
    role: weight  # Map each role to its weight
    for role, weight in ROLE_VOTES.items()  # Iterate over the role votes
    # Include only valid roles or "Excelsior"
    if role in VALID_ROLES or role == "Excelsior"
}

# Create a string that lists the vote weights and the roles associated with each weight
vote_weights_str = "\n".join(
    f"{weight1}: "  # Convert the weight to a string
    + ", ".join(
        # List roles with the same weight
        [role for role, weight2 in relevant_roles.items() if weight1 == weight2]
    )
    # Ensure unique and sorted weights
    for weight1 in set(sorted(relevant_roles.values()))
)

# Create a string that lists the roles where vote weight is ignored
vote_weight_ignored_str = "\n".join(f"{role}" for role in IGNORE_VOTE_WEIGHT)

# Help command contents
help_text = f"""
# Role Voting Bot
*This bot is under active development. Please provide feedback and keep in mind that not everything is finalized.*

__Source code:__ <https://github.com/0neye/Role-Request-Voting>

## How it works:
Role Voting helps determine the outcome of an Excelsior role request using an anyonymous voting system.

When a new thread is made in the role requests forum channel, it will send a message with *Yes* and *No* buttons. Select one of these buttons to cast your vote.
After a set amount of time, the bot will show the results of the poll and automatically assign a role if enough people voted *Yes*.
### Acceptance Threshold Percentages:
{thresholds_str}
### Vote Weights:
{vote_weights_str}
### Role Requests Where Vote Weight is Ignored:
{vote_weight_ignored_str}
"""


class OpenCmds(commands.Cog):
    """Commands that can be used in any role request thread by anyone."""

    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(description="Instructions for using bot, and provides a link to source code")
    async def help(self, ctx):
        """
        Provide help instructions and a link to the source code.
        """
        await ctx.respond(help_text)

    @commands.slash_command(description="Returns the latency of the bot in ms")
    async def ping(self, ctx):
        latency = self.bot.latency
        latency_ms = latency * 1000
        await ctx.respond(f"`Ping: {latency_ms:.2f}ms`")

    @commands.slash_command(description="Votes on this request.")
    async def vote_on_request(self, ctx, vote: discord.Option(str, choices=["Yes", "No"])):
        """
        Votes on the current role request thread.
        This command can only be used in a role request thread.
        Dependent on 'CHANNEL_ID' constant in config.

        Args:
            ctx (discord.ApplicationContext): The context of the command invocation.
            vote (str): The vote to cast, either "Yes" or "No".
        """
        # Check if the command is used in a thread
        if not isinstance(ctx.channel, discord.Thread) or ctx.channel.parent_id != CHANNEL_ID:
            await ctx.respond("This command can only be used in a role request thread.", ephemeral=True)
            return

        # Check if it's an active request
        request = app.get_request(ctx.channel.id)
        if request is None:
            await ctx.respond("There is no active request in this thread.", ephemeral=True)
            return

        # Get the view and call the appropriate handle_vote function
        view = next(
            (v for v in self.bot.persistent_views if v.thread_id == ctx.channel.id), None)
        if view:
            await view.handle_vote(ctx.interaction, vote.lower())
        else:
            logger.warning(f"VoteView not found for thread {ctx.channel.id}")
            await ctx.respond("An error occurred while processing your vote.", ephemeral=True)

    @commands.slash_command(description="Cancels your vote on this request.")
    async def cancel_my_vote(self, ctx):
        """
        Cancels the user's vote on the current role request thread.
        This command can only be used in a role request thread.
        Dependent on 'CHANNEL_ID' constant in config.

        Args:
            ctx (discord.ApplicationContext): The context of the command invocation.
        """
        # Check if the command is used in a thread
        if not isinstance(ctx.channel, discord.Thread) or ctx.channel.parent_id != CHANNEL_ID:
            await ctx.respond("This command can only be used in a role request thread.", ephemeral=True)
            return

        # Check if it's an active request
        request = app.get_request(ctx.channel.id)
        if request is None:
            await ctx.respond("There is no active request in this thread.", ephemeral=True)
            return

        # Get the view and call the appropriate cancel_vote function
        view = next(
            (v for v in self.bot.persistent_views if v.thread_id == ctx.channel.id), None)
        if view:
            await view.cancel_vote(ctx.interaction)
        else:
            logger.warning(f"VoteView not found for thread {ctx.channel.id}")
            await ctx.respond("An error occurred while processing your vote.", ephemeral=True)

    @commands.slash_command(description="Submit anonymous feedback on the current role request.")
    async def submit_request_feedback(self, ctx, feedback: discord.Option(str, required=True)):
        """
        Submit feedback on the current role request.
        This command can only be used in a role request thread.
        Dependent on 'CHANNEL_ID' constant in config.

        Args:
            ctx (discord.ApplicationContext): The context of the command invocation.
            feedback (str): The feedback to submit.
        """
        # Check if the command is used in a thread
        if not isinstance(ctx.channel, discord.Thread) or ctx.channel.parent_id != CHANNEL_ID:
            await ctx.respond("This command can only be used in a role request thread.", ephemeral=True)
            return

        # Check if it's an active request
        request = app.get_request(ctx.channel.id)
        if request is None:
            await ctx.respond("There is no active request in this thread.", ephemeral=True)
            return

        # Get the view and call the appropriate submit_feedback function
        view = next(
            (v for v in self.bot.persistent_views if v.thread_id == ctx.channel.id), None)
        if view:
            await view.submit_feedback(ctx.interaction, ctx.user.id, feedback)
            await ctx.respond("Thank you for your feedback!", ephemeral=True)
        else:
            logger.warning(f"VoteView not found for thread {ctx.channel.id}")
            await ctx.respond("An error occurred while processing your vote.", ephemeral=True)


def setup(bot):
    bot.add_cog(OpenCmds(bot))
