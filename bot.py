import asyncio
import discord
import os
import dotenv
from discord.ext import tasks
from discord import Embed, Colour
from datetime import datetime, timezone
from config import (
    CHECK_TIME,
    DEFAULT_VOTE,
    VOTE_TIME_PERIOD,
    ROLE_VOTES,
    CHANNEL_ID,
    COMMAND_WHITELISTED_ROLES,
    DEV_MODE,
    THREAD_TAGS,
    VALID_ROLES,
)
from app import RequestsManager
from request import RoleRequest

bot = discord.Bot()
app = RequestsManager()
app.load_state()


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

    @discord.ui.button(
        label="Yes", style=discord.ButtonStyle.success, custom_id="vote_yes"
    )
    async def yes_button_callback(self, button, interaction):
        await self.handle_vote(interaction, "yes")

    @discord.ui.button(
        label="No", style=discord.ButtonStyle.danger, custom_id="vote_no"
    )
    async def no_button_callback(self, button, interaction):
        await self.handle_vote(interaction, "no")

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
            await interaction.response.send_message(
                "You can't vote on your own request!", ephemeral=True
            )
            return

        vote_changed = app.get_request(self.thread_id).has_voted(user.id)

        role_votes = self.get_user_votes(user)

        # Negate are 'no' votes, positive are 'yes'
        app.vote_on_request(
            self.thread_id, user.id, role_votes * (-1 if vote_type == "no" else 1)
        )
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

    def get_user_votes(self, user: discord.Member):
        """
        Get the number of votes a user can cast based on their roles.
        Dependent on the 'ROLE_VOTES' and 'DEFAULT_VOTE' constants in config.

        Args:
            user (discord.Member): The user whose votes are being calculated.

        Returns:
            int: The number of votes the user can cast.
        """

        res = DEFAULT_VOTE
        for role in user.roles:
            if role.name in ROLE_VOTES:
                res = max(res, ROLE_VOTES[role.name])

        return res

    @tasks.loop(seconds=CHECK_TIME)
    async def check_time(self):
        """
        Check if the voting period has ended and end the vote if it has.
        """

        print("checking...")
        if int(datetime.now(timezone.utc).timestamp()) >= self.end_time:
            self.check_time.cancel()
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
    print("Editing vote message to show results...")
    try:
        vote_message = await thread.fetch_message(request.bot_message_id)
        yes_votes, no_votes = request.get_votes()
        outcome = "Approved" if request.result() is True else "Denied"

        total_votes = yes_votes + no_votes
        yes_percentage = (yes_votes / total_votes) * 100 if total_votes > 0 else 0
        no_percentage = (no_votes / total_votes) * 100 if total_votes > 0 else 0

        if total_votes == 0:
            vote_bar = "No votes cast."
        else:
            GREEN = "\u001b[32m"
            RED = "\u001b[31m"
            RESET = "\u001b[0m"
            yes_bars = round((yes_votes / total_votes) * 50)
            no_bars = round((no_votes / total_votes) * 50)
            vote_bar = (
                f"```ansi\n{GREEN}{'|' * yes_bars}{RESET}{RED}{'|' * no_bars}{RESET}```"
            )

        embed = Embed(
            title=f"Voting Results - {request.role} - **{outcome}**",
            colour=Colour.green() if outcome == "Approved" else Colour.red(),
        )
        embed.add_field(
            name="Yes Votes", value=f"{yes_votes} ({yes_percentage:.2f}%)", inline=True
        )
        embed.add_field(
            name="No Votes", value=f"{no_votes} ({no_percentage:.2f}%)", inline=True
        )
        embed.add_field(name="", value=vote_bar, inline=False)

        # Add veto disclaimer
        if request.veto is not None:
            user = await bot.get_or_fetch_user(request.veto[0])
            embed.add_field(
                name="",
                value=f"*This request's outcome was overruled by {user.mention}*",
                inline=False,
            )

        await vote_message.edit(content=None, embed=embed, view=None)

        # Add the tag "Approved" or "Denied" to the thread, then close it.
        approved_tag = discord.utils.get(
            thread.parent.available_tags, name=THREAD_TAGS["Approved"]
        )
        denied_tag = discord.utils.get(
            thread.parent.available_tags, name=THREAD_TAGS["Denied"]
        )

        if outcome == "Approved" and approved_tag:
            await thread.edit(applied_tags=thread.applied_tags + [approved_tag])
        elif outcome == "Denied" and denied_tag:
            await thread.edit(applied_tags=thread.applied_tags + [denied_tag])

        await thread.edit(archived=True, locked=True)

    except discord.NotFound:
        print("Vote message not found.")
    except discord.HTTPException as e:
        print(f"Failed to edit vote message: {e}")

    print("Voting has ended.")


