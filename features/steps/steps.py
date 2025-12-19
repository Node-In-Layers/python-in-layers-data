"""Step definitions for MongoDB feature tests."""

from __future__ import annotations

import json
from datetime import datetime as datetime_
from pathlib import Path
from typing import Any
from uuid import uuid4

from behave import given, then, when
from in_layers.core.models.libs import model
from in_layers.core.models.protocols import DatastoreValueType, PropertyOptions
from in_layers.core.models.query import query_builder
from pydantic import BaseModel, Field
from pymongo import MongoClient

from in_layers.data.backends.mongodb.libs import get_collection_name_for_model
from in_layers.data.backends.mongodb.services import MongoBackend


# Load environment configuration
def _load_env() -> dict[str, Any]:
    env_path = Path(__file__).parent.parent.parent / ".env-cucumber.json"
    if not env_path.exists():
        raise FileNotFoundError("Must have a .env-cucumber.json file")
    with env_path.open() as f:
        env = json.load(f)
    if "mongoUrl" not in env:
        raise ValueError("Must have mongoUrl inside the .env-cucumber.json")
    return env


DB_NAME = "in-layers-data-mongo-tests"


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


def _cleanout_database(context: Any) -> None:
    """Clean out the test database."""
    env = _load_env()
    client = MongoClient(env["mongoUrl"])
    db = client[DB_NAME]

    # Get all collection names from models - we only need the model classes, not instances
    # So we'll get them directly without calling the model_list_func
    from in_layers.core.models.libs import get_model_definition

    # Get model classes directly
    model_classes = [ModelA, ModelB, ModelC]
    for model_cls in model_classes:
        meta = get_model_definition(model_cls)
        collection_name = get_collection_name_for_model(meta)
        collection = db[collection_name]
        collection.delete_many({})

    client.close()


def _setup_backend(context: Any) -> None:
    """Set up the MongoDB backend."""
    env = _load_env()
    mongo_url = env["mongoUrl"]
    # Parse mongo URL to get config
    # Simple parsing - assumes mongodb://host:port format
    url_parts = mongo_url.replace("mongodb://", "").split("/")
    host_port = url_parts[0].split(":")

    class Config:
        host = host_port[0]
        port = int(host_port[1]) if len(host_port) > 1 else 27017
        username = ""
        password = ""
        database = DB_NAME

    context.backend = MongoBackend(Config())


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
    context.model_classes = {}

    # Create model instances using the backend
    for model_cls in result["models"]:
        from in_layers.core.models.libs import get_model_definition

        meta = get_model_definition(model_cls)
        context.model_classes[meta.plural_name] = model_cls
        # Store the model class and backend for later use
        context.models[meta.plural_name] = {
            "class": model_cls,
            "backend": context.backend,
            "meta": meta,
        }

    # Insert instances
    for instance in result["instances"]:
        instance_dict = instance.model_dump()
        model_cls = instance.__class__
        meta = get_model_definition(model_cls)
        context.backend.create(
            type(
                "Model",
                (),
                {
                    "get_model_definition": lambda self: meta,
                    "get_primary_key_name": lambda self: meta.primary_key,
                },
            )(),
            instance_dict,
        )


@when("search named {search_name} is executed on model named {model_name}")
def step_search_executed(context: Any, search_name: str, model_name: str) -> None:
    """Execute a search on a model."""
    if search_name not in SEARCHES:
        raise ValueError(f"Unknown search: {search_name}")
    if model_name not in context.models:
        raise ValueError(f"Unknown model: {model_name}")

    search = SEARCHES[search_name]()
    model_info = context.models[model_name]
    meta = model_info["meta"]

    # Create a mock model object for the search
    mock_model = type(
        "Model",
        (),
        {
            "get_model_definition": lambda self: meta,
            "get_primary_key_name": lambda self: meta.primary_key,
        },
    )()

    context.result = context.backend.search(mock_model, search)


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
    model_info = context.models[model_name]
    meta = model_info["meta"]

    # Create a mock model object
    mock_model = type(
        "Model",
        (),
        {
            "get_model_definition": lambda self: meta,
            "get_primary_key_name": lambda self: meta.primary_key,
        },
    )()

    context.backend.bulk_delete(mock_model, ids)
