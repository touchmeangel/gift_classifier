import pytest

from gifts_collect.providers.portals.client import PortalsAPI

@pytest.mark.asyncio
async def test_collections_without_credentials(monkeypatch):
    client = PortalsAPI()
    calls = {}

    async def fake_send(url, params, token):
        calls["token"] = token
        calls["params"] = params
        return {
            "collections": [],
            "floor_changes": {},
            "volume_changes": {},
        }

    monkeypatch.setattr(client, "_send", fake_send)

    async with client:
        result = await client.collections()

    assert result.collections == []
    assert calls["token"] is None
    assert calls["params"] == {
        "offset": 0,
        "limit": 150,
        "favorites_only": "false",
    }