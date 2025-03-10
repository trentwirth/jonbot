import asyncio
import logging
from typing import List, TYPE_CHECKING

import discord

from jonbot.backend.data_layer.models.discord_stuff.discord_message_document import DiscordMessageDocument
from jonbot.backend.data_layer.models.user_stuff.memory.context_memory_document import ContextMemoryDocument
from jonbot.frontends.discord_bot.cogs.bot_config_cog.helpers.get_pinned_messages_in_channel import get_pinned_messages
from jonbot.frontends.discord_bot.handlers.should_process_message import allowed_to_reply_to_message

BOT_CONFIG_CHANNEL_NAME = "bot-config"

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from jonbot.frontends.discord_bot.discord_bot import MyDiscordBot


class BotConfigCog(discord.Cog):
    def __init__(self, bot: "MyDiscordBot"):
        super().__init__()
        self.bot = bot

        self._bot_config_emoji = "🤖"
        self._memory_emoji = "💭"
        self._remove_memory_emoji = "❌"

    @discord.Cog.listener()
    async def on_guild_channel_pins_update(self, channel: discord.TextChannel, last_pin: discord.Message):
        logger.debug(f"Received pin update for channel: {channel}")
        self.bot.pinned_messages_by_channel_id[channel.id] = await get_pinned_messages(channel=channel)

    @discord.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        logger.debug(f"Received reaction: {payload}")
        user = self.bot.get_user(payload.user_id)
        guild = self.bot.get_guild(payload.guild_id)
        channel = self.bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)

        if not allowed_to_reply_to_message(message=message,
                                           bot_id=self.bot.user.id,
                                           bot_user_name=self.bot.user.name):
            return

        emoji = str(payload.emoji)

        if guild is not None:
            if emoji == self._bot_config_emoji and BOT_CONFIG_CHANNEL_NAME in channel.name:
                logger.debug(f"Reaction was in bot-config channel, updating config messages")
                self.bot.config_messages_by_guild_id[payload.guild_id] = await self.get_bot_config_channel_prompts(
                    guild=guild)

        if emoji == self._memory_emoji:
            logger.debug(f"User reacted with memory emoji - adding memory message to channel ({channel}) list")
            if payload.channel_id not in self.bot.memory_messages_by_channel_id.keys():
                self.bot.memory_messages_by_channel_id[payload.channel_id] = []

            if message not in self.bot.memory_messages_by_channel_id[payload.channel_id]:
                message_document = await DiscordMessageDocument.from_discord_message(message=message)
                self.bot.memory_messages_by_channel_id[payload.channel_id].append(message_document)

            if not user == self.bot.user:
                logger.debug("Emoji was added by a user, so botto will add their own reaction")
                await message.add_reaction(self._memory_emoji),

            logger.debug(f"Adding remove memory emoji to message: {self._remove_memory_emoji}")
            await message.add_reaction(self._remove_memory_emoji)

        if emoji == self._remove_memory_emoji and not user == self.bot.user:
            logger.debug(f"User reacted with remove memory emoji - removing memory message")
            await message.remove_reaction(self._remove_memory_emoji, self.bot.user)
            await message.remove_reaction(self._memory_emoji, self.bot.user)
            await message.remove_reaction(self._remove_memory_emoji, user)
            await message.remove_reaction(self._memory_emoji, user)

            if not payload.channel_id in self.bot.memory_messages_by_channel_id.keys():
                self.bot.memory_messages_by_channel_id[payload.channel_id] = []
            for message in self.bot.memory_messages_by_channel_id[payload.channel_id]:
                if message.message_id == payload.message_id:
                    message_document = await DiscordMessageDocument.from_discord_message(message=message)
                    self.bot.memory_messages_by_channel_id[payload.channel_id].remove(message_document)
                    break

    async def get_memory_messages(self,
                                  channel: discord.channel,
                                  memory_emoji: str = "💭") -> List[DiscordMessageDocument]:

        memory_messages = await self.look_for_emoji_reaction_in_channel(channel=channel,
                                                                        emoji=memory_emoji)
        documents = [await DiscordMessageDocument.from_discord_message(message=message) for message in memory_messages]

        if len(documents) == 0:
            logger.trace(f"Channel: {channel} - No memory messages found")
        else:
            logger.trace(f"Channel: {channel} - Found {len(documents)} memory messages")
        return documents

    async def gather_config_messages(self,
                                     channel: discord.channel, ):
        try:
            logger.info(f"Getting config messages")

            if channel.guild is not None:
                self.bot.config_messages_by_guild_id[channel.guild.id] = await self.get_bot_config_channel_prompts(
                    guild=channel.guild)
            self.bot.pinned_messages_by_channel_id[channel.id] = await get_pinned_messages(channel=channel)
            self.bot.memory_messages_by_channel_id[channel.id] = await self.get_memory_messages(channel=channel)

        except Exception as e:
            logger.error(f"Error getting config messages")
            logger.exception(e)
            raise
        logger.success(f"Finished gathering config messages")

    async def get_bot_config_channel_prompts(self,
                                             guild: discord.Guild,
                                             bot_config_channel_name: str = BOT_CONFIG_CHANNEL_NAME,
                                             selected_emoji: str = "🤖") -> List[str]:
        """
        Get messages from the `bot-config` channel in the server, if it exists
        :param message:
        :param bot_config_channel_name:
        :param selected_emoji:
        :return: List[str]
        """
        logger.debug(f"Getting extra prompts from bot-config channel")
        try:
            emoji_prompts = []
            pinned_messages = []
            for channel in filter(lambda channel: bot_config_channel_name in channel.name, guild.channels):
                logger.debug(f"Found bot-config channel: {channel}")
                pinned_messages = await get_pinned_messages(channel=channel)
                bot_emoji_messages = await self.look_for_emoji_reaction_in_channel(channel,
                                                                                   emoji=selected_emoji)
                emoji_prompts = [message.content for message in bot_emoji_messages]

            bot_config_prompts = list(set(pinned_messages + emoji_prompts))
            if len(bot_config_prompts) == 0:
                logger.debug(f"No extra prompts found in bot-config channel")
            else:
                logger.debug(
                    f"Found {len(bot_config_prompts)} prompts for bot {self.bot.user} in `{guild}` - `{channel}`")
            return bot_config_prompts
        except Exception as e:
            logger.error(f"Error getting extra prompts from bot-config channel")
            logger.exception(e)
            raise

    async def update_memory_emojis(self,
                                   context_memory_document: ContextMemoryDocument,
                                   message: discord.Message):
        memory_message_ids = []
        for memory_message in context_memory_document.chat_memory_message_buffer.message_buffer:
            if "message_id" in memory_message.additional_kwargs.keys():
                memory_message_ids.append(memory_message.additional_kwargs["message_id"])

        emoji_tasks = []

        async def update_message(channel: discord.TextChannel, message_id: int):

            message = await channel.fetch_message(message_id)
            if "💭" not in message.reactions:
                logger.trace(f"Adding memory emoji to message id: {message.id}")
                await message.add_reaction("💭")

        for memory_message_id in memory_message_ids:
            emoji_tasks.append(update_message(channel=message.channel, message_id=memory_message_id))

        await asyncio.gather(*emoji_tasks)
        logger.success(f"Finished updating memory emojis")

    async def look_for_emoji_reaction_in_channel(self,
                                                 channel: discord.TextChannel,
                                                 emoji: str,
                                                 self_only: bool = False) -> List[discord.Message]:
        try:
            messages = []
            async for msg in channel.history(limit=100):
                # use messages with `bot` emoji reactions as prompts
                if msg.reactions:
                    for reaction in msg.reactions:
                        if str(reaction.emoji) == emoji:
                            if self_only and not reaction.me:
                                continue
                            messages.append(msg)
            return messages
        except discord.Forbidden:
            logger.debug(f"Bot does not have permission to read messages in channel: {channel.name}")
            return []
        except Exception as e:
            logger.error(f"Error looking for emoji reaction in channel: {channel.name}")
            logger.exception(e)
            raise