# Can't actually be part of the VoteView class for some reason...
async def end_vote(view: VoteView):
    """
    End the vote and handle the outcome.
    Edits user roles and calls _finish_vote().

    Args:
        view (VoteView): The VoteView instance.
    """

    print("Ending vote...")
    view.check_time.stop()
    request: RoleRequest = app.get_request(view.thread_id)

    # Delete the role request from the active list
    print("Deleting record...")
    app.remove_request(view.thread_id)

    # Get the current thread
    thread = bot.get_channel(view.thread_id)
    if not isinstance(thread, discord.Thread):
        print("Error: Thread not found or is not a thread.")
        return

    # Do we hand out the role or not?
    give_role = request.result()
    print(f"Result: {give_role} - {request.get_votes()}")
    if request.veto is not None:
        print(f"Request vetoed, result is now {give_role}")

    try:
        if not give_role:
            await thread.send(
                f"Sorry, {view.thread_owner.mention}! Your application for {request.role} has been denied."
            )
            await _finish_vote(thread, request)
            return

        # Get guild and role from the discord api
        guild = bot.get_channel(CHANNEL_ID).guild
        role = discord.utils.get(guild.roles, name=request.role)
        print(thread.name, guild.name, role)

        if not role:
            await thread.send(f"Error: Role '{request.role}' not found in the server.")
            await _finish_vote(thread, request)
            return

        # Get the member from the user (yes it's confusing)
        member = guild.get_member(view.thread_owner.id) or await guild.fetch_member(
            view.thread_owner.id
        )
        print(member)

        if not member:
            await thread.send(
                f"Error: Member '{view.thread_owner.mention}' not found in the server."
            )
            await _finish_vote(thread, request)
            return

        # Add the role to the user if possible
        print("Adding role...")
        if member.id == member.guild.owner_id:
            print("Cannot modify roles of the server owner.")
            await thread.send(
                f"Error: Cannot modify roles of the server owner, {view.thread_owner.mention}."
            )
            await _finish_vote(thread, request)
            return
        else:
            await member.add_roles(role)
            print("Role added successfully.")
            await thread.send(
                f"Congratulations, {view.thread_owner.mention}! Your application for {request.role} has been approved."
            )
            await _finish_vote(thread, request)
            return

    except discord.Forbidden:
        print("Bot does not have permission to add roles.")
        print("Bot does not have permission to add roles.")
        await thread.send(
            f"Error: Bot does not have permission to add roles, {view.thread_owner.mention}."
        )
    except discord.HTTPException as e:
        print(f"Failed to add role: {e}")
        await thread.send(
            f"Failed to add role due to an error: {e}, {view.thread_owner.mention}."
        )

    except asyncio.exceptions.CancelledError:
        # Weird occurance, but thread.send *almost* always causes this even when it works
        await _finish_vote(thread, request)


@bot.event
async def on_ready():
    """
    Event handler for when the bot is ready.
    Updates the bot object with information loaded from the state file.
    """

    print(f"Logged in as {bot.user}")
    # Load all active role requests from the saved state on restart
    for request in app.requests.values():
        print(app.requests)
        thread_owner_id = request.user_id
        thread_owner = await bot.get_or_fetch_user(thread_owner_id)
        thread_title = request.title
        thread_id = request.thread_id
        end_time = request.end_time
        bot.add_view(VoteView(thread_owner, thread_id, thread_title, end_time))


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
        app.add_request(thread.owner_id, thread_id, thread_title, end_time, role)
    except ValueError as e:
        print(e)
        await thread.send(f"Error: {e}")
        return

    # Bunch of work needed to check roles below
    request = app.get_request(thread_id)
    guild = bot.get_channel(CHANNEL_ID).guild
    owner = await bot.get_or_fetch_user(thread.owner_id)
    owner_m = guild.get_member(thread.owner_id) or await guild.fetch_member(
        thread.owner_id
    )

    # People can't apply for a role they already have
    if request.role in [role.name for role in owner_m.roles] and not DEV_MODE:
        await thread.send(f"Error: You already have the role {request.role}.")
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

    vote_message = await thread.send(embed=embed, view=view)
    await vote_message.pin()

    app.update_bot_message_id(thread_id, vote_message.id)

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
    if thread.parent_id != CHANNEL_ID:
        await ctx.respond(
            "This command can only be used in the role requests forum channel.",
            ephemeral=True,
        )
        return
    
    return thread

@bot.command(
    description="Manually create a vote in this thread. Requires moderator or Paragon roles."
)
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

@bot.command(
    description="End the vote in this thread early. Requires moderator or Paragon roles.",
)
async def end_vote_early(
    ctx, outcome: discord.Option(str, choices=["Approve", "Deny"])
):
    """
    End the vote in the current thread early.
    Dependent on 'COMMAND_WHITELISTED_ROLES' constant in config.

    Args:
        ctx (discord.ApplicationContext): The context of the command.
        outcome (str): The outcome of the vote ("Approve" or "Deny").
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
    view = next((v for v in bot.persistent_views if v.thread_id == thread.id), None)
    if view is None:
        await ctx.respond(
            "This thread is not currently being voted on.", ephemeral=True
        )
        return

    await ctx.respond(f"Vote ended by {ctx.user.mention} with outcome: {outcome}")

    res = True if outcome == "Approve" else False
    request.veto = (ctx.user.id, res)
    await end_vote(view)


# Help command contents
help_text = """

__Source code:__ <https://github.com/0neye/Role-Request-Voting>

Role Voting helps determine the outcome of an Excelsior role request using an anyonymous voting system.

When a new thread is made in the role requests forum channel, it will send a message with *Yes* and *No* buttons. Select one of these buttons to cast your vote.
After a set amount of time, the bot will show the results of the poll and automatically assign a role if enough people voted *Yes*.
"""

@bot.command(
    description="Instructions for using bot, and provides a link to source code"
)
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
