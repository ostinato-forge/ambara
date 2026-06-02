"""stdio transport helpers for the MCP server."""

from __future__ import annotations

import logging
import queue
import sys
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.shared.message import SessionMessage


def run_stdio(mcp: FastMCP, *, logger: logging.Logger) -> None:
    """Run the MCP server over stdio without AnyIO file-wrapper reads."""
    anyio.run(_run_stdio_async, mcp, logger)


async def _run_stdio_async(mcp: FastMCP, logger: logging.Logger) -> None:
    async with _stdio_server_without_anyio_file_threads(logger) as (
        read_stream,
        write_stream,
    ):
        await mcp._mcp_server.run(  # noqa: SLF001 - FastMCP exposes no public transport hook.
            read_stream,
            write_stream,
            mcp._mcp_server.create_initialization_options(),  # noqa: SLF001
        )


@asynccontextmanager
async def _stdio_server_without_anyio_file_threads(
    logger: logging.Logger,
) -> AsyncIterator[tuple[Any, Any]]:
    read_stream_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](
        0
    )
    write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](0)
    stdin_queue: queue.Queue[str | Exception | None] = queue.Queue()

    def read_stdin() -> None:
        try:
            for line in sys.stdin:
                stdin_queue.put(line)
        except Exception as exc:
            stdin_queue.put(exc)
        finally:
            stdin_queue.put(None)

    threading.Thread(target=read_stdin, daemon=True).start()

    async def stdin_pump() -> None:
        async with read_stream_writer:
            while True:
                item = await _poll_queue(stdin_queue)
                if item is None:
                    return
                if isinstance(item, Exception):
                    await read_stream_writer.send(item)
                    continue
                try:
                    message = types.JSONRPCMessage.model_validate_json(item)
                except Exception as exc:  # pragma: no cover - malformed client message
                    logger.exception("Failed to parse JSON-RPC message from stdin")
                    await read_stream_writer.send(exc)
                    continue
                await read_stream_writer.send(SessionMessage(message))

    async def stdout_pump() -> None:
        async with write_stream_reader:
            async for session_message in write_stream_reader:
                payload = session_message.message.model_dump_json(
                    by_alias=True,
                    exclude_none=True,
                )
                sys.stdout.write(payload + "\n")
                sys.stdout.flush()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdin_pump)
        tg.start_soon(stdout_pump)
        try:
            yield read_stream, write_stream
        finally:
            tg.cancel_scope.cancel()


async def _poll_queue[T](items: queue.Queue[T]) -> T:
    while True:
        try:
            return items.get_nowait()
        except queue.Empty:
            await anyio.sleep(0.01)
