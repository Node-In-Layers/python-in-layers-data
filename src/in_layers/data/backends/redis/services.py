"""Redis backend implementation for InLayers models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from box import Box
from in_layers.core.models.protocols import (
    InLayersModel,
    ModelSearch,
    ModelSearchResult,
    PrimaryKeyType,
)

from in_layers.data.protocols import RedisBackendConfig

from .libs import (
    create_connection_url,
    dump_json,
    from_redis_search_response,
    get_key,
    get_key_prefix_for_model,
    get_search_document_key,
    get_search_document_prefix,
    get_search_index_name,
    load_json,
    normalize_for_storage,
    to_redis_search_hash_document,
    to_redis_search_limit_args,
    to_redis_search_query,
    to_redis_search_schema_args,
    to_redis_search_sort_args,
)


class RedisBackend:
    """Redis backend implementation."""

    def __init__(self, context, config: RedisBackendConfig):
        self.__context = context
        self.__config = config
        self.__client: Any = None
        self.__index_names_ready: set[str] = set()
        self.__schema_fields_by_index_name: dict[str, set[str]] = {}

    @staticmethod
    def create_unique_connection_string(config: RedisBackendConfig) -> str:
        config_dict = {
            "host": getattr(config, "host", None),
            "port": getattr(config, "port", None),
            "username": getattr(config, "username", None),
            "password": getattr(config, "password", None),
        }
        redis_stack = getattr(config, "redis_stack", True) is not False
        return f"{create_connection_url(config_dict)}|stack={redis_stack}"

    def __get_config_value(self, key: str, default_value: Any = None) -> Any:
        if key in self.__config:
            return self.__config[key]
        return default_value

    def __use_redis_stack(self) -> bool:
        return self.__get_config_value("redis_stack", True) is not False

    def __connect(self) -> None:
        injected_client = self.__get_config_value("client")
        if injected_client is not None:
            self.__client = injected_client
            return

        redis_lib = self.__get_config_value("redis")
        if redis_lib is None:
            import redis as redis_lib  # pragma: no cover # noqa: PLC0415

        url = create_connection_url(
            {
                "host": self.__get_config_value("host"),
                "port": self.__get_config_value("port"),
                "username": self.__get_config_value("username"),
                "password": self.__get_config_value("password"),
            }
        )

        from_url = getattr(redis_lib, "from_url", None)
        if callable(from_url):
            self.__client = from_url(url, decode_responses=True)
            return

        redis_cls = getattr(redis_lib, "Redis", None)
        if redis_cls is None or not hasattr(redis_cls, "from_url"):
            raise ValueError("Redis library must expose from_url or Redis.from_url")

        self.__client = redis_cls.from_url(url, decode_responses=True)

    def __disconnect(self) -> None:
        if self.__client is None:
            return
        close = getattr(self.__client, "close", None)
        if callable(close):
            close()
        self.__client = None
        self.__index_names_ready = set()
        self.__schema_fields_by_index_name = {}

    def __ensure_connected(self) -> None:
        if self.__client is None:
            self.__connect()

    @staticmethod
    def __to_schema_entries(schema_args: list[str]) -> list[list[str]]:
        entries: list[list[str]] = []
        index = 0
        while index < len(schema_args):
            field_type = schema_args[index + 1]
            if field_type == "TEXT":
                entries.append(schema_args[index : index + 2])
                index += 2
                continue
            if index + 2 < len(schema_args) and schema_args[index + 2] == "SORTABLE":
                entries.append(schema_args[index : index + 3])
                index += 3
                continue
            entries.append(schema_args[index : index + 2])
            index += 2
        return entries

    def __ensure_stack_index(
        self, model: InLayersModel, sample_data: Mapping[str, Any] | None = None
    ) -> str:
        if self.__use_redis_stack() is False:
            raise ValueError("Redis Stack search is required for the Redis backend")

        key_prefix = get_key_prefix_for_model(model)
        index_name = get_search_index_name(key_prefix)

        schema_args = to_redis_search_schema_args(model, sample_data)
        if len(schema_args) < 1:
            self.__index_names_ready.add(index_name)
            return index_name
        schema_entries = self.__to_schema_entries(schema_args)
        schema_field_names = {entry[0] for entry in schema_entries}

        if index_name in self.__index_names_ready:
            known_field_names = self.__schema_fields_by_index_name.setdefault(
                index_name, set()
            )
            missing_entries = [
                entry for entry in schema_entries if entry[0] not in known_field_names
            ]
            if missing_entries:
                self.__client.execute_command(
                    "FT.ALTER",
                    index_name,
                    "SCHEMA",
                    "ADD",
                    *[item for entry in missing_entries for item in entry],
                )
                known_field_names.update(entry[0] for entry in missing_entries)
            return index_name

        create_args = [
            "FT.CREATE",
            index_name,
            "ON",
            "HASH",
            "PREFIX",
            "1",
            get_search_document_prefix(key_prefix),
            "SCHEMA",
            *schema_args,
        ]
        try:
            self.__client.execute_command(*create_args)
        except Exception as error:
            message = str(error)
            if (
                "Index already exists" not in message
                and "Duplicate index name" not in message
            ):
                raise

        self.__index_names_ready.add(index_name)
        self.__schema_fields_by_index_name[index_name] = schema_field_names
        return index_name

    def __set_search_document(
        self, model: InLayersModel, data: Mapping[str, Any], primary_key: PrimaryKeyType
    ) -> None:
        key_prefix = get_key_prefix_for_model(model)
        self.__ensure_stack_index(model, data)
        self.__client.hset(
            get_search_document_key(key_prefix, primary_key),
            mapping=to_redis_search_hash_document(model, data),
        )

    def get_raw_client(self) -> Any:
        self.__ensure_connected()
        return self.__client

    def get_backend_name(self) -> str:
        return "redis"

    def create(self, model: InLayersModel, data: Mapping) -> Mapping:
        self.__ensure_connected()

        payload = normalize_for_storage(dict(data))
        pk_name = model.get_primary_key_name()
        pk_value = payload.get(pk_name)
        if pk_value is None:
            pk_value = str(uuid4())
            payload[pk_name] = pk_value

        key_prefix = get_key_prefix_for_model(model)
        key = get_key(key_prefix, pk_value)
        self.__client.set(key, dump_json(payload))
        self.__set_search_document(model, payload, pk_value)
        return payload

    def retrieve(self, model: InLayersModel, id: PrimaryKeyType) -> Mapping | None:
        self.__ensure_connected()

        key_prefix = get_key_prefix_for_model(model)
        key = get_key(key_prefix, id)
        value = self.__client.get(key)
        loaded = load_json(value)
        if loaded is None:
            return None
        return loaded

    def update(
        self, model: InLayersModel, id: PrimaryKeyType, data: Mapping
    ) -> Mapping:
        self.__ensure_connected()

        existing = self.retrieve(model, id)
        if existing is None:
            raise KeyError(f"Instance with id {id!r} not found")

        payload = dict(existing)
        payload.update(normalize_for_storage(dict(data)))
        payload[model.get_primary_key_name()] = id

        key_prefix = get_key_prefix_for_model(model)
        key = get_key(key_prefix, id)
        self.__client.set(key, dump_json(payload))
        self.__set_search_document(model, payload, id)
        return payload

    def delete(self, model: InLayersModel, id: PrimaryKeyType) -> None:
        self.__ensure_connected()

        key_prefix = get_key_prefix_for_model(model)
        self.__client.delete(
            get_key(key_prefix, id), get_search_document_key(key_prefix, id)
        )

    def search(self, model: InLayersModel, query: ModelSearch) -> ModelSearchResult:
        self.__ensure_connected()

        index_name = self.__ensure_stack_index(model)
        redis_query = to_redis_search_query(query)
        response = self.__client.execute_command(
            "FT.SEARCH",
            index_name,
            redis_query,
            "RETURN",
            "1",
            "__raw",
            *to_redis_search_sort_args(model, query),
            *to_redis_search_limit_args(query),
        )
        result = from_redis_search_response(response)
        return Box(instances=result.instances, page=query.page)

    def bulk_insert(self, model: InLayersModel, data: list[Mapping]) -> None:
        self.__ensure_connected()
        if len(data) < 1:
            return

        payloads: list[dict[str, Any]] = []
        pk_name = model.get_primary_key_name()
        for item in data:
            payload = normalize_for_storage(dict(item))
            pk_value = payload.get(pk_name)
            if pk_value is None:
                pk_value = str(uuid4())
                payload[pk_name] = pk_value
            payloads.append(payload)

        self.__ensure_stack_index(model, payloads[0])
        key_prefix = get_key_prefix_for_model(model)
        pipeline = self.__client.pipeline()
        for payload in payloads:
            primary_key = payload[pk_name]
            pipeline.set(get_key(key_prefix, primary_key), dump_json(payload))
            pipeline.hset(
                get_search_document_key(key_prefix, primary_key),
                mapping=to_redis_search_hash_document(model, payload),
            )
        pipeline.execute()

    def bulk_delete(self, model: InLayersModel, ids: list[PrimaryKeyType]) -> None:
        self.__ensure_connected()
        if len(ids) < 1:
            return

        key_prefix = get_key_prefix_for_model(model)
        keys = [get_key(key_prefix, id) for id in ids]
        search_keys = [get_search_document_key(key_prefix, id) for id in ids]
        self.__client.delete(*keys, *search_keys)

    def dispose(self) -> None:
        self.__disconnect()
