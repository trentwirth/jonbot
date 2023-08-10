import asyncio
import logging
from typing import Any, Dict, List

from fastapi import FastAPI
from langchain.callbacks.base import AsyncCallbackHandler
from langchain.schema import LLMResult
from starlette.responses import StreamingResponse
from uvicorn import Config, Server

from jonbot.layer2_core_processes.ai_chatbot.ai_chatbot import AIChatBotBuilder
from jonbot.layer2_core_processes.audio_transcription.transcribe_audio import transcribe_audio
from jonbot.layer3_data_layer.data_models.conversation_models import ChatResponse, ChatRequest
from jonbot.layer3_data_layer.data_models.database_upsert_models import DatabaseUpsertResponse, DatabaseUpsertRequest
from jonbot.layer3_data_layer.data_models.voice_to_text_request import VoiceToTextRequest, VoiceToTextResponse
from jonbot.layer3_data_layer.database.get_or_create_mongo_database_manager import get_or_create_mongo_database_manager

logger = logging.getLogger(__name__)

CHAT_ENDPOINT = "/chat"
VOICE_TO_TEXT_ENDPOINT = "/voice_to_text"
CHAT_STREAM_ENDPOINT = "/chat_stream"
DATABASE_UPSERT_ENDPOINT = "/database_upsert"

STREAMING_RESPONSE_TEST_ENDPOINT = "/test_streaming_response"

API_CHAT_URL = f"http://localhost:8000{CHAT_ENDPOINT}"
API_VOICE_TO_TEXT_URL = f"http://localhost:8000{VOICE_TO_TEXT_ENDPOINT}"
API_CHAT_STREAM_URL = f"http://localhost:8000{CHAT_STREAM_ENDPOINT}"
API_DATABASE_UPSERT_URL = f"http://localhost:8000{DATABASE_UPSERT_ENDPOINT}"

API_STREAMING_RESPONSE_TEST_URL = f"http://localhost:8000{STREAMING_RESPONSE_TEST_ENDPOINT}"
app = FastAPI()


@app.on_event("startup")
async def startup_event():
    await get_or_create_mongo_database_manager()


@app.post(CHAT_ENDPOINT, response_model=ChatResponse)
async def chat(chat_request: ChatRequest) -> ChatResponse:
    logger.info(f"Received chat request: {chat_request}")

    mongo_database = await get_or_create_mongo_database_manager()
    conversation_history = await mongo_database.get_conversation_history(
        context_route=chat_request.conversation_context.context_route)

    ai_chat_bot = await AIChatBotBuilder.build(conversation_context=chat_request.conversation_context,
                                               conversation_history=conversation_history, )

    chat_response = await ai_chat_bot.get_chat_response(chat_input_string=chat_request.chat_input.message)

    return chat_response


class StreamingAsyncCallbackHandler(AsyncCallbackHandler):
    async def on_llm_new_token(self, token: str, *args, **kwargs ) -> None:
        """Run when a new token is generated."""
        print("Hi! I just woke up. Your llm is generating a new token: '{token}'")
        yield f"lookit this token: {token} |"


@app.post(CHAT_STREAM_ENDPOINT, response_class=StreamingResponse)
async def chat_stream(chat_request: ChatRequest):
    logger.info(f"Received chat_stream request: {chat_request}")

    mongo_database = await get_or_create_mongo_database_manager()
    conversation_history = await mongo_database.get_conversation_history(
        context_route=chat_request.conversation_context.context_route)

    ai_chat_bot = await AIChatBotBuilder.build(conversation_context=chat_request.conversation_context,
                                               conversation_history=conversation_history, )

    ai_chat_bot.add_callback_handler(handler=StreamingAsyncCallbackHandler())

    async def stream_response():
        async for token in ai_chat_bot.stream_chat_response_tokens(input_text=chat_request.chat_input.message):
            yield token

    return StreamingResponse(stream_response(), media_type="text/plain")


@app.post(STREAMING_RESPONSE_TEST_ENDPOINT)
async def streaming_response_test():
    async def generate():
        for chunk in range(10):
            yield f"Data {chunk}\n"
            await asyncio.sleep(1)  # simulate some delay

    return StreamingResponse(generate(), media_type="text/plain")


@app.post(VOICE_TO_TEXT_ENDPOINT, response_model=VoiceToTextResponse)
async def voice_to_text(request: VoiceToTextRequest) -> VoiceToTextResponse:
    transcript_text = await transcribe_audio(
        request.audio_file_url,
        prompt=request.prompt,
        response_format=request.response_format,
        temperature=request.temperature,
        language=request.language
    )
    return VoiceToTextResponse(text=transcript_text)


@app.post(DATABASE_UPSERT_ENDPOINT, response_model=DatabaseUpsertResponse)
async def database_upsert(database_upsert_request: DatabaseUpsertRequest) -> DatabaseUpsertResponse:
    logger.info(f"Upserting data into database query - {database_upsert_request.query}")
    mongo_database = await get_or_create_mongo_database_manager()
    success = await mongo_database.upsert(**database_upsert_request.dict())
    if success:
        return DatabaseUpsertResponse(success=True)
    else:
        return DatabaseUpsertResponse(success=False)


def run_api():
    """
    Run the API for JonBot
    """
    logger.info("Starting API")
    import uvicorn

    uvicorn.run(app, host="localhost", port=8000)


async def run_api_async():
    """
    Run the API for JonBot
    """
    logger.info("Starting API")
    config = Config(app=app, host="localhost", port=8000)
    server = Server(config)
    await server.serve()


def run_api_sync():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_api_async())


if __name__ == '__main__':
    asyncio.run(run_api_async())
