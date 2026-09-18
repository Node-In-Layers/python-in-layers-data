"""JSON backend helpers."""

from __future__ import annotations

import json
import os
import re
import secrets
import time
import unicodedata
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol, TypeVar

from in_layers.core.models.protocols import InLayersModel, ModelDefinition

T = TypeVar("T")
_SECONDS_PER_MINUTE = 60
_CAMEL_CASE_RE = re.compile(r"(?<!^)(?=[A-Z])")
_ALPHA_NUM_BOUNDARY_RE = re.compile(r"([a-zA-Z])([0-9])")
_NUM_ALPHA_BOUNDARY_RE = re.compile(r"([0-9])([a-zA-Z])")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


class JsonFilesystemProtocol(Protocol):
    def read_file(self, file_path: str, encoding: str = "utf-8") -> str: ...
    def write_file(
        self, file_path: str, data: str, encoding: str = "utf-8"
    ) -> None: ...
    def mkdir(self, dir_path: str, recursive: bool = True) -> None: ...
    def rename(self, from_path: str, to_path: str) -> None: ...
    def open(self, file_path: str, mode: str): ...
    def close(self, handle: Any) -> None: ...
    def unlink(self, file_path: str) -> None: ...


class JsonFilesystem:
    """Default stdlib-backed filesystem shim for tests and runtime."""

    def read_file(self, file_path: str, encoding: str = "utf-8") -> str:
        return Path(file_path).read_text(encoding=encoding)

    def write_file(self, file_path: str, data: str, encoding: str = "utf-8") -> None:
        Path(file_path).write_text(data, encoding=encoding)

    def mkdir(self, dir_path: str, recursive: bool = True) -> None:
        Path(dir_path).mkdir(parents=recursive, exist_ok=True)

    def rename(self, from_path: str, to_path: str) -> None:
        Path(from_path).replace(to_path)

    def open(self, file_path: str, mode: str):
        return Path(file_path).open(mode, encoding="utf-8")

    def close(self, handle: Any) -> None:
        handle.close()

    def unlink(self, file_path: str) -> None:
        Path(file_path).unlink()


