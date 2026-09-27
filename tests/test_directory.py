"""Unit tests for the ``directory`` semantics (no server required).

Verifies that a client-level ``directory`` goes to both the ``directory`` query
param and the ``x-kilo-directory`` header, while a per-call ``directory`` applies
only to that request (query + a per-request header override when it differs).
"""

import asyncio
import base64
from typing import Any

from kilocode_client import Kilo


class _FakeResponse:
    status_code = 200
    content = b"[{}]"

    def json(self) -> Any:
        return [{"id": "p"}]


def _b64(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


class TestDirectory:
    def test_client_level_directory_sets_header_and_query(self) -> None:
        async def run() -> None:
            captured: list[dict[str, Any]] = []

            async def fake_request(method: str, path: str, **kwargs: Any) -> _FakeResponse:
                captured.append(kwargs)
                return _FakeResponse()

            client = Kilo(directory="/client")
            assert client._http.headers.get("x-kilo-directory") == _b64("/client")

            client._http.request = fake_request  # ty: ignore[invalid-assignment]
            await client.list_providers()
            assert captured[0]["params"] == {"directory": "/client"}
            assert captured[0]["headers"] is None

        asyncio.run(run())

    def test_call_level_directory_overrides_query_and_header(self) -> None:
        async def run() -> None:
            captured: list[dict[str, Any]] = []

            async def fake_request(method: str, path: str, **kwargs: Any) -> _FakeResponse:
                captured.append(kwargs)
                return _FakeResponse()

            client = Kilo(directory="/client")
            client._http.request = fake_request  # ty: ignore[invalid-assignment]

            await client.list_models(directory="/call")
            assert captured[0]["params"] == {"directory": "/call"}
            assert captured[0]["headers"] == {"x-kilo-directory": _b64("/call")}

        asyncio.run(run())

    def test_call_level_directory_without_client_directory(self) -> None:
        async def run() -> None:
            captured: list[dict[str, Any]] = []

            async def fake_request(method: str, path: str, **kwargs: Any) -> _FakeResponse:
                captured.append(kwargs)
                return _FakeResponse()

            client = Kilo()
            client._http.request = fake_request  # ty: ignore[invalid-assignment]

            await client.list_providers(directory="/call")
            assert captured[0]["params"] == {"directory": "/call"}
            assert captured[0]["headers"] == {"x-kilo-directory": _b64("/call")}

        asyncio.run(run())

    def test_same_directory_does_not_override_header(self) -> None:
        async def run() -> None:
            captured: list[dict[str, Any]] = []

            async def fake_request(method: str, path: str, **kwargs: Any) -> _FakeResponse:
                captured.append(kwargs)
                return _FakeResponse()

            client = Kilo(directory="/same")
            client._http.request = fake_request  # ty: ignore[invalid-assignment]

            await client.list_models(directory="/same")
            assert captured[0]["params"] == {"directory": "/same"}
            assert captured[0]["headers"] is None

        asyncio.run(run())
