import os
from contextlib import AsyncExitStack

from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client

from next_step import CANVAS_URL

SERVER_COMMAND = r"D:\Canvas\test\canvas\cmcp\.venv\Scripts\canvas-mcp-server.exe"
SERVER_ENV = {
    "CANVAS_API_URL": f"{CANVAS_URL}/api/v1",
    "CANVAS_API_TOKEN": "cplatform-dev-token",
    "CANVAS_ALLOW_INSECURE_HTTP": "true",
    "ENABLE_DATA_ANONYMIZATION": "true",
    "MCP_SERVER_NAME": "cmcp",
}


def _server_params() -> StdioServerParameters:
    return StdioServerParameters(command=SERVER_COMMAND, args=[], env={**os.environ, **SERVER_ENV})


def _result_text(result: types.CallToolResult) -> str:
    return "\n".join(
        block.text for block in result.content if isinstance(block, types.TextContent)
    )


class NudgeSession:
    async def __aenter__(self) -> "NudgeSession":
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        try:
            read_stream, write_stream = await self._stack.enter_async_context(
                stdio_client(_server_params())
            )
            self._session = await self._stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self._session.initialize()
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool | None:
        return await self._stack.__aexit__(exc_type, exc, tb)

    async def list_text(self, user_id) -> str:
        result = await self._session.call_tool("list_nudges", {"user_id": str(user_id)})
        return _result_text(result)

    async def push(self, user_id, text, context, url="") -> str:
        arguments = {"user_id": str(user_id), "text": text, "context": context}
        if url:
            arguments["url"] = url
        result = await self._session.call_tool("push_nudge", arguments)
        text_out = _result_text(result)
        if result.is_error:
            raise RuntimeError(text_out)
        return text_out
