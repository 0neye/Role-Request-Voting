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
    CHECK_TIME,
    DEFAULT_VOTE,
    PROMPT_AFTER_FIRST_FEEDBACK,
    PROMPT_NO_VOTERS_FOR_FEEDBACK,
    PROMPT_YES_VOTERS_FOR_FEEDBACK,
    VOTE_TIME_PERIOD,
    ROLE_VOTES,
    CHANNEL_ID,
    DEV_MODE,
    THREAD_TAGS,
    VALID_ROLES,
    LOG_FILE_NAME,
    CLOSE_POST,
)
from app import RequestsManager
from request import RoleRequest

# SETUP AND INITIALIZATION

bot = discord.Bot()
app = RequestsManager()
app.load_state()

# Configure logging


def setup_logger():
    logger = logging.getLogger('bot_logger')
    if not logger.handlers:
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

    return logger


logger = setup_logger()


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

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger, custom_id="vote_no")
    async def no_button_callback(self, button, interaction):
        await self.handle_vote(interaction, "no")

    @discord.ui.button(label="Cancel My Vote", style=discord.ButtonStyle.gray, custom_id="cancel_vote")
    async def cancel_button_callback(self, button, interaction):
        await self.cancel_vote(interaction)

    async def handle_vote(self, interaction: discord.Interaction, vote_type: str):
        """
        Handle a vote interaction.
        Dependant on the 'PROMPT_NO_VOTERS_FOR_FEEDBACK', 'PROMPT_YES_VOTERS_FOR_FEEDBACK', 
        and 'PROMPT_AFTER_FIRST_FEEDBACK' constants in config.py

        Args:
            interaction (discord.Interaction): The interaction that triggered the vote.
            vote_type (str): The type of vote ("yes" or "no").
        """

        user: discord.Member = interaction.user

        # People can't vote on their own requests
        if user.id == self.thread_owner.id and not DEV_MODE:
            await interaction.response.send_message("You can't vote on your own request!", ephemeral=True)
            return

        try:
            request = app.get_request(self.thread_id)
            vote_changed = request.has_voted(user.id)

            # Handle feedback prompt modal
            request_has_feedback = len(request.feedback) > 0
            user_submitted_feedback = request.has_submitted_feedback(user.id)
            feedback = ""

            # Figure out when to send the modal
            if ((vote_type == "no" and PROMPT_NO_VOTERS_FOR_FEEDBACK)
                    or (vote_type == "yes" and PROMPT_YES_VOTERS_FOR_FEEDBACK)) \
                    and (not request_has_feedback or PROMPT_AFTER_FIRST_FEEDBACK) \
                    and not user_submitted_feedback:

                # Create and show the modal
                modal = VoteModal(vote_type)
                await interaction.response.send_modal(modal)

                # Wait for the modal to be submitted
                try:
                    await modal.wait()
                except asyncio.TimeoutError:
                    return

                feedback = modal.feedback.value

            role_votes = self._get_user_votes(user, request)

            # Negate are 'no' votes, positive are 'yes'
            app.vote_on_request(self.thread_id,
                                user.id, role_votes * (-1 if vote_type == "no" else 1))
            await self._update_displayed_member_count()

            response_message = f"You {'changed your vote to' if vote_changed else 'voted'} {vote_type.capitalize()} with {role_votes} votes."

            if feedback != "":
                await self.submit_feedback(interaction, user.id, feedback)
                response_message += " Your feedback has been recorded and sent."

            await interaction.respond(response_message, ephemeral=True)

        except Exception as e:
            logger.error(
                f"Unexpected error handling vote for user {user.id} in thread {self.thread_id}: {str(e)}")
            await interaction.respond("An unexpected error occurred.", ephemeral=True)

    async def cancel_vote(self, interaction: discord.Interaction):
        """
        Cancels the users vote.

        Args:
            interaction (discord.Interaction): The interaction that triggered the cancel.
        """

        thread_id = self.thread_id
        user_id = interaction.user.id

        try:
            # Get the request
            request = app.get_request(thread_id)

            # Make sure they've voted
            if not request.has_voted(user_id):
                await interaction.respond("You haven't voted on this request yet.", ephemeral=True)
                return

            # Remove the vote
            app.remove_vote_on_request(thread_id, user_id)
            await self._update_displayed_member_count()

            # Respond
            await interaction.respond("Your vote has been cancelled.", ephemeral=True)

        except Exception as e:
            logger.error(
                f"Unexpected error cancelling vote for user {user_id} in thread {thread_id}: {str(e)}")
            await interaction.respond("An unexpected error occurred.", ephemeral=True)

    async def submit_feedback(self, interaction: discord.Interaction, user_id: int, feedback: str):
        """
        Submits feedback for a role request. 
        Saves the feedback to the database and sends it anonymously.

        Args:
            interaction (discord.Interaction): The interaction used for sending the feedback.
            user_id (int): The ID of the user submitting the feedback.
            feedback (str): The feedback to submit.
        """

        # Submit internally
        app.submit_feedback(self.thread_id, user_id, feedback)

        # Send public message anonymously
        await interaction.channel.send(f"**=== Anonymous Feedback ===**\n{feedback}")

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
        vote_message = bot.get_message(vote_message_id) or await thread.fetch_message(vote_message_id)

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


