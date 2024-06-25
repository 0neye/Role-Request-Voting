import asyncio
import discord
import os
import dotenv
import logging
import matplotlib.pyplot as plt
import io
from discord.ext import tasks
from discord import Embed, Colour
from datetime import datetime, timezone
from config import (
    ACCEPTANCE_THRESHOLDS,
    CHECK_TIME,
    DEFAULT_VOTE,
    IGNORE_VOTE_WEIGHT,
    VOTE_TIME_PERIOD,
    ROLE_VOTES,
    CHANNEL_ID,
    COMMAND_WHITELISTED_ROLES,
    DEV_MODE,
    THREAD_TAGS,
    VALID_ROLES,
    LOG_FILE_NAME,
)
from app import RequestsManager
from request import RoleRequest


# SETUP AND INITIALIZATION

bot = discord.Bot()
app = RequestsManager()
app.load_state()

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(LOG_FILE_NAME)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s"))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s"))

logger.addHandler(file_handler)
logger.addHandler(console_handler)


####################################


class VoteView(discord.ui.View):
    def __init__(
        self,
        thread_owner: discord.User,
        thread_id: int,
        thread_title: str,
        end_time: int,
    ):
        """
        Initialize the VoteView class.

        Args:
            thread_owner (discord.User): The owner of the thread.
            thread_id (int): The ID of the thread (also the request ID).
            thread_title (str): The title of the thread.
            end_time (int): The end time of the vote as a timestamp.
        """

        # Called every time the bot restarts
        super().__init__(timeout=None)
        self.thread_owner: discord.User = thread_owner
        self.thread_title = thread_title
        self.thread_id = thread_id
        self.end_time = end_time

        self.check_time.start()

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success, custom_id="vote_yes")
    async def yes_button_callback(self, button, interaction):
        await self.handle_vote(interaction, "yes")
        await self._update_displayed_member_count()

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger, custom_id="vote_no")
    async def no_button_callback(self, button, interaction):
        await self.handle_vote(interaction, "no")
        await self._update_displayed_member_count()

    async def handle_vote(self, interaction: discord.Interaction, vote_type: str):
        """
        Handle a vote interaction.

        Args:
            interaction (discord.Interaction): The interaction that triggered the vote.
            vote_type (str): The type of vote ("yes" or "no").
        """

        user: discord.Member = interaction.user

        # People can't vote on their own requests
        if user.id == self.thread_owner.id and not DEV_MODE:
            await interaction.response.send_message("You can't vote on your own request!", ephemeral=True)
            return

        request = app.get_request(self.thread_id)
        vote_changed = request.has_voted(user.id)

        role_votes = self._get_user_votes(user, request)

        # Negate are 'no' votes, positive are 'yes'
        app.vote_on_request(self.thread_id, user.id,
                            role_votes * (-1 if vote_type == "no" else 1))
        if vote_changed:
            await interaction.response.send_message(
                f"You changed your vote to {vote_type.capitalize()} with {role_votes} votes.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"You voted {vote_type.capitalize()} with {role_votes} votes.",
                ephemeral=True,
            )

    def _get_user_votes(self, user: discord.Member, request: RoleRequest):
        """
        Get the number of votes a user can cast based on their roles.
        Dependent on the 'ROLE_VOTES' and 'DEFAULT_VOTE' constants in config.

        Args:
            user (discord.Member): The user whose votes are being calculated.
            request (RoleRequest): The role request being voted on.

        Returns:
            int: The number of votes the user can cast.
        """

        if request.ignore_vote_weight:
            return DEFAULT_VOTE

        res = DEFAULT_VOTE
        for role in user.roles:
            if role.name in ROLE_VOTES:
                res = max(res, ROLE_VOTES[role.name])

        return res

    async def _update_displayed_member_count(self):
        """
        Called whenever the displayed member count needs to update
        """

        thread = bot.get_channel(self.thread_id)
        request = app.get_request(self.thread_id)
        vote_message_id = request.bot_message_id
        vote_message = await thread.fetch_message(vote_message_id)

        # Edit the member count on the embed
        embed = vote_message.embeds[0]
        embed.set_field_at(
            index=2,  # the 3rd field
            name="",
            value=f"`{request.num_users}` {'member has' if request.num_users == 1 else 'members have'} voted on this request.",
            inline=False,
        )
        await vote_message.edit(embed=embed)

    @tasks.loop(seconds=CHECK_TIME)
    async def check_time(self):
        """
        Check if the voting period has ended and end the vote if it has.
        """

        print("checking...")
        if int(datetime.now(timezone.utc).timestamp()) >= self.end_time:
            await end_vote(self)


