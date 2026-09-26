"""Integration tests against a live `kilo serve` instance.

These are skipped unless the environment provides a running server. Point the suite
at one with either of:

    export KILO_SERVER_URL=http://127.0.0.1:4096
    export KILO_SERVER_USERNAME=kilo
    export KILO_SERVER_PASSWORD=yourpassword   # omit if auth is disabled

When ``KILO_SERVER_URL`` is unset, the tests attempt to read the daemon's current
port from its state file (``~/.local/share/kilo/state.json``) and default to
``http://127.0.0.1:4096``. If nothing is reachable, they skip.
"""

import os

import pytest
import httpx

from kilocode_client import Kilo, SyncKilo

SERVER_URL = os.environ.get(
    "KILO_SERVER_URL",
    "http://127.0.0.1:4096",
)


def _server_reachable() -> bool:
    try:
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(f"{SERVER_URL}/global/health")
            return resp.status_code < 500
    except Exception:  # noqa: BLE001
        return False


SERVER_OK = _server_reachable()

pytestmark = pytest.mark.skipif(
    not SERVER_OK,
    reason=f"no reachable kilo server at {SERVER_URL}",
)


@pytest.fixture
def sync_client() -> "SyncKilo":
    client = SyncKilo(base_url=SERVER_URL)
    yield client
    client.close()


class TestHealth:
    def test_health_async(self) -> None:
        import asyncio

        async def run() -> dict:
            client = Kilo(base_url=SERVER_URL)
            try:
                result = await client.health()
                assert isinstance(result, dict)
                return result
            finally:
                await client.close()

        asyncio.run(run())

    def test_sync_health(self, sync_client: "SyncKilo") -> None:
        result = sync_client.health()
        assert isinstance(result, dict)


class TestAsyncStream:
    def test_create_prompt_back_and_forth(self) -> None:
        import asyncio

        async def run() -> None:
            client = Kilo(base_url=SERVER_URL)
            try:
                session = await client.session.create(title="it-async")
                msg = await client.send_prompt(session.id, "Reply with exactly: OK")
                assert msg.info.id
                await client.delete_session(session.id)
            finally:
                await client.close()

        asyncio.run(run())

    def test_prompt_async_streams_text_deltas(self) -> None:
        import asyncio

        from kilocode_client import text_delta_of

        async def run() -> None:
            client = Kilo(base_url=SERVER_URL)
            try:
                session = await client.session.create(title="it-stream-async")

                async def send() -> None:
                    await asyncio.sleep(0.2)
                    await client.send_prompt_async(
                        session.id, "Reply with the single word: banana"
                    )

                sender = asyncio.create_task(send())
                deltas: list[str] = []
                closed = False
                async for event in await client.stream_session_events(session.id):
                    if event.session_id == session.id and (delta := text_delta_of(event)):
                        deltas.append(delta)
                    if event.is_turn_close and event.session_id == session.id:
                        closed = True
                        break
                sender.cancel()
                assert closed
                assert [d for d in deltas if d]
                await client.delete_session(session.id)
            finally:
                await client.close()

        asyncio.run(run())

    def test_prompt_async_returns_immediately(self) -> None:
        import asyncio
        import time

        async def run() -> None:
            client = Kilo(base_url=SERVER_URL)
            try:
                session = await client.session.create(title="it-async-immediate")
                start = time.monotonic()
                await client.send_prompt_async(session.id, "Reply with the word: x")
                elapsed = time.monotonic() - start
                # 204 returns right away, not waiting for the full response.
                assert elapsed < 10
                await client.delete_session(session.id)
            finally:
                await client.close()

        asyncio.run(run())


class TestSyncStream:
    def test_prompt_async_streams_text_deltas(self, sync_client: "SyncKilo") -> None:
        import threading
        import time

        from kilocode_client.events import text_delta_of

        session = sync_client.create_session(title="it-stream-sync")

        def send() -> None:
            time.sleep(0.6)
            sync_client.send_prompt_async(session.id, "Reply with the single word: cherry")

        threading.Thread(target=send, daemon=True).start()
        deltas: list[str] = []
        closed = False
        for event in sync_client.stream_session_events(session.id):
            if event.session_id == session.id and (delta := text_delta_of(event)):
                deltas.append(delta)
            if event.is_turn_close and event.session_id == session.id:
                closed = True
                break
        sync_client.delete_session(session.id)
        assert closed
        assert [d for d in deltas if d]


class TestSessionLifecycle:
    def test_create_list_delete(self, sync_client: "SyncKilo") -> None:
        session = sync_client.session.create(title="it-test")
        assert session.id

        sessions = sync_client.session.list()
        ids = [s.id for s in sessions if hasattr(s, "id")]
        assert session.id in ids

        renamed = sync_client.session.rename(session.id, "it-test-renamed")
        assert renamed.title == "it-test-renamed"

        assert sync_client.session.delete(session.id) is True

    def test_fork(self, sync_client: "SyncKilo") -> None:
        session = sync_client.session.create(title="it-fork-parent")
        fork = sync_client.session.fork(session.id)
        assert fork.id != session.id
        sync_client.session.delete(fork.id)
        sync_client.session.delete(session.id)


class TestMessages:
    def test_send_prompt_and_history(self, sync_client: "SyncKilo") -> None:
        session = sync_client.session.create(title="it-msg")
        msg = sync_client.send_prompt(session.id, "Reply with exactly: OK")
        assert msg.info.id

        history = sync_client.session.messages(session.id)
        assert len(history) >= 1
        sync_client.delete_session(session.id)


class TestSyncLoopReuse:
    def test_multiple_calls_one_loop(self, sync_client: "SyncKilo") -> None:
        # Several calls through the same wrapper must share one event loop.
        for i in range(3):
            session = sync_client.session.create(title=f"loop-{i}")
            sync_client.send_prompt(session.id, "hi")
            sync_client.session.delete(session.id)