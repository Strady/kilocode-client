"""Parity checks between the async :class:`Kilo` API and its sync :class:`SyncKilo`.

The synchronous wrapper is meant to mirror the async client exactly. If someone
changes a signature in one place and forgets the other, the wrapper silently
accepts/passes different arguments, so this module walks every public method of
both APIs (plus their ``session`` / ``permission`` namespaces) and asserts the
parameter names, kinds, types and defaults line up.

Return types are intentionally not compared: async methods return coroutines /
``AsyncIterator`` where the sync counterparts return plain values / ``Iterator``.
That difference is by design (the async method is a coroutine).
"""

import inspect
from collections.abc import Callable
from typing import Any

from kilocode_client.client import Kilo, _PermissionApi, _SessionApi
from kilocode_client.sync import SyncKilo, _SyncPermissionApi, _SyncSessionApi


def _params(func: Callable[..., Any]) -> list[tuple[str, str, str, str]]:
    sig = inspect.signature(func)
    params: list[tuple[str, str, str, str]] = []
    for name, p in sig.parameters.items():
        if name == "self":
            continue
        ann = p.annotation if p.annotation is not inspect.Parameter.empty else ""
        default = "" if p.default is inspect.Parameter.empty else str(p.default)
        params.append((name, str(p.kind), str(ann), default))
    return params


def _public_async_methods(cls: Any) -> dict[str, Callable[..., Any]]:
    out: dict[str, Callable[..., Any]] = {}
    for name, member in inspect.getmembers(cls):
        if name.startswith("_") or name.endswith("__"):
            continue
        if not inspect.iscoroutinefunction(member):
            continue
        out[name] = member
    return out


def _assert_parity(async_method: Any, sync_method: Any, label: str) -> None:
    assert _params(async_method) == _params(sync_method), (
        f"signature drift for {label}: async={_params(async_method)} sync={_params(sync_method)}"
    )


class TestSyncParity:
    def test_top_level_methods(self) -> None:
        for name, async_method in _public_async_methods(Kilo).items():
            sync_method = getattr(SyncKilo, name, None)
            assert sync_method is not None, f"SyncKilo missing method {name}"
            _assert_parity(async_method, sync_method, f"Kilo.{name}")

    def test_session_namespace(self) -> None:
        for name, async_method in _public_async_methods(_SessionApi).items():
            sync_method = getattr(_SyncSessionApi, name, None)
            assert sync_method is not None, f"_SyncSessionApi missing method {name}"
            _assert_parity(async_method, sync_method, f"session.{name}")

    def test_permission_namespace(self) -> None:
        for name, async_method in _public_async_methods(_PermissionApi).items():
            sync_method = getattr(_SyncPermissionApi, name, None)
            assert sync_method is not None, f"_SyncPermissionApi missing method {name}"
            _assert_parity(async_method, sync_method, f"permission.{name}")
