import asyncio
import discord
import os
import dotenv
from discord.ext import tasks
from datetime import datetime
from config import VOTE_TIME_PERIOD, ROLE_VOTES, CHANNEL_ID
from app import RequestsManager
from request import RoleRequest

bot = discord.Bot()
app = RequestsManager()
app.load_state()

class VoteView(discord.ui.View):
    def __init__(self, thread_owner: discord.User, thread_id: int, thread_title: str, end_time: int):
        # Called every time the bot restarts
        super().__init__(timeout=None)
        self.thread_owner: discord.User = thread_owner
        self.thread_title = thread_title
        self.thread_id = thread_id
        self.end_time = end_time
        self.check_time.start()
        self.id = app.add_request(self.thread_owner.id, self.thread_id, self.thread_title, self.end_time)

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success, custom_id="vote_yes")
    async def yes_button_callback(self, button, interaction):
        await self.handle_vote(interaction, "yes")

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger, custom_id="vote_no")
    async def no_button_callback(self, button, interaction):
        await self.handle_vote(interaction, "no")

    async def handle_vote(self, interaction, vote_type):
        user: discord.User = interaction.user
        role_votes = self.get_user_votes(user)
        try:
            app.vote_on_request(self.id, user.id, role_votes * (-1 if vote_type == "no" else 1))
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)

        await interaction.response.send_message(f"You voted {vote_type.capitalize()} with {role_votes} votes.", ephemeral=True)

    def get_user_votes(self, user):
        for role in user.roles:
            if role.name in ROLE_VOTES:
                return ROLE_VOTES[role.name]
        return 1

    @tasks.loop(seconds=10)
    async def check_time(self):
        print("checking...")
        if datetime.utcnow().timestamp() >= self.end_time:
            self.check_time.cancel()
            await end_vote(self)

async def _finish_vote(thread: discord.Thread, request: RoleRequest):
    # Edit the original "Vote now!" message to show the vote results and remove the view
    print("Editing vote message to show results...")
    try:
        vote_message = await thread.fetch_message(request.bot_message_id)
        yes_votes, no_votes = request.get_votes()
        await vote_message.edit(content=f"Voting has ended.\nResults:\nYes: {yes_votes}\nNo: {no_votes}", view=None)
    except discord.NotFound:
        print("Vote message not found.")
    except discord.HTTPException as e:
        print(f"Failed to edit vote message: {e}")

    print("Voting has ended.")

# Can't actually be part of the VoteView class for some reason...
async def end_vote(self: VoteView):
    print("Ending vote...")
    self.check_time.stop()

    # Get the current thread
    thread = bot.get_channel(self.thread_id)
    if not isinstance(thread, discord.Thread):
        print("Error: Thread not found or is not a thread.")
        return 

    # Do we hand out the role or not?
    request: RoleRequest = app.get_request(self.id)
    give_role = request.result()
    print(f"Result: {give_role} - {request.get_votes()}")

    # Delete the role request from the active list either way
    print("Deleting record...")
    app.remove_request(self.id)
    try:
        if not give_role:
            await thread.send(f"Sorry, {self.thread_owner.mention}! You have not been given the role.")
            # await _finish_vote(thread, request)
            # return

        # Get guild and role from the discord api
        guild = bot.get_channel(CHANNEL_ID).guild
        role = discord.utils.get(guild.roles, name=request.role)
        print(thread.name, guild.name, role)

        if not role:
            await thread.send(f"Error: Role {role.name} not found in the server.")
            # await _finish_vote(thread, request)
            # return

        # Get the member from the user (yes it's confusing)
        member = guild.get_member(self.thread_owner.id) or await guild.fetch_member(self.thread_owner.id)
        print(member)

        if not member:
            await thread.send(f"Error: Member {self.thread_owner.mention} not found in the server.")
            # await _finish_vote(thread, request)
            # return
        
        # Add the role to the user if possible
        print("Adding role...")
        if member.id == member.guild.owner_id:
            print("Cannot modify roles of the server owner.")
            await thread.send(f"Error: Cannot modify roles of the server owner, {self.thread_owner.mention}.")
            # _finish_vote(thread, request)
        else:
            await member.add_roles(role)
            print("Role added successfully.")
            await thread.send(f"Congratulations, {self.thread_owner.mention}! You have been given the {role.name} role.")
            # _finish_vote(thread, request)
    except discord.Forbidden:
        print("Bot does not have permission to add roles.")
        await thread.send(f"Error: Bot does not have permission to add roles, {self.thread_owner.mention}.")
        # _finish_vote(thread, request)
    except discord.HTTPException as e:
        print(f"Failed to add role: {e}")
        await thread.send(f"Failed to add role due to an error: {e}, {self.thread_owner.mention}.")
        # _finish_vote(thread, request)
    except asyncio.exceptions.CancelledError:
          # weird occurance, but thread.send always causes this even when it works
          await _finish_vote(thread, request)


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    # Load all active role requests from the saved state on restart
    for request in app.requests.values():
        print(app.requests)
        thread_owner_id = request.user_id
        thread_owner = await bot.get_or_fetch_user(thread_owner_id)
        thread_title = request.title
        thread_id = request.thread_id
        end_time = request.end_time
        bot.add_view(VoteView(thread_owner, thread_id, thread_title, end_time))

@bot.event
async def on_thread_create(thread: discord.Thread):
    # Create an active role request for the first time
    if thread.parent_id == CHANNEL_ID:
        thread_owner_id = thread.owner_id
        thread_owner = await bot.get_or_fetch_user(thread_owner_id)
        thread_title = thread.name
        thread_id = thread.id
        end_time = datetime.utcnow().timestamp() + VOTE_TIME_PERIOD
        vote_message = await thread.send("Vote now!", view=VoteView(thread_owner, thread_id, thread_title, end_time))
        app.update_bot_message_id(thread_id, vote_message.id)

# Help command contents
help_text = """

__Source code:__ <https://github.com/0neye/Role-Request-Voting>

Role Voting helps determine the outcome of an Excelsior role request using an anyonymous voting system.

When a new thread is made in the role requests forum channel, it will send a message with *Yes* and *No* buttons. Select one of these buttons to cast your vote.
After a set amount of time, the bot will show the results of the poll and automatically assign a role if enough people voted *Yes*.

...and its as simple as that, with no slash commands needed for operation!
"""

@bot.command(description="Instructions for using bot, and provides a link to source code")
async def help(ctx):
    await ctx.respond(help_text)

@bot.command(description="end a vote in a given thread early")
async def end_vote(ctx):
    await ctx.respond(f"Vote ended by "+ctx.user.display_name)

dotenv.load_dotenv()
TOKEN = os.getenv("Discord_Bot_Token")

bot.run(TOKEN)