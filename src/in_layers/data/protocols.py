from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal, Protocol


class SupportedBackend(Enum):
    MongoDB = "mongodb"
    DynamoDB = "dynamodb"
    Redis = "redis"
    Json = "json"


class MongoBackendConfig(Protocol):
    type: Literal[SupportedBackend.MongoDB]
    host: str
    port: int | None
    username: str | None
    password: str | None
    database: str | None


class DynamoDBBackendConfig(Protocol):
    type: Literal[SupportedBackend.DynamoDB]
    region: str | None
    endpoint_url: str | None
    aws_access_key_id: str | None
    aws_secret_access_key: str | None
    boto3: Any | None


class RedisBackendConfig(Protocol):
    type: Literal[SupportedBackend.Redis]
    host: str
    port: int | None
    username: str | None
    password: str | None
    redis_stack: bool | None
    redis: Any | None
    client: Any | None


class JsonBackendConfig(Protocol):
    type: Literal[SupportedBackend.Json]
    file_path: str
    directory_mode: bool | None
    write_buffer_ms: int | None
    fs: Any | None
    get_collection_name_for_model: Any | None


BackendConfig = (
    MongoBackendConfig | DynamoDBBackendConfig | RedisBackendConfig | JsonBackendConfig
)


class DataNamespace(Enum):
    root = "in_layers_data"
    backends = "in_layers_data_backends"


class InLayersDataConfig(Protocol):
    default: BackendConfig
    model_to_backend: Mapping[str, BackendConfig] | None


class WithInLayersDataConfig(Protocol):
    in_layers_data: InLayersDataConfig