async def _finish_vote(thread: discord.Thread, request: RoleRequest):
    """
    Finish the voting process and display the results.
    Edits thread tags and original voting prompt message.
    Closes and locks thread.
    Dependent on 'THREAD_TAGS' constant in config.

    Args:
        thread (discord.Thread): The thread where the vote took place.
        request (RoleRequest): The role request being voted on.
    """

    # Edit the original bot message to show the vote results and remove the view
    logger.info("Editing vote message to show results...")
    try:
        vote_message = await thread.fetch_message(request.bot_message_id)
        yes_votes, no_votes = request.get_votes()
        outcome = "Approved" if request.result() is True else "Denied"

        total_votes = yes_votes + no_votes
        yes_percentage = (yes_votes / total_votes) * \
            100 if total_votes > 0 else 0
        no_percentage = (no_votes / total_votes) * \
            100 if total_votes > 0 else 0
        file = None

        if total_votes > 0:
            # Create a pie chart
            fig, ax = plt.subplots()
            ax.pie([yes_votes, no_votes], labels=['Yes', 'No'], colors=['green', 'red'],
                   autopct='%1.1f%%', startangle=90, textprops={'color': 'w', 'size': 'x-large'})
            ax.axis('equal')

            # Save the plot to a BytesIO object with a transparent background
            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight',
                        pad_inches=0, transparent=True)
            buf.seek(0)

            # Create a file from the BytesIO object
            file = discord.File(buf, filename="vote_pie.png")

        embed = Embed(
            title=f"Voting Results - {request.role} - **{outcome}**",
            colour=Colour.green() if outcome == "Approved" else Colour.red(),
        )
        embed.add_field(
            name=f"Yes Votes{'' if request.ignore_vote_weight else ' (weighted)'}",
            value=f"{yes_votes} ({yes_percentage:.2f}%)",
            inline=True,
        )
        embed.add_field(
            name=f"No Votes{'' if request.ignore_vote_weight else ' (weighted)'}",
            value=f"{no_votes} ({no_percentage:.2f}%)",
            inline=True,
        )

        # Add member count
        if total_votes > 0:
            embed.add_field(
                name=f"Total participating members: `{request.num_users}`",
                value="",
                inline=False,
            )

        # Add veto disclaimer
        if request.veto is not None:
            user = await bot.get_or_fetch_user(request.veto[0])
            embed.add_field(
                name="",
                value=f"*This request's outcome was overruled by {user.mention}*",
                inline=False,
            )

        # Deal with image
        if file:
            embed.set_image(url=f"attachment://{file.filename}")
            await vote_message.edit(content=None, embed=embed, view=None, file=file)
        else:
            embed.add_field(name="", value="No votes cast.", inline=False)
            await vote_message.edit(content=None, embed=embed, view=None)

        logger.info("Edited vote message.")

        # Add the tag "Approved" or "Denied" to the thread, then close it
        approved_tag = discord.utils.get(
            thread.parent.available_tags, name=THREAD_TAGS["Approved"])
        denied_tag = discord.utils.get(
            thread.parent.available_tags, name=THREAD_TAGS["Denied"])

        if outcome == "Approved" and approved_tag and approved_tag not in thread.applied_tags:
            await thread.edit(applied_tags=thread.applied_tags + [approved_tag])
        elif outcome == "Denied" and denied_tag and denied_tag not in thread.applied_tags:
            await thread.edit(applied_tags=thread.applied_tags + [denied_tag])

        await thread.edit(archived=True, locked=True)

        # Log the result
        logger.info(
            f"Vote finished for request '{request.thread_id}' - {request.role}: {outcome}. "
            f"Yes: {yes_votes} ({yes_percentage:.2f}%), No: {no_votes} ({no_percentage:.2f}%)\n{'==' * 10}\n\n"
        )

    except discord.NotFound:
        logger.error(
            f"Vote message not found for request {request.thread_id}.")
    except discord.HTTPException as e:
        logger.error(f"Failed to edit vote message: {e}")
    except Exception as e:
        logger.exception(f"Failed to edit vote message: {e}")


