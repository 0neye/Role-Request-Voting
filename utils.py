from typing import Optional, Tuple
import discord
from request import RoleRequest
from config import ROLE_VOTES, DEFAULT_VOTE


def get_user_votes(user: discord.Member, request: RoleRequest) -> int:
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

async def get_user_names(bot: discord.Bot, guild: discord.Guild, user_id: int) -> Tuple[str, str]:
    """
    Get a user's display name, handling cases where the user is not in the guild.

    Args:
        guild (discord.Guild): The guild the user is in (hopefully).
        user_id (int): The ID of the user.

    Returns:
        Tuple[str, str]: The display name of the user and their global username. Can be identical.
    """
    try:
        member: discord.Member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        return member.display_name, member.name
    except discord.errors.NotFound:
        user: Optional[discord.User] = await bot.get_or_fetch_user(user_id)
        if user is None:
            return 'User', f'#{user_id}'

        return user.display_name, user.name
    

async def respond_long_message(
    interaction: discord.Interaction,
    text: str,
    chunk_size: int = 1800,
    use_codeblock: bool = False,
    **kwargs,
):
    """
    Sends a message longer than discord's character limit by chunking it.
    Supports all kwargs for discord.Interaction.respond().
    """
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

    for chunk in chunks:
        if use_codeblock:
            chunk = f"```md\n{chunk}\n```"

        await interaction.respond(chunk, **kwargs)

async def send_long_message(
    channel: discord.abc.Messageable,
    text: str,
    chunk_size: int = 1800,
    use_codeblock: bool = False,
    **kwargs,
):
    """
    Sends a message longer than discord's character limit by chunking it.
    Supports all kwargs for discord.Message.send().
    """
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

    for chunk in chunks:
        if use_codeblock:
            chunk = f"```md\n{chunk}\n```"

        await channel.send(chunk, **kwargs)