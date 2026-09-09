"""Unit tests for top-level data services."""

from __future__ import annotations

from unittest.mock import MagicMock

from box import Box

import in_layers.data.services as data_services
from in_layers.data.protocols import SupportedBackend


class _StubModelDefinition:
    """Minimal model definition for routing tests."""

    def __init__(self, domain: str, plural_name: str):
        self.domain = domain
        self.plural_name = plural_name


class _StubMongoBackend:
    """Simple backend stub for MongoDB."""

    def __init__(self, context, config):
        self.context = context
        self.config = config
        self.was_disposed = False

    @staticmethod
    def create_unique_connection_string(config):
        return f"mongodb://{config.host}:{config.port}"

    def dispose(self):
        self.was_disposed = True


class _StubDynamoBackend:
    """Simple backend stub for DynamoDB."""

    def __init__(self, context, config):
        self.context = context
        self.config = config
        self.was_disposed = False

    @staticmethod
    def create_unique_connection_string(config):
        return f"dynamodb://{config.region}:{config.endpoint_url}"

    def dispose(self):
        self.was_disposed = True


class _StubRedisBackend:
    """Simple backend stub for Redis."""

    def __init__(self, context, config):
        self.context = context
        self.config = config
        self.was_disposed = False

    @staticmethod
    def create_unique_connection_string(config):
        return f"redis://{config.host}:{config.port}|stack={config.redis_stack}"

    def dispose(self):
        self.was_disposed = True


class _StubJsonBackend:
    """Simple backend stub for JSON."""

    def __init__(self, context, config):
        self.context = context
        self.config = config
        self.was_disposed = False

    @staticmethod
    def create_unique_connection_string(config):
        return f"json://{config.file_path}|directory={config.directory_mode}"

    def dispose(self):
        self.was_disposed = True


class _StubFailingMongoBackend(_StubMongoBackend):
    def dispose(self):
        raise RuntimeError("boom")


def _create_mongo_config(host: str, port: int = 27017):
    return Box(
        type=SupportedBackend.MongoDB,
        host=host,
        port=port,
        username=None,
        password=None,
        database=None,
    )


def _create_dynamo_config(region: str):
    return Box(
        type=SupportedBackend.DynamoDB,
        region=region,
        endpoint_url=None,
        aws_access_key_id=None,
        aws_secret_access_key=None,
        boto3=None,
    )


def _create_redis_config(host: str, port: int = 6379):
    return Box(
        type=SupportedBackend.Redis,
        host=host,
        port=port,
        username=None,
        password=None,
        redis_stack=True,
        redis=None,
        client=None,
    )


def _create_json_config(file_path: str, directory_mode: bool = False):
    return Box(
        type=SupportedBackend.Json,
        file_path=file_path,
        directory_mode=directory_mode,
        write_buffer_ms=10,
        fs=None,
        get_collection_name_for_model=None,
    )


def _create_context(default_backend, model_to_backend=None):
    return Box(
        config=Box(
            in_layers_data=Box(
                default=default_backend,
                model_to_backend=model_to_backend,
            )
        ),
        log=MagicMock(),
    )


