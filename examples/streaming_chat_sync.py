"""Blocking (thread-based) streaming of a session's events.

Mirrors :mod:`streaming_chat` but uses :class:`SyncKilo`, whose event stream is a
plain iterable driven by a background thread. Subscribe before sending, then use
:meth:`SyncKilo.send_prompt_async` so you can see text deltas as they stream in.

Run against a live server, e.g.:

    kilo serve --port 4096 &
    python examples/streaming_chat_sync.py
"""

import threading
import time

from kilocode_client import SyncKilo, text_delta_of


def main(base_url: str = "http://127.0.0.1:4096") -> None:
    client = SyncKilo(base_url=base_url)
    session = client.create_session(title="streaming-chat-sync-example")

    def send() -> None:
        time.sleep(0.2)
        client.send_prompt_async(session.id, "List three Python web frameworks, then stop.")

    threading.Thread(target=send, daemon=True).start()

    for event in client.stream_session_events(session.id):
        delta = text_delta_of(event)
        if delta:
            print(delta, end="", flush=True)
        if event.is_turn_close:
            reason = event.turn_close_reason
            print(f"\n--- turn closed ({reason}) ---", flush=True)
            break

    client.close()


if __name__ == "__main__":
    main()
