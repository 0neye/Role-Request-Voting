import asyncio
import io
import discord
from utils import get_user_names, respond_long_message
from typing import Optional
from discord.ext import commands
from bot import logger, app, end_vote, _init_request
from config import CHANNEL_ID, COMMAND_WHITELISTED_ROLES, DEV_MODE, LOG_FILE_NAME, MOD_LOG_CHANNEL_ID


class RestrictedCmds(commands.Cog):
    """Restricted commands that can only be used by specific roles."""

    def __init__(self, bot):
        self.bot: discord.Bot = bot

    async def _restricted_cmd_ctx_to_thread(self, ctx) -> Optional[discord.Thread]:
        """
        Performs basic checks for restricted commands and returns the thread if valid.
        Dependent on the 'COMMAND_WHITELISTED_ROLES' and 'CHANNEL_ID' constants in config.

        Args:
            ctx (discord.ext.commands.Context): The context of the command.

        Returns:
            Optional[discord.Thread]
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
        
    
    async def _log_command_use(self, ctx, command_name) -> bool:
        """
        Log command usage to the moderation log channel.
        Dependant on the 'MOD_LOG_CHANNEL' constant in config.

        Args:
            ctx (discord.ext.commands.Context): The context of the command.
            command_name (str): The name of the command being used.
        
        Returns:
            bool: True if logging was successful, False otherwise.
        """
        if MOD_LOG_CHANNEL_ID:
            try:
                channel = self.bot.get_channel(MOD_LOG_CHANNEL_ID) or await self.bot.fetch_channel(MOD_LOG_CHANNEL_ID)
                await channel.send(f"{ctx.user.mention} used the '{command_name}' command in {ctx.channel.mention}.")
                logger.info(f"User {ctx.user} used the '{command_name}' command in {ctx.channel.mention}.")
                return True
            except Exception as e:
                logger.error(f"Failed to log command use: {e}")
                await ctx.respond("Failed to log command use to moderation log channel.", ephemeral=True)
                return False
        return True

    @commands.slash_command(description="Manually create a vote in this thread. Requires moderator or Paragon roles.")
    async def create_vote(self, ctx):
        """
        Manually creates a vote in the current thread.
        Dependent on 'COMMAND_WHITELISTED_ROLES' constant in config.

        Args:
            ctx (discord.ext.commands.Context): The context of the command.
        """

        # Get the thread
        thread = await self._restricted_cmd_ctx_to_thread(ctx)
        if thread is None:
            return

        # Check if a request is created for this thread
        if app.get_request(thread.id) is not None:
            await ctx.respond("This thread already has a running vote.", ephemeral=True)
            return

        # Create the request and vote
        await _init_request(thread)

        await ctx.respond("Vote created.", ephemeral=True)

    @commands.slash_command(
        description="End the vote in this thread early. Requires moderator or Paragon roles.",
    )
    async def end_vote_early(self, ctx, outcome: discord.Option(str, choices=["Approve", "Deny", "Abstain"])):
        """
        End the vote in the current thread early.
        Dependent on 'COMMAND_WHITELISTED_ROLES' constant in config.

        Args:
            ctx (discord.ApplicationContext): The context of the command.
            outcome (str): The outcome of the vote ("Approve", "Deny" or "Abstain").
        """

        # Get the thread
        thread = await self._restricted_cmd_ctx_to_thread(ctx)
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
            (v for v in self.bot.persistent_views if v.thread_id == thread.id), None)
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

    @commands.slash_command(description="Force-deletes a role request ungracefully. Logged and requires moderator or Paragon roles.")
    async def force_delete_request(self, ctx):
        """
        Force-deletes a role request ungracefully.
        Dependent on the 'COMMAND_WHITELISTED_ROLES' and 'MOD_LOG_CHANNEL' constants in config.

        Args:
            ctx (discord.ext.commands.Context): The context of the command.
        """

        try:
            # Get the thread
            thread = await self._restricted_cmd_ctx_to_thread(ctx)
            if thread is None:
                return

            # Ask for confirmation
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Confirm",
                        style=discord.ButtonStyle.danger, custom_id="confirm"))
            await ctx.interaction.response.send_message(
                "Are you sure you want to force-delete this request? This action cannot be undone.",
                view=view,
                ephemeral=True
            )

            try:
                # Wait for the user to click the button
                interaction = await self.bot.wait_for(
                    "interaction",
                    check=lambda i: i.data["custom_id"] == "confirm" and i.user.id == ctx.author.id,
                    timeout=60.0
                )
            except asyncio.TimeoutError:
                await ctx.interaction.edit_original_message(content="Force-delete request timed out.", view=None)
                return

            # User confirmed, proceed with deletion
            await interaction.response.defer()
            await ctx.interaction.edit_original_message(content="Proceeding with force-delete...", view=None)

            # Log command use to moderation log channel
            if not await self._log_command_use(ctx, "force-delete-request"):
                return

            # Force-delete the request
            request = app.get_request(thread.id)
            if request is not None:
                try:
                    message = await thread.fetch_message(request.bot_message_id)
                    await message.delete()
                except:
                    # No vote message exists, our job is already done
                    pass
                app.remove_request(thread.id)

                await ctx.respond("Request deleted.", ephemeral=True)
            else:
                await ctx.respond("This thread is not an active role request.", ephemeral=True)

        except Exception as e:
            logger.error(f"Failed to force-delete request: {e}")


    @commands.slash_command(description="Show voting data for most recent request. Logged and requires moderator or Paragon roles.")
    async def show_votes(self, ctx):
        """
        Show all voting data for the most recent request.
        Dependent on the 'COMMAND_WHITELISTED_ROLES' and 'MOD_LOG_CHANNEL' constants in config.

        Args:
            ctx (discord.ext.commands.Context): The context of the command.
        """

        try:
            # Get the thread
            thread = await self._restricted_cmd_ctx_to_thread(ctx)
            if thread is None:
                return

            _guild: discord.Guild = ctx.guild

            # Get the most recent request
            request = app.get_request(
                thread.id) or app.get_closed_requests(thread.id)
            if request is None:
                await ctx.respond("This thread is not an active role request and has no closed requests.", ephemeral=True)
                return
            if isinstance(request, list):
                request = request[-1]

            # Log command use to moderation log channel
            if not await self._log_command_use(ctx, "show-votes"):
                return

            # Create a markdown formatted string to display voting data
            voting_data = f"# Voting Data for {request.role} Request\n\n"
            voting_data += f"**Request Title:** {request.title}\n"
            name = await get_user_names(self.bot, _guild, request.user_id)
            voting_data += f"**Requester:** {name[0]} (<@{request.user_id}>)\n\n"


            # Get the vote data
            vote_data = []
            for vote_list, vote_type in [(request.yes_votes, "Yes"), (request.no_votes, "No")]:
                for user_id, vote_count in vote_list:
                    display_name, username = await get_user_names(self.bot, _guild, user_id)
                    vote_data.append((display_name, username, vote_type, vote_count))

            # Sort vote data by number of votes
            vote_data.sort(key=lambda x: x[3], reverse=True)

            # Create the table with dynamic field sizes
            voting_data += "## Votes\n\n"
            longest_name = max(len(f"{display_name} ({username}):") for display_name, username, _, _ in vote_data)
            
            header = f"| {'User':<{longest_name}} | Vote | Count |\n"
            separator = f"|{'-' * (longest_name + 2)}|------|-------|\n"
            voting_data += header + separator
            
            for display_name, username, vote_type, vote_count in vote_data:
                full_name = f"{display_name} ({username}):"
                voting_data += f"| {full_name:<{longest_name}} | {vote_type:<4} | {vote_count:<5} |\n"

            # Add vote totals and outcome
            yes_count, no_count = request.get_votes()
            voting_data += "\n## Vote Totals\n\n"
            voting_data += f"- Yes: {yes_count}\n"
            voting_data += f"- No: {no_count}\n"
            voting_data += f"- Accepted: {request.result()}\n"

            # Create feedback file if any
            feedback_file = None
            if request.feedback:
                feedback_content = ""
                for user_id, feedback in request.feedback:
                    display_name, username = await get_user_names(self.bot, _guild, user_id)
                    feedback_content += f"# {display_name} ({username}):\n```{feedback}```\n\n"
                feedback_file = discord.File(io.StringIO(feedback_content), filename="feedback.md")
            else:
                voting_data += "\n## Feedback\n\nNo feedback submitted\n"

            # Add veto information if any
            if request.veto:
                veto_user_id, veto_result = request.veto
                veto_display_name, veto_user_name = await get_user_names(self.bot, _guild, veto_user_id)
                voting_data += "\n## Veto\n\n"
                voting_data += f"Veto by {veto_display_name} ({veto_user_name}): {'Approved' if veto_result else 'Denied'}\n"

            # Send the embed and feedback file
            # await ctx.respond(content="Command use logged.", embed=embed, file=feedback_file, ephemeral=True)
            await respond_long_message(ctx.interaction, voting_data, use_codeblock=True, file=feedback_file, ephemeral=True)

        except Exception as e:
            logger.error(f"Error showing votes in thread {thread.id}: {e}")
            await ctx.respond("Failed to show voting data.", ephemeral=True)


    @commands.slash_command(description="Sends the log file as a file attachment. Requires moderator or Paragon roles.")
    async def send_log(self, ctx):
        """
        Sends the log file as a file attachment. Dependent on 'COMMAND_WHITELISTED_ROLES' and 'LOG_FILE_NAME' constant in config.

        Args:
            ctx (discord.ext.commands.Context): The context of the command.
        """

        # Get the log file
        log_file = open(LOG_FILE_NAME, "rb")

        # Send the log file
        await ctx.respond(file=discord.File(log_file, LOG_FILE_NAME), ephemeral=True)
        log_file.close()


def setup(bot):
    bot.add_cog(RestrictedCmds(bot))