class TestGetModelBackend:
    """Tests for get_model_backend()."""

    def test_should_reuse_backend_instance_for_matching_connection_config(
        self, monkeypatch
    ):
        monkeypatch.setattr(data_services, "MongoBackend", _StubMongoBackend)
        monkeypatch.setattr(data_services, "DynamoDBBackend", _StubDynamoBackend)
        monkeypatch.setattr(data_services, "RedisBackend", _StubRedisBackend)
        monkeypatch.setattr(data_services, "JsonBackend", _StubJsonBackend)

        shared_backend = _create_mongo_config("shared-host")
        context = _create_context(
            default_backend=shared_backend,
            model_to_backend={"billing.Invoices": shared_backend},
        )
        instance = data_services.create(context)

        default_actual = instance.get_model_backend(
            _StubModelDefinition("users", "Users")
        )
        override_actual = instance.get_model_backend(
            _StubModelDefinition("billing", "Invoices")
        )

        assert default_actual is override_actual

    def test_should_prefer_model_specific_then_domain_then_default_backend(
        self, monkeypatch
    ):
        monkeypatch.setattr(data_services, "MongoBackend", _StubMongoBackend)
        monkeypatch.setattr(data_services, "DynamoDBBackend", _StubDynamoBackend)
        monkeypatch.setattr(data_services, "RedisBackend", _StubRedisBackend)
        monkeypatch.setattr(data_services, "JsonBackend", _StubJsonBackend)

        default_backend = _create_mongo_config("default-host")
        domain_backend = _create_dynamo_config("us-east-1")
        model_backend = _create_mongo_config("model-host")
        context = _create_context(
            default_backend=default_backend,
            model_to_backend={
                "billing": domain_backend,
                "billing.Invoices": model_backend,
            },
        )
        instance = data_services.create(context)

        model_specific_actual = instance.get_model_backend(
            _StubModelDefinition("billing", "Invoices")
        )
        domain_actual = instance.get_model_backend(
            _StubModelDefinition("billing", "Jobs")
        )
        default_actual = instance.get_model_backend(
            _StubModelDefinition("users", "Users")
        )

        assert model_specific_actual.config.host == "model-host"
        assert domain_actual.config.region == "us-east-1"
        assert default_actual.config.host == "default-host"

    def test_should_support_redis_for_default_and_model_specific_routing(
        self, monkeypatch
    ):
        monkeypatch.setattr(data_services, "MongoBackend", _StubMongoBackend)
        monkeypatch.setattr(data_services, "DynamoDBBackend", _StubDynamoBackend)
        monkeypatch.setattr(data_services, "RedisBackend", _StubRedisBackend)
        monkeypatch.setattr(data_services, "JsonBackend", _StubJsonBackend)

        default_backend = _create_redis_config("redis-default")
        model_backend = _create_redis_config("redis-model")
        context = _create_context(
            default_backend=default_backend,
            model_to_backend={
                "billing.RedisCaches": model_backend,
            },
        )
        instance = data_services.create(context)

        default_actual = instance.get_model_backend(
            _StubModelDefinition("users", "Users")
        )
        model_actual = instance.get_model_backend(
            _StubModelDefinition("billing", "RedisCaches")
        )

        assert default_actual.config.host == "redis-default"
        assert model_actual.config.host == "redis-model"

    def test_should_support_json_backend_routing_and_reuse(self, monkeypatch):
        monkeypatch.setattr(data_services, "MongoBackend", _StubMongoBackend)
        monkeypatch.setattr(data_services, "DynamoDBBackend", _StubDynamoBackend)
        monkeypatch.setattr(data_services, "RedisBackend", _StubRedisBackend)
        monkeypatch.setattr(data_services, "JsonBackend", _StubJsonBackend)

        shared_backend = _create_json_config("/tmp/shared.json")
        context = _create_context(
            default_backend=shared_backend,
            model_to_backend={"billing.Invoices": shared_backend},
        )
        instance = data_services.create(context)

        default_actual = instance.get_model_backend(
            _StubModelDefinition("users", "Users")
        )
        model_actual = instance.get_model_backend(
            _StubModelDefinition("billing", "Invoices")
        )

        assert default_actual is model_actual


class TestDispose:
    """Tests for dispose()."""

    def test_should_allow_dispose_before_backend_initialization(self, monkeypatch):
        monkeypatch.setattr(data_services, "MongoBackend", _StubMongoBackend)
        monkeypatch.setattr(data_services, "DynamoDBBackend", _StubDynamoBackend)
        monkeypatch.setattr(data_services, "RedisBackend", _StubRedisBackend)
        monkeypatch.setattr(data_services, "JsonBackend", _StubJsonBackend)

        context = _create_context(default_backend=_create_mongo_config("default-host"))
        instance = data_services.create(context)

        instance.dispose()

        assert instance._InLayersDataServices__backends is None
        assert instance._InLayersDataServices__backend_by_unique_key == {}

    def test_should_log_warning_when_backend_dispose_fails(self, monkeypatch):
        monkeypatch.setattr(data_services, "MongoBackend", _StubFailingMongoBackend)
        monkeypatch.setattr(data_services, "DynamoDBBackend", _StubDynamoBackend)
        monkeypatch.setattr(data_services, "RedisBackend", _StubRedisBackend)
        monkeypatch.setattr(data_services, "JsonBackend", _StubJsonBackend)

        context = _create_context(default_backend=_create_mongo_config("default-host"))
        logger = MagicMock()
        context.log.get_inner_logger.return_value = logger
        instance = data_services.create(context)
        instance.get_model_backend(_StubModelDefinition("users", "Users"))

        instance.dispose()

        assert logger.warn.call_count == 1
        assert instance._InLayersDataServices__backends is None
        assert instance._InLayersDataServices__backend_by_unique_key == {}
