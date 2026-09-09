"""Unit tests for JSON backend services."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from box import Box
from pydantic import BaseModel

from in_layers.core.models.libs import model
from in_layers.core.models.query import PropertyOptions, query_builder
from in_layers.core.models.services import create_in_layers_model
from in_layers.data.backends.json.services import JsonBackend
from in_layers.data.protocols import SupportedBackend


@model(domain="functional-models-orm-json", plural_name="Test1Models")
class JsonTest1Model(BaseModel):
    id: str | None = None
    name: str
    created_at: str | None = None


@model(domain="functional-models-orm-json", plural_name="Test2Models")
class JsonTest2Model(BaseModel):
    id: str | None = None
    name: str


def _create_context():
    return Box(
        config=Box(system_name="json-tests", environment="test"),
        log=MagicMock(),
    )


def _create_config(
    file_path: str,
    *,
    directory_mode: bool = False,
    write_buffer_ms: int = 10_000,
    fs=None,
):
    return Box(
        type=SupportedBackend.Json,
        file_path=file_path,
        directory_mode=directory_mode,
        write_buffer_ms=write_buffer_ms,
        fs=fs,
        get_collection_name_for_model=None,
    )


def _create_model_classes(backend: JsonBackend):
    return (
        create_in_layers_model(JsonTest1Model, backend),
        create_in_layers_model(JsonTest2Model, backend),
    )


class _ExplodingReadFs:
    def read_file(self, file_path: str, encoding: str = "utf-8"):  # noqa: ARG002
        raise PermissionError("boom")

    def write_file(
        self, file_path: str, data: str, encoding: str = "utf-8"
    ):  # noqa: ARG002
        return None

    def mkdir(self, dir_path: str, recursive: bool = True):  # noqa: ARG002
        return None

    def open(self, file_path: str, mode: str):  # noqa: ARG002
        return open("/dev/null", "r", encoding="utf-8")

    def close(self, handle):
        handle.close()

    def unlink(self, file_path: str):  # noqa: ARG002
        return None


def test_should_create_and_flush_on_count_in_file_mode(tmp_path):
    file_path = tmp_path / "database.json"
    backend = JsonBackend(_create_context(), _create_config(str(file_path)))
    model, _ = _create_model_classes(backend)

    created = model.create({"name": "Alice"})

    assert file_path.exists() is False
    assert model.count() == 1
    assert created.get.name() == "Alice"
    assert file_path.exists() is True

    backend.dispose()


def test_should_support_search_update_delete_and_bulk_operations(tmp_path):
    file_path = tmp_path / "database.json"
    backend = JsonBackend(_create_context(), _create_config(str(file_path)))
    model, _ = _create_model_classes(backend)

    first = model.create({"id": "a", "name": "Alice"})
    model.update(first.get.id(), name="Alicia")
    model.bulk_insert(
        [
            {"id": "b", "name": "Bob"},
            {"id": "c", "name": "Charlie"},
        ]
    )
    search = model.search(
        query_builder()
        .property(
            "name",
            "ali",
            PropertyOptions(starts_with=True),
        )
        .compile()
    )

    assert [instance.get.name() for instance in search.instances] == ["Alicia"]
    assert model.count() == 3

    model.bulk_delete(["b", "c"])
    model.delete("a")

    assert model.count() == 0
    backend.dispose()


def test_should_flush_on_dispose_without_read(tmp_path):
    file_path = tmp_path / "database.json"
    backend = JsonBackend(_create_context(), _create_config(str(file_path)))
    model, _ = _create_model_classes(backend)

    model.create({"name": "Alice"})

    assert file_path.exists() is False

    backend.dispose()

    assert file_path.exists() is True


def test_should_support_directory_mode_and_multiple_collections(tmp_path):
    directory_path = tmp_path / "db"
    backend = JsonBackend(
        _create_context(),
        _create_config(str(directory_path), directory_mode=True),
    )
    model1, model2 = _create_model_classes(backend)

    model1.create({"id": "a", "name": "Alpha"})
    model2.create({"id": "b", "name": "Beta"})

    assert model1.count() == 1
    assert model2.count() == 1

    file1 = directory_path / "functional-models-orm-json-test-1-models.json"
    file2 = directory_path / "functional-models-orm-json-test-2-models.json"
    data1 = json.loads(file1.read_text(encoding="utf-8"))
    data2 = json.loads(file2.read_text(encoding="utf-8"))

    assert data1["functional-models-orm-json-test-1-models"]["a"]["name"] == "Alpha"
    assert data2["functional-models-orm-json-test-2-models"]["b"]["name"] == "Beta"

    backend.dispose()


def test_should_return_none_and_zero_when_file_missing(tmp_path):
    file_path = tmp_path / "missing.json"
    backend = JsonBackend(_create_context(), _create_config(str(file_path)))
    model, _ = _create_model_classes(backend)

    assert model.retrieve("missing") is None
    assert model.count() == 0

    backend.dispose()


def test_should_raise_non_enoent_read_errors():
    backend = JsonBackend(
        _create_context(),
        _create_config("broken.json", fs=_ExplodingReadFs(), write_buffer_ms=0),
    )
    model, _ = _create_model_classes(backend)

    with pytest.raises(PermissionError, match="boom"):
        model.retrieve("missing")


def test_should_preserve_datetime_like_strings_in_json_payload(tmp_path):
    file_path = tmp_path / "database.json"
    backend = JsonBackend(_create_context(), _create_config(str(file_path)))
    model, _ = _create_model_classes(backend)

    created_at = datetime(2024, 1, 2, tzinfo=UTC).isoformat()
    model.create({"id": "a", "name": "Alice", "created_at": created_at})
    backend.dispose()

    actual = json.loads(Path(file_path).read_text(encoding="utf-8"))
    assert (
        actual["functional-models-orm-json-test-1-models"]["a"]["created_at"]
        == created_at
    )
