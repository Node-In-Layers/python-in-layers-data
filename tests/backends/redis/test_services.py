"""Unit tests for Redis backend services."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from box import Box
from pydantic import BaseModel

from in_layers.core.models.backends import MemoryBackend
from in_layers.core.models.libs import model
from in_layers.core.models.protocols import SortOrder
from in_layers.core.models.query import PropertyOptions, query_builder
from in_layers.core.models.services import create_in_layers_model
from in_layers.data.backends.redis.services import RedisBackend
from in_layers.data.protocols import SupportedBackend


@model(domain="functional-models-orm-redis", plural_name="RedisModels")
class RedisModel(BaseModel):
    id: str | None = None
    name: str
    age: int
    active: bool = True
    created_at: datetime | None = None


def _create_model():
    return create_in_layers_model(RedisModel, MemoryBackend())


def _create_context():
    return Box(
        config=Box(system_name="redis-tests", environment="test"),
        log=MagicMock(),
    )


def _create_config(client: Any | None = None, redis_stack: bool = True):
    return Box(
        type=SupportedBackend.Redis,
        host="localhost",
        port=6379,
        username=None,
        password=None,
        redis_stack=redis_stack,
        redis=None,
        client=client,
    )


class _FakePipeline:
    def __init__(self, client):
        self._client = client
        self._operations: list[tuple[str, Any, Any]] = []

    def set(self, key: str, value: str):
        self._operations.append(("set", key, value))
        return self

    def hset(self, key: str, mapping: dict[str, Any]):
        self._operations.append(("hset", key, dict(mapping)))
        return self

    def execute(self):
        for operation, key, value in self._operations:
            if operation == "set":
                self._client.set(key, value)
                continue
            self._client.hset(key, mapping=value)
        return ["OK"] * len(self._operations)


class _FakeRedisClient:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.hashes: dict[str, dict[str, Any]] = {}
        self.closed = False
        self.commands: list[tuple[Any, ...]] = []
        self.search_response: list[Any] = [0]

    def set(self, key: str, value: str):
        self.values[key] = value
        return True

    def get(self, key: str):
        return self.values.get(key)

    def hset(self, key: str, mapping: dict[str, Any]):
        self.hashes[key] = dict(mapping)
        return 1

    def delete(self, *keys: str):
        for key in keys:
            self.values.pop(key, None)
            self.hashes.pop(key, None)
        return len(keys)

    def execute_command(self, *args):
        self.commands.append(args)
        if args[0] == "FT.SEARCH":
            return self.search_response
        return "OK"

    def pipeline(self):
        return _FakePipeline(self)

    def scan_iter(self, match: str):
        prefix = match[:-1] if match.endswith("*") else match
        for key in sorted(self.values):
            if key.startswith(prefix):
                yield key

    def close(self):
        self.closed = True


class TestCreateUniqueConnectionString:
    """Tests for create_unique_connection_string."""

    def test_should_include_stack_mode(self):
        config = _create_config()

        actual = RedisBackend.create_unique_connection_string(config)

        assert actual == "redis://localhost:6379|stack=True"


class TestCreateAndRetrieve:
    """Tests for create and retrieve methods."""

    def test_should_create_item_and_search_document(self):
        client = _FakeRedisClient()
        backend = RedisBackend(_create_context(), _create_config(client=client))
        model_instance = _create_model()
        payload = {
            "name": "Alpha",
            "age": 10,
            "active": True,
            "created_at": datetime(2020, 2, 1, tzinfo=UTC),
        }

        actual = backend.create(model_instance, payload)

        assert actual["id"] is not None
        assert len(client.values) == 1
        assert len(client.hashes) == 1
        assert client.commands[0][0] == "FT.CREATE"

    def test_should_retrieve_created_item(self):
        client = _FakeRedisClient()
        backend = RedisBackend(_create_context(), _create_config(client=client))
        model_instance = _create_model()
        created = backend.create(
            model_instance,
            {
                "id": "abc",
                "name": "Alpha",
                "age": 10,
                "active": True,
            },
        )

        actual = backend.retrieve(model_instance, created["id"])

        assert actual is not None
        assert actual["id"] == "abc"
        assert actual["name"] == "Alpha"


class TestUpdateAndDelete:
    """Tests for update and delete methods."""

    def test_should_merge_existing_item_on_update(self):
        client = _FakeRedisClient()
        backend = RedisBackend(_create_context(), _create_config(client=client))
        model_instance = _create_model()
        backend.create(
            model_instance,
            {
                "id": "abc",
                "name": "Alpha",
                "age": 10,
                "active": True,
            },
        )

        actual = backend.update(model_instance, "abc", {"name": "Beta"})

        assert actual["id"] == "abc"
        assert actual["name"] == "Beta"
        assert actual["age"] == 10

    def test_should_delete_data_and_search_keys(self):
        client = _FakeRedisClient()
        backend = RedisBackend(_create_context(), _create_config(client=client))
        model_instance = _create_model()
        backend.create(
            model_instance,
            {
                "id": "abc",
                "name": "Alpha",
                "age": 10,
                "active": True,
            },
        )

        backend.delete(model_instance, "abc")

        assert client.values == {}
        assert client.hashes == {}


class TestSearch:
    """Tests for search method."""

    def test_should_execute_redis_stack_search(self):
        client = _FakeRedisClient()
        client.search_response = [
            1,
            "searchdoc:functional-models-orm-redis-redis-models:abc",
            ["__raw", '{"id":"abc","name":"Alpha","age":10,"active":true}'],
        ]
        backend = RedisBackend(_create_context(), _create_config(client=client))
        model_instance = _create_model()
        search = (
            query_builder()
            .property("name", "Alpha", PropertyOptions(starts_with=True))
            .sort("created_at", SortOrder.dsc)
            .take(5)
            .compile()
        )

        actual = backend.search(model_instance, search)

        assert len(actual.instances) == 1
        assert actual.instances[0]["id"] == "abc"
        assert client.commands[-1][0] == "FT.SEARCH"
        assert "SORTBY" in client.commands[-1]
        assert "LIMIT" in client.commands[-1]

    def test_should_require_redis_stack_for_search(self):
        client = _FakeRedisClient()
        backend = RedisBackend(
            _create_context(), _create_config(client=client, redis_stack=False)
        )
        model_instance = _create_model()

        with pytest.raises(
            ValueError, match="Redis Stack search is required for the Redis backend"
        ):
            backend.search(model_instance, query_builder().compile())


class TestCount:
    """Tests for count method."""

    def test_should_count_model_records_by_key_prefix(self):
        client = _FakeRedisClient()
        backend = RedisBackend(_create_context(), _create_config(client=client))
        model_instance = _create_model()
        backend.bulk_insert(
            model_instance,
            [
                {"id": "a", "name": "Alpha", "age": 10, "active": True},
                {"id": "b", "name": "Beta", "age": 11, "active": False},
            ],
        )

        actual = backend.count(model_instance)

        assert actual == 2


class TestBulkOperations:
    """Tests for bulk insert and delete."""

    def test_should_bulk_insert_and_generate_ids(self):
        client = _FakeRedisClient()
        backend = RedisBackend(_create_context(), _create_config(client=client))
        model_instance = _create_model()

        backend.bulk_insert(
            model_instance,
            [
                {"name": "Alpha", "age": 10, "active": True},
                {"name": "Beta", "age": 11, "active": False},
            ],
        )

        assert len(client.values) == 2
        assert len(client.hashes) == 2
        assert client.commands[0][0] == "FT.CREATE"

    def test_should_bulk_delete_multiple_ids(self):
        client = _FakeRedisClient()
        backend = RedisBackend(_create_context(), _create_config(client=client))
        model_instance = _create_model()
        backend.bulk_insert(
            model_instance,
            [
                {"id": "a", "name": "Alpha", "age": 10, "active": True},
                {"id": "b", "name": "Beta", "age": 11, "active": False},
            ],
        )

        backend.bulk_delete(model_instance, ["a", "b"])

        assert client.values == {}
        assert client.hashes == {}


class TestRawClientAndDispose:
    """Tests for raw client access and cleanup."""

    def test_should_return_raw_client(self):
        client = _FakeRedisClient()
        backend = RedisBackend(_create_context(), _create_config(client=client))

        actual = backend.get_raw_client()

        assert actual is client

    def test_should_close_client_on_dispose(self):
        client = _FakeRedisClient()
        backend = RedisBackend(_create_context(), _create_config(client=client))

        backend.get_raw_client()
        backend.dispose()

        assert client.closed is True
