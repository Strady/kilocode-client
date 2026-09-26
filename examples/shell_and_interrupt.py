"""Run a shell command through a session and interrupt an in-flight run.

Demonstrates running shell commands via `run_shell`/`run_command`, and using
`interrupt()` to stop a long-running agent turn. Run against a live server:

    kilo serve --port 4096 &
    python examples/shell_and_interrupt.py
"""

import asyncio

from kilocode_client import Kilo


async def main(base_url: str = "http://127.0.0.1:4096") -> None:
    client = Kilo(base_url=base_url)
    session = await client.session.create(title="shell-example")

    shell = await client.run_shell(session.id, "/bin/echo", "hello from kilocode-client")
    print("shell ack:", shell.info.role)

    # Start a long-running turn asynchronously, then interrupt it in flight.
    await client.send_prompt_async(session.id, "Count from 1 to 500, printing each number.")
    await asyncio.sleep(0.1)
    ok = await client.interrupt(session.id)
    print("interrupt sent:", ok)

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())