class VoteModal(discord.ui.Modal):
    def __init__(self, vote_type: str):
        super().__init__(title=f"Vote {vote_type.capitalize()}")
        self.vote_type = vote_type

        self.feedback = discord.ui.InputText(
            label="Submit anonymous feedback for this request?",
            style=discord.InputTextStyle.long,
            placeholder="Enter your feedback here...",
            required=False,
            max_length=3000
        )

        self.add_item(self.feedback)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()


async def _finish_vote(thread: discord.Thread, request: RoleRequest):
    """
    Finish the voting process and display the results.
    Edits thread tags and original voting prompt message.
    Closes and locks thread.
    Dependent on 'THREAD_TAGS' and 'CLOSE_POST' constants in config.

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

        # Close and lock the thread
        if CLOSE_POST:
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
    logger.info(
        f"# Ending vote with thread id '{view.thread_id}': \"{request.title}\"\n")

    # Remove the role request from the active list
    app.close_request(view.thread_id)

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
    except Exception as e:
        logger.error(f"Error when creating role request: {e}")
        await thread.send(f"Error when creating role request: {e}")
        return

    # Bunch of work needed to check roles below
    request = app.get_request(thread_id)
    guild = (bot.get_channel(CHANNEL_ID) or await bot.fetch_guild(CHANNEL_ID)).guild
    owner = await bot.get_or_fetch_user(thread.owner_id)
    owner_m = guild.get_member(thread.owner_id) or await guild.fetch_member(thread.owner_id)

    # People can't apply for a role they already have
    if request.role in [role.name for role in owner_m.roles] and not DEV_MODE:
        logger.error(
            f"{owner.mention} tried to create a request for {request.role} but they already have it.")
        app.remove_request(thread_id)
        await thread.send(f"Error: You already have the role {request.role}.")
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

    vote_message = None
    n = 0
    while not vote_message and n < 5:
        try:
            # Potentially getting an error on send that means a view isn't saved?
            vote_message = await thread.send(embed=embed, view=view)
            await vote_message.pin()

            app.update_bot_message_id(thread_id, vote_message.id)
            break
        except Exception as e:
            logger.error(f"Error when sending role request message: {e}\nTrying again.")
            n += 1
    else:
        logger.error(f"Failed to send role request message in {thread_id} after {n} tries. Deleting request.")
        app.remove_request(thread_id)
        await thread.send(f"Failed to send role request message in {thread_id} after {n} tries. Deleting request.")
        return

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


dotenv.load_dotenv()
TOKEN = os.getenv("Discord_Bot_Token")

# Cogs
cogs_list = [
    'open_cmds',
    'restricted_cmds'
]
for cog in cogs_list:
    bot.load_extension(f'cogs.{cog}')

bot.run(TOKEN)