# Can't actually be part of the VoteView class for some reason...
async def end_vote(view: VoteView):
    """
    End the vote and handle the outcome.
    Edits user roles and calls _finish_vote().

    Args:
        view (VoteView): The VoteView instance.
    """

    view.check_time.stop()
    request: RoleRequest = app.get_request(view.thread_id)
    logger.info(f"# Ending vote with thread id '{view.thread_id}': \"{request.title}\"\n")

    # Delete the role request from the active list
    app.remove_request(view.thread_id)

    # Get the current thread
    thread = bot.get_channel(view.thread_id) or await bot.fetch_channel(view.thread_id)
    if not isinstance(thread, discord.Thread):
        logger.error("Error: Thread not found or is not a thread.")
        return

    # Do we hand out the role or not?
    give_role = request.result()
    if request.veto is not None:
        logger.info(f"Request vetoed, result is now {give_role}")

    try:
        if not give_role:
            await thread.send(f"Sorry, {view.thread_owner.mention}! Your application for {request.role} has been denied.")
            await _finish_vote(thread, request)
            return

        # Get guild and role from the discord api
        guild = (bot.get_channel(CHANNEL_ID) or await bot.fetch_guild(CHANNEL_ID)).guild
        role = discord.utils.get(guild.roles, name=request.role)

        if not role:
            logger.error(
                f"Error: Role '{request.role}' not found in the server.")
            await thread.send(f"Error: Role '{request.role}' not found in the server.")
            await _finish_vote(thread, request)
            return

        # Get the member from the user (yes it's confusing)
        member = guild.get_member(view.thread_owner.id) or await guild.fetch_member(view.thread_owner.id)

        if not member:
            logger.error(
                f"Error: Member '{view.thread_owner.mention}' not found in the server.")
            await thread.send(f"Error: Member '{view.thread_owner.mention}' not found in the server.")
            await _finish_vote(thread, request)
            return

        # Add the role to the user if possible
        logger.info(
            f"Adding role '{request.role}' to {view.thread_owner.mention}...")
        if member.id == member.guild.owner_id:
            logger.error("Error: Cannot modify roles of the server owner.")
            await thread.send(f"Error: Cannot modify roles of the server owner, {view.thread_owner.mention}.")
            await _finish_vote(thread, request)
            return
        else:
            await member.add_roles(role)
            await thread.send(
                f"Congratulations, {view.thread_owner.mention}! Your application for {request.role} has been approved."
            )
            await _finish_vote(thread, request)
            return

    except discord.Forbidden:
        logger.critical("Error: Bot does not have permission to add roles.")
        await thread.send("Error: Bot does not have permission to add roles.")
    except discord.HTTPException as e:
        logger.error(f"Failed to add role due to an error: {e}")
        await thread.send(f"Failed to add role due to an error: {e}.")
    except Exception as e:
        logger.exception(f"Failed to add role due to an error: {e}")
        await thread.send(f"Failed to add role due to an error: {e}.")

    except asyncio.exceptions.CancelledError:
        # Weird occurance, but thread.send *almost* always causes this even when it works
        logger.error("Thread.send resulted in an asyncio CancelledError.")
        await _finish_vote(thread, request)


