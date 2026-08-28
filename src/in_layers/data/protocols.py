from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal, Protocol


class SupportedBackend(Enum):
    MongoDB = "mongodb"
    DynamoDB = "dynamodb"


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


BackendConfig = MongoBackendConfig | DynamoDBBackendConfig


class DataNamespace(Enum):
    root = "in_layers_data"
    backends = "in_layers_data_backends"


class InLayersDataConfig(Protocol):
    default: BackendConfig
    model_to_backend: Mapping[str, BackendConfig] | None


class WithInLayersDataConfig(Protocol):
    in_layers_data: InLayersDataConfig
