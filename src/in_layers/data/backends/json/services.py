"""JSON file backend implementation for InLayers models."""

from __future__ import annotations

from collections.abc import Mapping
from threading import RLock, Timer
from typing import Any
from uuid import uuid4

from box import Box
from in_layers.core.models.backends import (
    _apply_sort,
    _apply_take,
    _matches_query_tokens,
)
from in_layers.core.models.protocols import (
    InLayersModel,
    ModelSearch,
    ModelSearchResult,
    PrimaryKeyType,
)

from in_layers.data.protocols import JsonBackendConfig

from .libs import (
    JsonFilesystem,
    get_collection_name_for_model,
    load_collection_from_directory,
    load_database_from_file,
    save_collection_to_directory,
    save_database_to_file,
    with_file_lock,
)

PendingOperation = tuple[str, Any]


class JsonBackend:
    """JSON backend with file and directory persistence modes."""

    def __init__(self, context, config: JsonBackendConfig):
        self.__context = context
        self.__config = config
        self.__fs = self.__get_config_value("fs", JsonFilesystem())
        self.__get_collection_name = self.__get_config_value(
            "get_collection_name_for_model", get_collection_name_for_model
        )
        self.__lock = RLock()
        self.__collections: dict[str, dict[str, dict[str, Any]]] = {}
        self.__loaded_database = False
        self.__loaded_collections: set[str] = set()
        self.__dirty_database = False
        self.__dirty_collections: set[str] = set()
        self.__pending_database_ops: list[PendingOperation] = []
        self.__pending_collection_ops: dict[str, list[PendingOperation]] = {}
        self.__flush_timer: Timer | None = None

    @staticmethod
    def create_unique_connection_string(config: JsonBackendConfig) -> str:
        directory_mode = getattr(config, "directory_mode", False) is True
        return f"json://{config.file_path}|directory={directory_mode}"

    def __get_config_value(self, key: str, default_value: Any = None) -> Any:
        if key in self.__config:
            value = self.__config[key]
            if value is not None:
                return value
        return default_value

    def __use_directory_mode(self) -> bool:
        return self.__get_config_value("directory_mode", False) is True

    def __file_path(self) -> str:
        return self.__config.file_path

    def __write_buffer_ms(self) -> int:
        return int(self.__get_config_value("write_buffer_ms", 10) or 0)

    def __get_collection_name_for_model(self, model: InLayersModel) -> str:
        return self.__get_collection_name(model)

    def __get_collection_store(self, collection_name: str) -> dict[str, dict[str, Any]]:
        store = self.__collections.get(collection_name)
        if store is None:
            store = {}
            self.__collections[collection_name] = store
        return store

    def __load_collection_from_raw_database(
        self, model: InLayersModel, raw_database: Mapping[str, Any]
    ) -> dict[str, dict[str, Any]]:
        collection_name = self.__get_collection_name_for_model(model)
        raw_collection = raw_database.get(collection_name, {}) if raw_database else {}
        if not isinstance(raw_collection, Mapping):
            return {}
        return {
            str(primary_key): dict(record)
            for primary_key, record in raw_collection.items()
            if isinstance(record, Mapping)
        }

    def __load_database_if_needed(self) -> None:
        if self.__loaded_database or self.__use_directory_mode():
            return
        raw_database = load_database_from_file(self.__fs, self.__file_path())
        self.__collections = {}
        for collection_name, raw_collection in raw_database.items():
            if not isinstance(raw_collection, Mapping):
                continue
            self.__collections[collection_name] = {
                str(primary_key): dict(record)
                for primary_key, record in raw_collection.items()
                if isinstance(record, Mapping)
            }
        self.__loaded_database = True

    def __ensure_initialized(self, model: InLayersModel) -> None:
        collection_name = self.__get_collection_name_for_model(model)
        if self.__use_directory_mode() is False:
            self.__load_database_if_needed()
            self.__get_collection_store(collection_name)
            return

        if collection_name in self.__loaded_collections:
            return
        raw_collection_wrapper = load_collection_from_directory(
            self.__fs, self.__file_path(), collection_name
        )
        self.__collections[collection_name] = self.__load_collection_from_raw_database(
            model, raw_collection_wrapper
        )
        self.__loaded_collections.add(collection_name)

    def __get_collection(self, model: InLayersModel) -> dict[str, dict[str, Any]]:
        self.__ensure_initialized(model)
        collection_name = self.__get_collection_name_for_model(model)
        return self.__get_collection_store(collection_name)

    def __record_key(self, primary_key: PrimaryKeyType) -> str:
        return str(primary_key)

    def __apply_upsert(
        self,
        collection: dict[str, dict[str, Any]],
        record_key: str,
        payload: Mapping[str, Any],
    ) -> None:
        collection[record_key] = dict(payload)

    def __apply_delete(
        self, collection: dict[str, dict[str, Any]], record_key: str
    ) -> None:
        collection.pop(record_key, None)

    def __apply_pending_operation(
        self,
        collection: dict[str, dict[str, Any]],
        operation: PendingOperation,
    ) -> None:
        operation_type, payload = operation
        if operation_type == "upsert":
            record_key, data = payload
            self.__apply_upsert(collection, record_key, data)
            return
        if operation_type == "delete":
            self.__apply_delete(collection, payload)
            return
        if operation_type == "bulk_upsert":
            for record_key, data in payload:
                self.__apply_upsert(collection, record_key, data)
            return
        if operation_type == "bulk_delete":
            for record_key in payload:
                self.__apply_delete(collection, record_key)
            return
        raise ValueError(f"Unknown operation type: {operation_type}")

    def __schedule_flush_locked(self) -> None:
        if self.__flush_timer is not None:
            return
        delay_ms = max(0, self.__write_buffer_ms())
        if delay_ms == 0:
            self.__flush_pending_writes_locked()
            return
        timer = Timer(delay_ms / 1000, self.__flush_from_timer)
        timer.daemon = True
        self.__flush_timer = timer
        timer.start()

    def __flush_from_timer(self) -> None:
        with self.__lock:
            self.__flush_timer = None
            self.__flush_pending_writes_locked()

    def __cancel_flush_timer_locked(self) -> None:
        if self.__flush_timer is None:
            return
        self.__flush_timer.cancel()
        self.__flush_timer = None

    def __serialize_collection(
        self, collection: Mapping[str, Mapping[str, Any]], collection_name: str
    ) -> dict[str, dict[str, dict[str, Any]]]:
        return {
            collection_name: {
                str(primary_key): dict(record)
                for primary_key, record in collection.items()
            }
        }

    def __flush_database_locked(self) -> None:
        if self.__dirty_database is False:
            return

        pending_ops = list(self.__pending_database_ops)
        self.__pending_database_ops = []
        self.__dirty_database = False

        file_path = self.__file_path()
        lock_path = f"{file_path}.lock"

        def _flush() -> None:
            raw_database = load_database_from_file(self.__fs, file_path)
            fresh_collections: dict[str, dict[str, dict[str, Any]]] = {}

            for collection_name, raw_collection in raw_database.items():
                if not isinstance(raw_collection, Mapping):
                    continue
                fresh_collections[collection_name] = {
                    str(primary_key): dict(record)
                    for primary_key, record in raw_collection.items()
                    if isinstance(record, Mapping)
                }

            for operation_type, payload in pending_ops:
                collection_name, inner_payload = payload
                collection = fresh_collections.setdefault(collection_name, {})
                self.__apply_pending_operation(
                    collection, (operation_type, inner_payload)
                )

            save_database_to_file(self.__fs, file_path, fresh_collections)
            self.__collections = fresh_collections
            self.__loaded_database = True

        with_file_lock(self.__fs, lock_path, _flush)

    def __flush_directory_collections_locked(self) -> None:
        if len(self.__dirty_collections) < 1:
            return

        dirty_collection_names = list(self.__dirty_collections)
        self.__dirty_collections = set()

        for collection_name in dirty_collection_names:
            pending_ops = list(self.__pending_collection_ops.get(collection_name, []))
            self.__pending_collection_ops[collection_name] = []

            collection_path = f"{self.__file_path()}/{collection_name}.json"
            lock_path = f"{collection_path}.lock"

            def _flush_collection(
                target_collection_name: str = collection_name,
                ops: list[PendingOperation] = pending_ops,
            ) -> None:
                raw_collection_wrapper = load_collection_from_directory(
                    self.__fs, self.__file_path(), target_collection_name
                )
                fresh_collection = {}
                raw_collection = raw_collection_wrapper.get(target_collection_name, {})
                if isinstance(raw_collection, Mapping):
                    fresh_collection = {
                        str(primary_key): dict(record)
                        for primary_key, record in raw_collection.items()
                        if isinstance(record, Mapping)
                    }
                for operation in ops:
                    self.__apply_pending_operation(fresh_collection, operation)
                save_collection_to_directory(
                    self.__fs,
                    self.__file_path(),
                    target_collection_name,
                    self.__serialize_collection(
                        fresh_collection,
                        target_collection_name,
                    ),
                )
                self.__collections[target_collection_name] = fresh_collection
                self.__loaded_collections.add(target_collection_name)

            with_file_lock(self.__fs, lock_path, _flush_collection)

    def __flush_pending_writes_locked(self) -> None:
        self.__cancel_flush_timer_locked()
        if self.__use_directory_mode():
            self.__flush_directory_collections_locked()
            return
        self.__flush_database_locked()

    def __enqueue_database_operation(
        self, collection_name: str, operation: PendingOperation
    ) -> None:
        self.__pending_database_ops.append(
            (operation[0], (collection_name, operation[1]))
        )
        self.__dirty_database = True
        self.__schedule_flush_locked()

    def __enqueue_collection_operation(
        self, collection_name: str, operation: PendingOperation
    ) -> None:
        self.__pending_collection_ops.setdefault(collection_name, []).append(operation)
        self.__dirty_collections.add(collection_name)
        self.__schedule_flush_locked()

    def __queue_operation(
        self, collection_name: str, operation: PendingOperation
    ) -> None:
        if self.__use_directory_mode():
            self.__enqueue_collection_operation(collection_name, operation)
            return
        self.__enqueue_database_operation(collection_name, operation)

    def get_raw_client(self) -> Any:
        return self.__fs

    def get_backend_name(self) -> str:
        return "json"

    def create(self, model: InLayersModel, data: Mapping) -> Mapping:
        with self.__lock:
            collection_name = self.__get_collection_name_for_model(model)
            collection = self.__get_collection(model)
            payload = dict(data)
            primary_key_name = model.get_primary_key_name()
            primary_key = payload.get(primary_key_name)
            if primary_key is None:
                primary_key = str(uuid4())
                payload[primary_key_name] = primary_key
            record_key = self.__record_key(primary_key)
            self.__apply_upsert(collection, record_key, payload)
            self.__queue_operation(collection_name, ("upsert", (record_key, payload)))
            return dict(payload)

    def retrieve(self, model: InLayersModel, id: PrimaryKeyType) -> Mapping | None:
        with self.__lock:
            self.__flush_pending_writes_locked()
            collection = self.__get_collection(model)
            record = collection.get(self.__record_key(id))
            if record is None:
                return None
            return dict(record)

    def update(
        self, model: InLayersModel, id: PrimaryKeyType, data: Mapping
    ) -> Mapping:
        with self.__lock:
            collection_name = self.__get_collection_name_for_model(model)
            collection = self.__get_collection(model)
            record_key = self.__record_key(id)
            existing = collection.get(record_key)
            if existing is None:
                raise KeyError(f"Instance with id {id!r} not found")

            payload = dict(existing)
            payload.update(dict(data))
            payload[model.get_primary_key_name()] = id
            self.__apply_upsert(collection, record_key, payload)
            self.__queue_operation(collection_name, ("upsert", (record_key, payload)))
            return dict(payload)

    def delete(self, model: InLayersModel, id: PrimaryKeyType) -> None:
        with self.__lock:
            collection_name = self.__get_collection_name_for_model(model)
            collection = self.__get_collection(model)
            record_key = self.__record_key(id)
            self.__apply_delete(collection, record_key)
            self.__queue_operation(collection_name, ("delete", record_key))

    def search(self, model: InLayersModel, query: ModelSearch) -> ModelSearchResult:
        with self.__lock:
            self.__flush_pending_writes_locked()
            collection = self.__get_collection(model)
            records = list(collection.values())
            filtered = [
                record
                for record in records
                if _matches_query_tokens(record, query.query)
            ]
            sorted_records = _apply_sort(filtered, query.sort)
            limited = _apply_take(sorted_records, query.take)
            return Box(instances=[dict(record) for record in limited], page=query.page)

    def count(self, model: InLayersModel) -> int:
        with self.__lock:
            self.__flush_pending_writes_locked()
            collection = self.__get_collection(model)
            return len(collection)

    def bulk_insert(self, model: InLayersModel, data: list[Mapping]) -> None:
        with self.__lock:
            if len(data) < 1:
                return
            collection_name = self.__get_collection_name_for_model(model)
            collection = self.__get_collection(model)
            primary_key_name = model.get_primary_key_name()
            inserts: list[tuple[str, dict[str, Any]]] = []
            for item in data:
                payload = dict(item)
                primary_key = payload.get(primary_key_name)
                if primary_key is None:
                    primary_key = str(uuid4())
                    payload[primary_key_name] = primary_key
                record_key = self.__record_key(primary_key)
                self.__apply_upsert(collection, record_key, payload)
                inserts.append((record_key, payload))
            self.__queue_operation(collection_name, ("bulk_upsert", inserts))

    def bulk_delete(self, model: InLayersModel, ids: list[PrimaryKeyType]) -> None:
        with self.__lock:
            if len(ids) < 1:
                return
            collection_name = self.__get_collection_name_for_model(model)
            collection = self.__get_collection(model)
            record_keys = [self.__record_key(primary_key) for primary_key in ids]
            for record_key in record_keys:
                self.__apply_delete(collection, record_key)
            self.__queue_operation(collection_name, ("bulk_delete", record_keys))

    def dispose(self) -> None:
        with self.__lock:
            self.__flush_pending_writes_locked()
            self.__collections = {}
            self.__loaded_database = False
            self.__loaded_collections = set()