@bot.event
async def on_ready():
    """
    Event handler for when the bot is ready.
    Updates the bot object with information loaded from the state file.
    """

    logger.info(f"Logged in as {bot.user}")
    # Load all active role requests from the saved state on restart
    for request in app.requests.values():
        request: RoleRequest
        print(request.to_dict())
        thread_owner_id = request.user_id
        thread_owner = await bot.get_or_fetch_user(thread_owner_id)
        thread_title = request.title
        thread_id = request.thread_id
        end_time = request.end_time
        bot.add_view(view=VoteView(thread_owner, thread_id,
                     thread_title, end_time), message_id=request.bot_message_id)

    logger.info("Loaded all active role requests!")


async def _init_request(thread: discord.Thread):
    """
    Creates a new RoleRequest and VoteView from the request thread.
    Dependent on 'VOTE_TIME_PERIOD' and 'VALID_ROLES' constants in config.

    Args:
        thread (discord.Thread): The request thread.
    """

    # Create an active role request for the first time
    thread_title = thread.name
    thread_id = thread.id
    end_time = int(datetime.now(timezone.utc).timestamp() + VOTE_TIME_PERIOD)
    role = None

    # Try to extract the role from the thread tags
    for tag in thread.applied_tags:
        if tag.name in VALID_ROLES:
            role = tag.name

    try:
        # Can throw ValueError if the role in the title is invalid
        # Won't throw if the role was found in the tags
        app.add_request(thread.owner_id, thread_id,
                        thread_title, end_time, role)
    except ValueError as e:
        await thread.send(f"Error when creating role request: {e}")
        logger.error(f"Error when creating role request: {e}")
        return

    # Bunch of work needed to check roles below
    request = app.get_request(thread_id)
    guild = (bot.get_channel(CHANNEL_ID) or await bot.fetch_guild(CHANNEL_ID)).guild
    owner = await bot.get_or_fetch_user(thread.owner_id)
    owner_m = guild.get_member(thread.owner_id) or await guild.fetch_member(thread.owner_id)

    # People can't apply for a role they already have
    if request.role in [role.name for role in owner_m.roles] and not DEV_MODE:
        await thread.send(f"Error: You already have the role {request.role}.")
        logger.error(
            f"{owner.mention} tried to create a request for {request.role} but they already have it.")
        app.remove_request(thread_id)
        return

    # Finally construct the view
    view = VoteView(owner, thread_id, thread_title, end_time)

    embed = discord.Embed(
        title=f"Role Application - {request.role}",
        description=f"{owner.mention} is applying for {request.role}! Do you think they meet the standards required? Take a look at their ships in-game and then vote below.",
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="Deadline",
        value=f"Voting ends <t:{end_time}:F> or <t:{end_time}:R>.",
    )
    embed.add_field(
        name="Threshold",
        value=f"**{request.threshold*100:.0f}%** 'Yes'{'' if request.ignore_vote_weight else ' (weighted)'} votes are required to approve.",
    )
    # Index 2
    embed.add_field(
        name="",
        value=f"`{request.num_users}` {'member has' if request.num_users == 1 else 'members have'} voted on this request.",
        inline=False,
    )
    if request.ignore_vote_weight:
        embed.add_field(
            name="",
            value="*Vote weighting is ignored for this role request. Use `/help` for more info.*",
            inline=False,
        )

    vote_message = await thread.send(embed=embed, view=view)
    await vote_message.pin()

    app.update_bot_message_id(thread_id, vote_message.id)

    logger.info(
        f"Created new role request for '{request.role}' in '{thread_id}' by '{owner.mention}'.")


