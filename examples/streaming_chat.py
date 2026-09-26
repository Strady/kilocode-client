"""Stream a session's events live and react to text deltas, tool calls and turns.

Uses :meth:`Kilo.send_prompt_async` (``POST /session/{id}/prompt_async``), which
returns immediately and runs the agent loop in the background, so we must subscribe
to the event stream *before* sending to observe text deltas as they arrive.

Run against a live server, e.g.:

    kilo serve --port 4096 &
    python examples/streaming_chat.py
"""

import asyncio

from kilocode_client import Kilo
from kilocode_client import text_delta_of, tool_call_of


async def main(base_url: str = "http://127.0.0.1:4096") -> None:
    client = Kilo(base_url=base_url)
    session = await client.session.create(title="streaming-chat-example")

    async def send() -> None:
        await asyncio.sleep(0.2)
        await client.send_prompt_async(
            session.id, "List three Python web frameworks, then stop."
        )

    sender = asyncio.create_task(send())

    async for event in await client.stream_session_events(session.id):
        delta = text_delta_of(event)
        if delta:
            print(delta, end="", flush=True)
        tool = tool_call_of(event)
        if tool:
            print(f"\n[tool {tool.status}] {tool.tool} {tool.input}", flush=True)
        if event.is_turn_close:
            reason = event.turn_close_reason
            print(f"\n--- turn closed ({reason}) ---", flush=True)
            break

    sender.cancel()
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())