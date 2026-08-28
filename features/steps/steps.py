"""Step definitions for backend feature tests."""

from __future__ import annotations

import json
from datetime import datetime as datetime_
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4
from unittest.mock import MagicMock

from box import Box
from behave import given, then, when
from in_layers.core.models.libs import get_model_definition, model
from in_layers.core.models.protocols import DatastoreValueType, PropertyOptions
from in_layers.core.models.query import query_builder
from in_layers.core.models.services import create_in_layers_model
from pydantic import BaseModel, Field
from pymongo import MongoClient

from in_layers.data.backends.mongodb.libs import get_collection_name_for_model
from in_layers.data.backends.mongodb.services import MongoBackend
from in_layers.data.backends.redis.libs import (
    get_key_prefix_for_model_definition,
    get_search_document_prefix,
    get_search_index_name,
)
from in_layers.data.backends.redis.services import RedisBackend
from in_layers.data.protocols import SupportedBackend


# Load environment configuration
def _load_env() -> dict[str, Any]:
    env_path = Path(__file__).parent.parent.parent / ".env-cucumber.json"
    if not env_path.exists():
        return {}
    with env_path.open() as f:
        env = json.load(f)
    return env


DB_NAME = "in-layers-data-mongo-tests"
REDIS_MODEL_CLASSES = []