def _ascii_lower(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_bytes = normalized.encode("ascii", "ignore")
    return ascii_bytes.decode("ascii").lower()


def _to_kebab(value: str) -> str:
    kebab = _CAMEL_CASE_RE.sub("-", value).replace("_", "-").replace("/", "-")
    kebab = _ALPHA_NUM_BOUNDARY_RE.sub(r"\1-\2", kebab)
    kebab = _NUM_ALPHA_BOUNDARY_RE.sub(r"\1-\2", kebab)
    kebab = _ascii_lower(kebab)
    kebab = _NON_ALNUM_RE.sub("-", kebab)
    return kebab.strip("-")


def get_collection_name_for_model_definition(model_definition: ModelDefinition) -> str:
    identifier = f"{model_definition.domain}/{model_definition.plural_name}"
    return _to_kebab(identifier.replace("@", ""))


def get_collection_name_for_model(model: InLayersModel) -> str:
    return get_collection_name_for_model_definition(model.get_model_definition())


def to_unix_timestamp(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) * _SECONDS_PER_MINUTE
    if isinstance(value, str):
        normalized = value.strip()
        if normalized == "":
            return None
        with suppress(ValueError):
            return float(int(normalized)) * _SECONDS_PER_MINUTE
    return None


def get_record_expiry_timestamp(
    record: dict[str, Any] | Mapping[str, Any], ttl_property_name: str | None
) -> float | None:
    if ttl_property_name is None or ttl_property_name == "":
        return None
    if ttl_property_name not in record:
        return None
    return to_unix_timestamp(record.get(ttl_property_name))


def is_record_expired(
    record: dict[str, Any] | Mapping[str, Any],
    ttl_property_name: str | None,
    *,
    current_time_seconds: float | None = None,
) -> bool:
    expiry_timestamp = get_record_expiry_timestamp(record, ttl_property_name)
    if expiry_timestamp is None:
        return False
    now_seconds = time.time() if current_time_seconds is None else current_time_seconds
    return expiry_timestamp <= now_seconds


def _is_enoent(error: Exception) -> bool:
    if isinstance(error, FileNotFoundError):
        return True
    code = getattr(error, "code", None)
    return code == "ENOENT"


def load_database_from_file(
    fs: JsonFilesystemProtocol, file_path: str
) -> dict[str, dict[str, dict[str, Any]]]:
    try:
        data = fs.read_file(file_path, "utf-8")
    except Exception as error:
        if _is_enoent(error):
            return {}
        raise
    return json.loads(data)


def save_database_to_file(
    fs: JsonFilesystemProtocol,
    file_path: str,
    database: dict[str, dict[str, dict[str, Any]]],
) -> None:
    parent_dir = str(Path(file_path).parent)
    fs.mkdir(parent_dir, recursive=True)
    data = json.dumps(database, indent=2)
    tmp_path = str(
        Path(parent_dir)
        / f".{Path(file_path).name}.{os.getpid()}.{int(time.time() * 1000)}.{secrets.token_hex(8)}.tmp"
    )
    fs.write_file(tmp_path, data, "utf-8")
    rename = getattr(fs, "rename", None)
    if callable(rename):
        rename(tmp_path, file_path)
    else:
        fs.write_file(file_path, data, "utf-8")


def load_collection_from_directory(
    fs: JsonFilesystemProtocol, dir_path: str, collection_name: str
) -> dict[str, dict[str, dict[str, Any]]]:
    full_path = str(Path(dir_path) / f"{collection_name}.json")
    try:
        data = fs.read_file(full_path, "utf-8")
    except Exception as error:
        if _is_enoent(error):
            return {}
        raise
    return json.loads(data)


def save_collection_to_directory(
    fs: JsonFilesystemProtocol,
    dir_path: str,
    collection_name: str,
    collection_data: dict[str, dict[str, dict[str, Any]]],
) -> None:
    fs.mkdir(dir_path, recursive=True)
    full_path = str(Path(dir_path) / f"{collection_name}.json")
    data = json.dumps(collection_data, indent=2)
    tmp_path = str(
        Path(dir_path)
        / f".{collection_name}.{os.getpid()}.{int(time.time() * 1000)}.{secrets.token_hex(8)}.tmp"
    )
    fs.write_file(tmp_path, data, "utf-8")
    rename = getattr(fs, "rename", None)
    if callable(rename):
        rename(tmp_path, full_path)
    else:
        fs.write_file(full_path, data, "utf-8")


def sleep(ms: int) -> None:
    time.sleep(ms / 1000)


def with_file_lock(  # noqa: UP047
    fs: JsonFilesystemProtocol,
    lock_path: str,
    func: Callable[[], T],
    *,
    poll_ms: int = 25,
    max_wait_ms: int = 10_000,
) -> T:
    if not all(
        callable(getattr(fs, name, None)) for name in ["open", "close", "unlink"]
    ):
        return func()

    lock_parent = str(Path(lock_path).parent)
    mkdir = getattr(fs, "mkdir", None)
    if callable(mkdir):
        mkdir(lock_parent, recursive=True)

    started_at = time.time() * 1000
    handle = None
    while True:
        try:
            handle = fs.open(lock_path, "x")
            break
        except Exception as error:
            if getattr(error, "code", None) != "EEXIST" and not isinstance(
                error, FileExistsError
            ):
                raise
            if (time.time() * 1000) - started_at > max_wait_ms:
                raise TimeoutError(
                    f"Timed out waiting for lock: {lock_path}"
                ) from error
            sleep(poll_ms)

    try:
        return func()
    finally:
        with suppress(Exception):
            fs.close(handle)
        with suppress(Exception):
            fs.unlink(lock_path)
