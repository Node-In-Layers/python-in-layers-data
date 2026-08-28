"""Unit tests for Redis backend helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from in_layers.core.models.backends import MemoryBackend
from in_layers.core.models.libs import model
from in_layers.core.models.protocols import SortOrder
from in_layers.core.models.query import query_builder
from in_layers.core.models.services import create_in_layers_model
from in_layers.data.backends.redis.libs import (
    create_connection_url,
    from_redis_search_response,
    get_key,
    get_key_prefix_for_model,
    get_search_document_key,
    get_search_document_prefix,
    get_search_index_name,
    to_redis_search_hash_document,
    to_redis_search_limit_args,
    to_redis_search_query,
    to_redis_search_schema_args,
    to_redis_search_sort_args,
)


@model(domain="functional-models-orm-redis", plural_name="RedisModels")
class RedisModel(BaseModel):
    id: str
    name: str
    age: int
    active: bool
    created_at: datetime | None = None


def _create_model():
    return create_in_layers_model(RedisModel, MemoryBackend())


class TestKeyHelpers:
    """Tests for key and name helpers."""

    def test_should_create_expected_model_prefix(self):
        actual = get_key_prefix_for_model(_create_model())
        expected = "functional-models-orm-redis-redis-models"
        assert actual == expected

    def test_should_create_expected_key_values(self):
        prefix = "my-prefix"
        assert get_key(prefix, "abc") == "my-prefix:abc"
        assert get_search_index_name(prefix) == "idx:my-prefix"
        assert get_search_document_prefix(prefix) == "searchdoc:my-prefix:"
        assert get_search_document_key(prefix, "abc") == "searchdoc:my-prefix:abc"

    def test_should_create_expected_connection_url(self):
        actual = create_connection_url(
            {
                "host": "localhost",
                "port": 6380,
                "username": "user",
                "password": "pass",
            }
        )
        assert actual == "redis://user:pass@localhost:6380"


class TestSearchHelpers:
    """Tests for Redis Stack query helpers."""

    def test_should_return_wildcard_for_empty_query(self):
        actual = to_redis_search_query(query_builder().compile())
        assert actual == "*"

    def test_should_build_or_string_query(self):
        search = (
            query_builder()
            .property("name", "alpha")
            .or_()
            .property("name", "beta")
            .compile()
        )

        actual = to_redis_search_query(search)

        assert actual == "(@name__tag:{alpha})|(@name__tag:{beta})"

    def test_should_build_datetime_span_query(self):
        start = datetime(2020, 2, 1, tzinfo=UTC)
        end = datetime(2020, 5, 1, tzinfo=UTC)
        search = (
            query_builder()
            .dates_after("created_at", start, equal_to_and_after=True)
            .and_()
            .dates_before("created_at", end, equal_to_and_before=False)
            .compile()
        )

        actual = to_redis_search_query(search)

        assert "@created_at__ts:[" in actual
        assert "+inf]" in actual
        assert "@created_at__ts:[-inf (" in actual

    def test_should_build_sort_and_limit_args(self):
        model = _create_model()
        search = query_builder().take(25).sort("created_at", SortOrder.dsc).compile()

        sort_actual = to_redis_search_sort_args(model, search)
        limit_actual = to_redis_search_limit_args(search)

        assert sort_actual == ["SORTBY", "created_at__ts", "DESC"]
        assert limit_actual == ["LIMIT", "0", "25"]


class TestSchemaAndHashDocs:
    """Tests for schema and hash document helpers."""

    def test_should_create_schema_args_from_model_annotations(self):
        actual = to_redis_search_schema_args(_create_model())

        assert "id__tag" in actual
        assert "name__text" in actual
        assert "age" in actual
        assert "active" in actual
        assert "created_at__ts" in actual

    def test_should_create_hash_document_with_typed_fields(self):
        actual = to_redis_search_hash_document(
            _create_model(),
            {
                "id": "abc",
                "name": "Alpha",
                "age": 10,
                "active": True,
                "created_at": datetime(2020, 2, 1, tzinfo=UTC),
            },
        )

        assert "__raw" in actual
        assert actual["id__tag"] == "abc"
        assert actual["name__text"] == "Alpha"
        assert actual["age"] == 10.0
        assert actual["active"] == "true"
        assert "created_at__ts" in actual


class TestSearchResponseParsing:
    """Tests for RediSearch response parsing."""

    def test_should_parse_search_response_instances(self):
        response = [
            1,
            "searchdoc:functional-models-orm-redis-redis-models:abc",
            ["__raw", '{"id":"abc","name":"Alpha","age":10,"active":true}'],
        ]

        actual = from_redis_search_response(response)

        assert len(actual.instances) == 1
        assert actual.instances[0]["id"] == "abc"
        assert actual.instances[0]["name"] == "Alpha"