# Model definitions
@model(domain="functional-models-orm-mongo", plural_name="ModelA", primary_key="id")
class ModelA(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    age: int
    datetime: datetime_ | None = None


@model(domain="functional-models-orm-mongo", plural_name="ModelB", primary_key="id")
class ModelB(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    age: int
    datetime: str | None = None


@model(domain="functional-models-orm-mongo", plural_name="ModelC", primary_key="id")
class ModelC(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    age: int
    date: str | None = None


# Model lists for test data
MODELS = {
    "ModelList1": lambda backend: {
        "models": [ModelA],
        "instances": [
            ModelA(
                id="edf73dba-216a-4e10-a38f-398a4b38350a",
                name="name-2",
                age=2,
            ),
            ModelA(
                id="2c3e6547-2d6b-44c3-ad2c-1220a3d305be",
                name="name-3",
                age=10,
                datetime=datetime_.fromisoformat("2020-02-01T00:00:00.000Z"),
            ),
            ModelA(
                id="ed1dc8ff-fdc5-401c-a229-8566a418ceb5",
                name="name-1",
                age=1,
                datetime=datetime_.fromisoformat("2020-01-01T00:00:00.000Z"),
            ),
            ModelA(
                name="name-4",
                age=15,
                datetime=datetime_.fromisoformat("2020-03-01T00:00:00.000Z"),
            ),
            ModelA(name="name-5", age=20),
            ModelA(name="name-7", age=20),
            ModelA(name="name-6", age=20),
            ModelA(name="name-9", age=30),
            ModelA(
                name="name-10",
                age=100,
                datetime=datetime_.fromisoformat("2020-05-01T00:00:00.000Z"),
            ),
            ModelA(name="name-8", age=50),
        ],
    },
    "ModelList2": lambda backend: {
        "models": [ModelB],
        "instances": [
            ModelB(name="name-2", age=2),
            ModelB(
                name="name-3",
                age=10,
                datetime="2020-02-01T00:00:00.000Z",
            ),
            ModelB(
                name="name-1",
                age=1,
                datetime="2020-01-01T00:00:00.000Z",
            ),
            ModelB(
                name="name-4",
                age=15,
                datetime="2020-03-01T00:00:00.000Z",
            ),
            ModelB(name="name-5", age=20),
            ModelB(name="name-7", age=20),
            ModelB(name="name-6", age=20),
            ModelB(name="name-9", age=30),
            ModelB(
                name="name-10",
                age=100,
                datetime="2020-05-01T00:00:00.000Z",
            ),
            ModelB(name="name-8", age=50),
        ],
    },
    "ModelList3": lambda backend: {
        "models": [ModelC],
        "instances": [
            ModelC(name="name-2", age=2),
            ModelC(name="name-3", age=10, date="2020-02-01"),
            ModelC(name="name-1", age=1, date="2020-01-01"),
            ModelC(name="name-4", age=15, date="2020-03-01"),
            ModelC(name="name-5", age=20),
            ModelC(name="name-7", age=20),
            ModelC(name="name-6", age=20),
            ModelC(name="name-9", age=30),
            ModelC(name="name-10", age=100, date="2020-05-01"),
            ModelC(name="name-8", age=50),
        ],
    },
}


MODEL_CLASSES = [ModelA, ModelB, ModelC]
REDIS_MODEL_CLASSES = MODEL_CLASSES


# Search definitions
SEARCHES = {
    "DateSpanSearch": lambda: query_builder()
    .dates_after(
        "datetime",
        datetime_.fromisoformat("2020-02-01T00:00:00.000Z"),
        equal_to_and_after=True,
    )
    .and_()
    .dates_before(
        "datetime",
        datetime_.fromisoformat("2020-05-01T00:00:00.000Z"),
        equal_to_and_before=False,
    )
    .compile(),
    "DateSpanSearch2": lambda: query_builder()
    .dates_after(
        "datetime",
        "2020-02-01T00:00:00.000Z",
        value_type=DatastoreValueType.string,
        equal_to_and_after=True,
    )
    .and_()
    .dates_before(
        "datetime",
        "2020-05-01T00:00:00.000Z",
        value_type=DatastoreValueType.string,
        equal_to_and_before=False,
    )
    .compile(),
    "DateSpanSearch3": lambda: query_builder()
    .dates_after(
        "date",
        "2020-02-01",
        value_type=DatastoreValueType.string,
        equal_to_and_after=True,
    )
    .and_()
    .dates_before(
        "date",
        "2020-05-01",
        value_type=DatastoreValueType.string,
        equal_to_and_before=False,
    )
    .compile(),
    "TextStartsWithPropertySearch": lambda: query_builder()
    .property("name", "name-1", PropertyOptions(starts_with=True))
    .compile(),
    "OrPropertySearch": lambda: query_builder()
    .property("name", "name-8")
    .or_()
    .property("name", "name-1")
    .or_()
    .property("name", "name-10")
    .compile(),
    "EmptySearch": lambda: query_builder().compile(),
}


def _get_backend_name(context: Any) -> str:
    return getattr(context, "backend_name", "mongodb")


def _get_redis_url(context: Any) -> str:
    if getattr(context, "redis_url", None):
        return context.redis_url
    env = _load_env()
    redis_url = env.get("redisUrl")
    if not redis_url:
        raise ValueError(
            "Must have redisUrl configured or start a Redis test container"
        )
    return redis_url


def _get_mongo_url(context: Any) -> str:
    if getattr(context, "mongo_url", None):
        return context.mongo_url
    env = _load_env()
    mongo_url = env.get("mongoUrl")
    if not mongo_url:
        raise ValueError(
            "Must have mongoUrl configured or start a Mongo test container"
        )
    return mongo_url


def _create_backend_context() -> Box:
    return Box(
        config=Box(
            system_name="in-layers-data",
            environment="test",
        ),
        log=MagicMock(),
    )


def _cleanout_database(context: Any) -> None:
    """Clean out the selected test backend."""
    backend_name = _get_backend_name(context)
    if backend_name == "redis":
        import redis  # pragma: no cover # noqa: PLC0415

        client = redis.from_url(_get_redis_url(context), decode_responses=True)
        for model_cls in REDIS_MODEL_CLASSES:
            meta = get_model_definition(model_cls)
            key_prefix = get_key_prefix_for_model_definition(meta)
            data_keys = client.keys(f"{key_prefix}:*")
            search_keys = client.keys(f"{get_search_document_prefix(key_prefix)}*")
            if data_keys:
                client.delete(*data_keys)
            if search_keys:
                client.delete(*search_keys)
            try:
                client.execute_command(
                    "FT.DROPINDEX", get_search_index_name(key_prefix), "DD"
                )
            except Exception:
                pass
        client.close()
        return

    client = MongoClient(_get_mongo_url(context))
    db = client[DB_NAME]
    for model_cls in MODEL_CLASSES:
        meta = get_model_definition(model_cls)
        collection_name = get_collection_name_for_model(meta)
        collection = db[collection_name]
        collection.delete_many({})
    client.close()


def _setup_backend(context: Any) -> None:
    """Set up the selected backend."""
    backend_name = _get_backend_name(context)
    backend_context = _create_backend_context()
    if backend_name == "redis":
        parsed = urlparse(_get_redis_url(context))
        config = Box(
            type=SupportedBackend.Redis,
            host=parsed.hostname or "localhost",
            port=parsed.port or 6379,
            username=parsed.username,
            password=parsed.password,
            redis_stack=True,
            redis=None,
            client=None,
        )
        context.backend = RedisBackend(backend_context, config)
        return

    mongo_url = _get_mongo_url(context)
    url_parts = mongo_url.replace("mongodb://", "").split("/")
    host_port = url_parts[0].split(":")
    config = Box(
        host=host_port[0],
        port=int(host_port[1]) if len(host_port) > 1 else 27017,
        username="",
        password="",
        database=DB_NAME,
    )
    context.backend = MongoBackend(backend_context, config)


# Step definitions
@given("an orm is setup")
def step_orm_setup(context: Any) -> None:
    """Set up the ORM/backend."""
    if not hasattr(context, "backend"):
        _setup_backend(context)


@given("{model_list} is created and inserted into the database")
def step_model_list_created(context: Any, model_list: str) -> None:
    """Create and insert model instances."""
    if model_list not in MODELS:
        raise ValueError(f"Unknown model list: {model_list}")

    result = MODELS[model_list](context.backend)
    context.models = {}
    for model_cls in result["models"]:
        meta = get_model_definition(model_cls)
        context.models[meta.plural_name] = create_in_layers_model(
            model_cls, context.backend
        )

    for instance in result["instances"]:
        instance_dict = instance.model_dump()
        model_name = get_model_definition(instance.__class__).plural_name
        context.models[model_name].create(instance_dict)


@when("search named {search_name} is executed on model named {model_name}")
def step_search_executed(context: Any, search_name: str, model_name: str) -> None:
    """Execute a search on a model."""
    if search_name not in SEARCHES:
        raise ValueError(f"Unknown search: {search_name}")
    if model_name not in context.models:
        raise ValueError(f"Unknown model: {model_name}")

    search = SEARCHES[search_name]()
    context.result = context.models[model_name].search(search)


@then("{count:d} instances are found")
def step_instances_found(context: Any, count: int) -> None:
    """Assert the number of instances found."""
    actual = len(context.result.instances)
    assert actual == count, f"Expected {count} instances, but found {actual}"


@when('bulk delete is executed on model named {model_name} with ids "{ids_string}"')
def step_bulk_delete(context: Any, model_name: str, ids_string: str) -> None:
    """Execute bulk delete on a model."""
    if model_name not in context.models:
        raise ValueError(f"Unknown model: {model_name}")

    ids = [id.strip() for id in ids_string.split(",")]
    context.models[model_name].bulk_delete(ids)
