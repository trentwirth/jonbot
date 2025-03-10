from typing import List, Union, Any, Dict

from langchain.memory import ConversationSummaryBufferMemory
from langchain.schema import HumanMessage, AIMessage

from jonbot.backend.ai.chatbot.components.memory.conversation_memory.context_memory_handler import (
    ContextMemoryHandler,
)
from jonbot.backend.data_layer.models.discord_stuff.discord_message_document import DiscordMessageDocument
from jonbot.backend.data_layer.models.user_stuff.memory.chat_memory_message_buffer import ChatMemoryMessageBuffer
from jonbot.backend.data_layer.models.user_stuff.memory.context_memory_document import ContextMemoryDocument
from jonbot.backend.data_layer.models.user_stuff.memory.memory_config import ChatbotConversationMemoryConfig
from jonbot.system.setup_logging.get_logger import get_jonbot_logger

logger = get_jonbot_logger()

from jonbot.backend.backend_database_operator.backend_database_operator import (
    BackendDatabaseOperations,
)
from jonbot.backend.data_layer.models.context_route import ContextRoute


class ChatbotConversationMemory(ConversationSummaryBufferMemory):
    context_memory_handler: ContextMemoryHandler

    def __init__(
            self,
            context_route: "ContextRoute",
            database_name: str,
            database_operations: "BackendDatabaseOperations",
            config: ChatbotConversationMemoryConfig = None,
    ):
        if config is None:
            config = ChatbotConversationMemoryConfig()

        super().__init__(
            memory_key=config.memory_key,
            input_key=config.input_key,
            llm=config.llm,
            return_messages=config.return_messages,
            max_token_limit=config.max_token_limit,
            context_memory_handler=ContextMemoryHandler(
                context_route=context_route,
                database_name=database_name,
                database_operations=database_operations,
                summary_prompt=config.summary_prompt,
            ),
        )

        self.prompt = config.summary_prompt

    @property
    async def context_memory_document(self) -> ContextMemoryDocument:
        return await self.context_memory_handler.context_memory_document

    async def configure_memory(self):
        self._build_memory_from_context_memory_document(
            document=await self.context_memory_document
        )

    @property
    def token_count(self) -> int:
        tokens_in_messages = self.llm.get_num_tokens_from_messages(self.buffer)
        tokens_in_summary = self.llm.get_num_tokens(self.moving_summary_buffer)
        return tokens_in_messages + tokens_in_summary

    def _build_memory_from_context_memory_document(
            self, document: ContextMemoryDocument
    ):
        self._load_messages_from_message_buffer(buffer=document.chat_memory_message_buffer)

        # # self.message_uuids = [message["additional_kwargs"]["uuid"] for message in self.message_buffer],
        self.moving_summary_buffer = document.summary
        self.prompt = document.summary_prompt

    def _load_messages_from_message_buffer(
            self, buffer: List[Dict[str, Any]]
    ) -> List[Union[HumanMessage, AIMessage]]:
        messages = []
        try:
            for message in buffer:
                if message.additional_kwargs["type"] == "human":
                    if isinstance(message, AIMessage):
                        logger.warning(
                            f"Message type is AIMessage but type is `human`: {message}"
                        )
                    messages.append(message)
                elif message.additional_kwargs["type"] == "ai":
                    if isinstance(message, HumanMessage):
                        logger.warning(
                            f"Message type is HumanMessage but type is `ai`: {message}"
                        )
                    messages.append(AIMessage(**message.dict()))
            self.chat_memory.messages = messages
        except Exception as e:
            logger.exception(e)
            raise

    async def update(self,
                     inputs: Dict[str, Any],
                     outputs: Dict[str, Any]):
        try:
            self.save_context(inputs={"human_input": inputs["human_input"]},
                              outputs={"output": outputs["output"]})
            buffer = self.buffer
            for message in buffer:
                if message.content == inputs["human_input"]:
                    message.additional_kwargs["message_id"] = inputs["message_id"]
                elif message.content == outputs["output"]:
                    message.additional_kwargs["message_id"] = outputs["message_id"]

            await self.context_memory_handler.update(
                chat_memory_message_buffer=ChatMemoryMessageBuffer(message_buffer=buffer),
                summary=self.moving_summary_buffer,
                token_count=self.token_count,
            )
        except Exception as e:
            logger.error(f"Failed to update context memory: {e}")
            logger.exception(e)
            raise

    def set_memory_messages(self, memory_messages: List[DiscordMessageDocument]):
        chat_history_message_buffer = ChatMemoryMessageBuffer.from_discord_message_documents(
            discord_message_documents=memory_messages)

        self.chat_memory.messages = chat_history_message_buffer.message_buffer
        self.context_memory_handler.update(chat_memory_message_buffer=chat_history_message_buffer)
