"""Unit tests for MongoDB backend services."""

from __future__ import annotations

from unittest.mock import MagicMock

from box import Box

from in_layers.data.backends.mongodb.services import MongoBackend
from in_layers.data.protocols import SupportedBackend


class _StubModelDefinition:
    def __init__(self, plural_name: str = "MongoModels"):
        self.plural_name = plural_name


class _StubModel:
    def get_model_definition(self):
        return _StubModelDefinition()

    def get_primary_key_name(self) -> str:
        return "id"


def _create_config():
    return Box(
        type=SupportedBackend.MongoDB,
        host="localhost",
        port=27017,
        username=None,
        password=None,
        database="mongo-tests",
    )


def test_should_count_documents_in_collection(monkeypatch):
    collection = MagicMock()
    collection.count_documents.return_value = 3
    database = MagicMock()
    database.__getitem__.return_value = collection
    client = MagicMock()
    client.__getitem__.return_value = database
    monkeypatch.setattr(
        "pymongo.MongoClient",
        lambda *args, **kwargs: client,  # noqa: ARG005
    )

    context = Box(config=Box(system_name="mongo-tests", environment="test"))
    backend = MongoBackend(context, _create_config())

    actual = backend.count(_StubModel())

    assert actual == 3
    collection.count_documents.assert_called_once_with({})
