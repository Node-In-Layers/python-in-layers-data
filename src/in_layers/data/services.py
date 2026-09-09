from typing import Any, Protocol

from in_layers.core import create_error_object
from in_layers.core.models.protocols import BackendProtocol, ModelDefinition

from .backends.dynamodb.services import DynamoDBBackend
from .backends.json.services import JsonBackend
from .backends.mongodb.services import MongoBackend
from .backends.redis.services import RedisBackend
from .protocols import (
    BackendConfig,
    SupportedBackend,
    WithInLayersDataConfig,
)


class _ExpectedContext(Protocol):
    config: WithInLayersDataConfig
    log: Any


class InLayersDataServices:
    def __init__(self, context: _ExpectedContext):
        self.__context = context
        self.__backend_by_unique_key = {}
        self.__backends = None

    def __initialize_backend(  # noqa: PLR0911
        self, config: BackendConfig
    ) -> BackendProtocol:
        if config.type in [SupportedBackend.MongoDB, SupportedBackend.MongoDB.value]:
            unique = MongoBackend.create_unique_connection_string(config)
            if unique in self.__backend_by_unique_key:
                return self.__backend_by_unique_key[unique]
            backend = MongoBackend(self.__context, config)
            self.__backend_by_unique_key[unique] = backend
            return backend
        elif config.type in [
            SupportedBackend.DynamoDB,
            SupportedBackend.DynamoDB.value,
        ]:
            unique = DynamoDBBackend.create_unique_connection_string(config)
            if unique in self.__backend_by_unique_key:
                return self.__backend_by_unique_key[unique]
            backend = DynamoDBBackend(self.__context, config)
            self.__backend_by_unique_key[unique] = backend
            return backend
        elif config.type in [SupportedBackend.Redis, SupportedBackend.Redis.value]:
            unique = RedisBackend.create_unique_connection_string(config)
            if unique in self.__backend_by_unique_key:
                return self.__backend_by_unique_key[unique]
            backend = RedisBackend(self.__context, config)
            self.__backend_by_unique_key[unique] = backend
            return backend
        elif config.type in [SupportedBackend.Json, SupportedBackend.Json.value]:
            unique = JsonBackend.create_unique_connection_string(config)
            if unique in self.__backend_by_unique_key:
                return self.__backend_by_unique_key[unique]
            backend = JsonBackend(self.__context, config)
            self.__backend_by_unique_key[unique] = backend
            return backend
        else:
            raise ValueError(f"Unsupported backend type: {config.type}")

    def __initialize_backends(self):
        if self.__backends is not None:
            return
        config = self.__context.config.in_layers_data
        default_backend_config = config.default
        model_to_backend_config = getattr(config, "model_to_backend", {}) or {}

        self.__backends = {"default": self.__initialize_backend(default_backend_config)}
        for model_key, backend_config in model_to_backend_config.items():
            backend_instance = self.__initialize_backend(backend_config)
            self.__backends[model_key] = backend_instance

    def __get_backend_for_model(self, meta: ModelDefinition) -> BackendProtocol:
        self.__initialize_backends()
        model_key_full = f"{meta.domain}.{meta.plural_name}"
        if model_key_full in self.__backends:
            return self.__backends[model_key_full]
        if meta.domain in self.__backends:
            return self.__backends[meta.domain]
        return self.__backends["default"]

    def get_model_backend(self, model_definition: ModelDefinition) -> BackendProtocol:
        backend = self.__get_backend_for_model(model_definition)
        if not backend:
            raise ValueError(
                f"No backend found for model {model_definition.domain}.{model_definition.plural_name}"
            )
        return backend

    def dispose(self):
        for backend in (self.__backends or {}).values():
            try:
                backend.dispose()
            except Exception as e:
                error_obj = create_error_object(
                    "DATA_SERVICES_DISPOSE_ERROR", "Error disposing backend", e
                )
                log = self.__context.log.get_inner_logger("dispose")
                log.warn("Error disposing backend", error_obj)

        self.__backends = None
        self.__backend_by_unique_key = {}


def create(context: _ExpectedContext) -> InLayersDataServices:
    return InLayersDataServices(context)
