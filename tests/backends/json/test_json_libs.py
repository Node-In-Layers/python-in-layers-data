"""Unit tests for JSON backend helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from in_layers.data.backends.json.libs import (
    JsonFilesystem,
    get_collection_name_for_model_definition,
    load_database_from_file,
    save_database_to_file,
    with_file_lock,
)


class _StubModelDefinition:
    def __init__(
        self,
        domain: str = "functional-models-orm-json",
        plural_name: str = "Test1Models",
    ):
        self.domain = domain
        self.plural_name = plural_name


class _FsWithoutRename:
    def read_file(self, file_path: str, encoding: str = "utf-8") -> str:
        return Path(file_path).read_text(encoding=encoding)

    def write_file(self, file_path: str, data: str, encoding: str = "utf-8") -> None:
        Path(file_path).write_text(data, encoding=encoding)

    def mkdir(self, dir_path: str, recursive: bool = True) -> None:
        Path(dir_path).mkdir(parents=recursive, exist_ok=True)


class _LockedFs:
    def open(self, file_path: str, mode: str):  # noqa: ARG002
        error = FileExistsError(file_path)
        error.code = "EEXIST"  # type: ignore[attr-defined]
        raise error

    def close(self, handle):  # noqa: ARG002
        return None

    def unlink(self, file_path: str):  # noqa: ARG002
        return None


def test_should_get_ts_compatible_collection_name():
    model_definition = _StubModelDefinition()

    actual = get_collection_name_for_model_definition(model_definition)

    assert actual == "functional-models-orm-json-test-1-models"


def test_should_return_empty_database_when_file_missing(tmp_path):
    missing_file = tmp_path / "missing.json"

    actual = load_database_from_file(JsonFilesystem(), str(missing_file))

    assert actual == {}


def test_should_fall_back_to_direct_write_when_rename_missing(tmp_path):
    file_path = tmp_path / "database.json"
    fs = _FsWithoutRename()

    save_database_to_file(
        fs,
        str(file_path),
        {"users-models": {"1": {"id": 1, "name": "Alice"}}},
    )

    actual = load_database_from_file(JsonFilesystem(), str(file_path))
    assert actual["users-models"]["1"]["name"] == "Alice"


def test_should_raise_timeout_when_lock_never_releases():
    with pytest.raises(TimeoutError):
        with_file_lock(
            _LockedFs(),
            "busy.lock",
            lambda: "never",
            poll_ms=0,
            max_wait_ms=1,
        )