@bot.event
async def on_thread_create(thread: discord.Thread):
    """
    Event handler for when a new thread is created.
    Calls _init_request() if the thread is in the role requests channel.

    Args:
        thread (discord.Thread): The newly created thread.
    """

    if thread.parent_id == CHANNEL_ID:
        await _init_request(thread)


async def _restricted_cmd_ctx_to_thread(ctx) -> discord.Thread:
    """
    Performs basic checks for restricted commands and returns the thread if valid.

    Args:
        ctx (discord.ext.commands.Context): The context of the command.

    Returns:
        discord.Thread | None
    """

    # Make sure they have the perms
    for role in ctx.user.roles:
        if role.name in COMMAND_WHITELISTED_ROLES or DEV_MODE:
            break
    else:
        await ctx.respond("You don't have permission to do that.", ephemeral=True)
        return

    # Get the thread
    thread = ctx.channel
    if not isinstance(thread, discord.Thread):
        await ctx.respond("This command can only be used in a thread.", ephemeral=True)
        return

    # Check if it's a valid thread in the correct forum channel
    if thread.parent.id != CHANNEL_ID:
        await ctx.respond(
            "This command can only be used in the role requests forum channel.",
            ephemeral=True,
        )
        return

    return thread


@bot.command(description="Manually create a vote in this thread. Requires moderator or Paragon roles.")
async def create_vote(ctx):
    """
    Manually creates a vote in the current thread.
    Dependent on 'COMMAND_WHITELISTED_ROLES' constant in config.

    Args:
        ctx (discord.ext.commands.Context): The context of the command.
    """

    # Get the thread
    thread = await _restricted_cmd_ctx_to_thread(ctx)
    if thread is None:
        return

    await _init_request(thread)

    await ctx.respond("Vote created.", ephemeral=True)


@bot.command(
    description="End the vote in this thread early. Requires moderator or Paragon roles.",
)
async def end_vote_early(ctx, outcome: discord.Option(str, choices=["Approve", "Deny", "Abstain"])):
    """
    End the vote in the current thread early.
    Dependent on 'COMMAND_WHITELISTED_ROLES' constant in config.

    Args:
        ctx (discord.ApplicationContext): The context of the command.
        outcome (str): The outcome of the vote ("Approve", "Deny" or "Abstain").
    """

    # Get the thread
    thread = await _restricted_cmd_ctx_to_thread(ctx)
    if thread is None:
        return

    # Get the request
    request = app.get_request(thread.id)
    if request is None:
        await ctx.respond("This thread is not a role request.", ephemeral=True)
        return

    # Stop moderator abuse
    if ctx.user.id == request.user_id and not DEV_MODE:
        await ctx.respond("You can't end your own vote.", ephemeral=True)
        return

    # Get the view
    view = next(
        (v for v in bot.persistent_views if v.thread_id == thread.id), None)
    if view is None:
        await ctx.respond("This thread is not currently being voted on.", ephemeral=True)
        return

    # End the vote
    if outcome != "Abstain":
        # If they veto
        await ctx.respond(f"Vote ended early by {ctx.user.mention} with outcome: {outcome}")

        res = True if outcome == "Approve" else False
        request.veto = (ctx.user.id, res)
    else:
        # If they don't veto
        await ctx.respond(f"Vote ended early by {ctx.user.mention}.")

    await end_vote(view)


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


@bot.command(description="Instructions for using bot, and praovides a link to source code")
async def help(ctx):
    """
    Provide help instructions and a link to the source code.
    """
    await ctx.respond(help_text)


@bot.command(description="Returns the latency of the bot in ms")
async def ping(ctx):
    latency = bot.latency
    latency_ms = latency * 1000
    await ctx.respond(f"`Ping: {latency_ms:.2f}ms`")


dotenv.load_dotenv()
TOKEN = os.getenv("Discord_Bot_Token")

bot.run(TOKEN)
