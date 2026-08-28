"""Redis backend helpers."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import date, datetime
from types import NoneType, UnionType
from typing import Any, Union, get_args, get_origin

from box import Box
from in_layers.core.models.protocols import (
    DatastoreValueType,
    EqualitySymbol,
    InLayersModel,
    ModelDefinition,
    ModelSearch,
    ModelSearchResult,
    PrimaryKeyType,
    PropertyQuery,
    QueryTokens,
    SortOrder,
)
from in_layers.core.models.query import (
    is_link_token,
    is_property_based_query,
    validate_model_search,
)
from pydantic import BaseModel

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_CAMEL_CASE_RE = re.compile(r"(?<!^)(?=[A-Z])")
_TEXT_ESCAPE_RE = re.compile(r"[\\]")
_TAG_ESCAPE_RE = re.compile(r"[{}|\\,\-@:'\"\s]")
_DEFAULT_REDIS_SEARCH_TAKE = 10_000
_STRING_FIELD = "string"
_NUMBER_FIELD = "number"
_BOOLEAN_FIELD = "boolean"
_DATE_FIELD = "date"


def _ascii_lower(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_bytes = normalized.encode("ascii", "ignore")
    return ascii_bytes.decode("ascii").lower()


def _camel_to_kebab(value: str) -> str:
    return _CAMEL_CASE_RE.sub("-", value)


def _to_kebab(value: str) -> str:
    kebab = _camel_to_kebab(value).replace("_", "-").replace("/", "-")
    kebab = _ascii_lower(kebab)
    kebab = _NON_ALNUM_RE.sub("-", kebab)
    return kebab.strip("-")


def get_key_prefix_for_model_definition(model_definition: ModelDefinition) -> str:
    domain_part = _to_kebab(model_definition.domain)
    plural_name_part = _to_kebab(model_definition.plural_name)
    return "-".join(part for part in [domain_part, plural_name_part] if part)


def get_key_prefix_for_model(model: InLayersModel) -> str:
    return get_key_prefix_for_model_definition(model.get_model_definition())


def create_connection_url(args: Mapping[str, Any]) -> str:
    host = args.get("host") or "127.0.0.1"
    port = args.get("port") or 6379
    username = args.get("username")
    password = args.get("password")
    credentials = ""
    if username:
        credentials = f"{username}:{password or ''}@"
    return f"redis://{credentials}{host}:{port}"


def get_key(model_prefix: str, primary_key: PrimaryKeyType) -> str:
    return f"{model_prefix}:{primary_key}"


def get_search_index_name(key_prefix: str) -> str:
    return f"idx:{key_prefix}"


def get_search_document_prefix(key_prefix: str) -> str:
    return f"searchdoc:{key_prefix}:"


def get_search_document_key(key_prefix: str, primary_key: PrimaryKeyType) -> str:
    return f"{get_search_document_prefix(key_prefix)}{primary_key}"


def _normalize_storage_value(value: Any) -> Any:
    normalized = value
    if isinstance(value, BaseModel):
        normalized = normalize_for_storage(value.model_dump())
    elif isinstance(value, Mapping):
        normalized = {
            str(key): _normalize_storage_value(inner_value)
            for key, inner_value in value.items()
        }
    elif isinstance(value, (list, tuple, set)):
        normalized = [_normalize_storage_value(inner_value) for inner_value in value]
    elif isinstance(value, (datetime, date)):
        normalized = value.isoformat()
    return normalized


def normalize_for_storage(data: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _normalize_storage_value(value) for key, value in data.items()}


def dump_json(data: Mapping[str, Any]) -> str:
    return json.dumps(normalize_for_storage(data))


def load_json(value: str | bytes | None) -> dict[str, Any] | None:
    if value is None:
        return None
    raw = value.decode() if isinstance(value, bytes) else value
    return json.loads(raw)


def _escape_tag_value(value: str) -> str:
    return _TAG_ESCAPE_RE.sub(lambda match: f"\\{match.group(0)}", value)


def _escape_text_value(value: str) -> str:
    return _TEXT_ESCAPE_RE.sub(lambda match: f"\\{match.group(0)}", value)


def _to_timestamp(value: Any) -> int:
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time()).timestamp() * 1000)
    return int(
        datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000
    )


def _unwrap_annotation(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin is None:
        return annotation
    if origin in {UnionType, Union}:
        args = [arg for arg in get_args(annotation) if arg is not NoneType]
        if len(args) == 1:
            return _unwrap_annotation(args[0])
        return annotation
    if str(origin).endswith("Annotated"):
        args = get_args(annotation)
        if args:
            return _unwrap_annotation(args[0])
    return annotation


def _field_type_from_annotation(annotation: Any) -> str:
    unwrapped = _unwrap_annotation(annotation)
    if unwrapped in {datetime, date}:
        return _DATE_FIELD
    if unwrapped is bool:
        return _BOOLEAN_FIELD
    if unwrapped in {int, float}:
        return _NUMBER_FIELD
    return _STRING_FIELD


def _field_type_from_value(value: Any) -> str:
    if isinstance(value, bool):
        return _BOOLEAN_FIELD
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _NUMBER_FIELD
    if isinstance(value, (datetime, date)):
        return _DATE_FIELD
    if isinstance(value, str):
        try:
            _to_timestamp(value)
            return _DATE_FIELD
        except (TypeError, ValueError):
            pass
    return _STRING_FIELD


def _get_model_class(model: InLayersModel) -> type[BaseModel] | None:
    model_cls = getattr(model, "_InLayersModelImpl__model", None)
    if isinstance(model_cls, type) and issubclass(model_cls, BaseModel):
        return model_cls
    return None


def _get_field_types(
    model: InLayersModel, sample_data: Mapping[str, Any] | None = None
) -> dict[str, str]:
    model_cls = _get_model_class(model)
    if model_cls is not None:
        field_types = {
            field_name: _field_type_from_annotation(field_info.annotation)
            for field_name, field_info in model_cls.model_fields.items()
        }
        if sample_data is None:
            return field_types
        for field_name, field_value in sample_data.items():
            key = str(field_name)
            inferred = _field_type_from_value(field_value)
            if key not in field_types or (
                field_types[key] == _STRING_FIELD and inferred != _STRING_FIELD
            ):
                field_types[key] = inferred
        return field_types
    if sample_data is None:
        return {}
    return {
        str(field_name): _field_type_from_value(field_value)
        for field_name, field_value in sample_data.items()
    }


def to_redis_search_schema_args(
    model: InLayersModel, sample_data: Mapping[str, Any] | None = None
) -> list[str]:
    field_types = _get_field_types(model, sample_data)
    schema_args: list[str] = []
    for key, field_type in field_types.items():
        if field_type == _DATE_FIELD:
            schema_args.extend([f"{key}__ts", "NUMERIC", "SORTABLE"])
            continue
        if field_type == _NUMBER_FIELD:
            schema_args.extend([key, "NUMERIC", "SORTABLE"])
            continue
        if field_type == _BOOLEAN_FIELD:
            schema_args.extend([key, "TAG", "SORTABLE"])
            continue
        schema_args.extend([f"{key}__tag", "TAG", "SORTABLE", f"{key}__text", "TEXT"])
    return schema_args


def _to_sort_field(model: InLayersModel, key: str) -> str:
    field_type = _get_field_types(model).get(key, _STRING_FIELD)
    if field_type == _DATE_FIELD:
        return f"{key}__ts"
    if field_type in {_NUMBER_FIELD, _BOOLEAN_FIELD}:
        return key
    return f"{key}__tag"


def _string_property_query_to_redis_search(query: PropertyQuery) -> str:
    value = "" if query.value is None else str(query.value)
    starts_with = bool(query.options.starts_with)
    ends_with = bool(query.options.ends_with)
    includes = bool(query.options.includes)

    if query.equality_symbol == EqualitySymbol.ne:
        escaped = _escape_tag_value(value)
        return f"-@{query.key}__tag:{{{escaped}}}"

    if starts_with or ends_with or includes:
        escaped = _escape_tag_value(value)
        prefix = "*" if ends_with or includes else ""
        suffix = "*" if starts_with or includes else ""
        return f"@{query.key}__tag:{{{prefix}{escaped}{suffix}}}"

    escaped = _escape_tag_value(value)
    return f"@{query.key}__tag:{{{escaped}}}"


def _numeric_property_query_to_redis_search(query: PropertyQuery) -> str:
    value = (
        _to_timestamp(query.value)
        if query.value_type == DatastoreValueType.date
        else float(query.value)
    )
    field = (
        f"{query.key}__ts" if query.value_type == DatastoreValueType.date else query.key
    )
    if query.equality_symbol == EqualitySymbol.eq:
        return f"@{field}:[{value} {value}]"
    if query.equality_symbol == EqualitySymbol.ne:
        return f"-@{field}:[{value} {value}]"
    if query.equality_symbol == EqualitySymbol.gt:
        return f"@{field}:[({value} +inf]"
    if query.equality_symbol == EqualitySymbol.gte:
        return f"@{field}:[{value} +inf]"
    if query.equality_symbol == EqualitySymbol.lt:
        return f"@{field}:[-inf ({value}]"
    if query.equality_symbol == EqualitySymbol.lte:
        return f"@{field}:[-inf {value}]"
    raise ValueError(f"Unsupported numeric equality symbol: {query.equality_symbol}")


def _boolean_property_query_to_redis_search(query: PropertyQuery) -> str:
    value = "true" if bool(query.value) else "false"
    if query.equality_symbol == EqualitySymbol.ne:
        return f"-@{query.key}:{{{value}}}"
    return f"@{query.key}:{{{value}}}"


def _property_query_to_redis_search(query: PropertyQuery) -> str:
    if query.value_type == DatastoreValueType.string:
        return _string_property_query_to_redis_search(query)
    if query.value_type in {DatastoreValueType.number, DatastoreValueType.date}:
        return _numeric_property_query_to_redis_search(query)
    if query.value_type == DatastoreValueType.boolean:
        return _boolean_property_query_to_redis_search(query)
    raise ValueError(f"Unsupported Redis Stack value type: {query.value_type}")


def _dates_query_to_redis_search(query: Any) -> str:
    field = f"{query.key}__ts"
    value = _to_timestamp(query.date)
    if query.type == "datesBefore":
        max_value = f"{value}" if query.options.equal_to_and_before else f"({value}"
        return f"@{field}:[-inf {max_value}]"
    min_value = f"{value}" if query.options.equal_to_and_after else f"({value}"
    return f"@{field}:[{min_value} +inf]"


def _tokens_to_redis_search(token: QueryTokens) -> str:
    if isinstance(token, list):
        if len(token) < 1:
            return "*"
        if all(is_link_token(inner) is False for inner in token):
            terms = [_tokens_to_redis_search(inner) for inner in token]
            return f"({' '.join(terms)})"
        first, *rest = token
        built = _tokens_to_redis_search(first)
        for index in range(0, len(rest), 2):
            link = rest[index]
            next_token = rest[index + 1] if index + 1 < len(rest) else None
            if next_token is None:
                continue
            next_expr = _tokens_to_redis_search(next_token)
            if str(link).upper() == "OR":
                built = f"({built})|({next_expr})"
            else:
                built = f"({built} {next_expr})"
        return built
    if is_property_based_query(token):
        if token.type == "property":
            return _property_query_to_redis_search(token)
        if token.type in {"datesBefore", "datesAfter"}:
            return _dates_query_to_redis_search(token)
    raise ValueError("Unsupported query token for Redis Stack search")


def to_redis_search_query(search: ModelSearch) -> str:
    validate_model_search(search)
    if not search.query:
        return "*"
    return _tokens_to_redis_search(search.query)


def to_redis_search_sort_args(model: InLayersModel, search: ModelSearch) -> list[str]:
    if not search.sort:
        return []
    direction = "DESC" if search.sort.order == SortOrder.dsc else "ASC"
    return ["SORTBY", _to_sort_field(model, search.sort.key), direction]


def to_redis_search_limit_args(search: ModelSearch) -> list[str]:
    take = search.take or _DEFAULT_REDIS_SEARCH_TAKE
    return ["LIMIT", "0", str(take)]


def to_redis_search_hash_document(
    model: InLayersModel, data: Mapping[str, Any]
) -> dict[str, str | int | float]:
    normalized_data = normalize_for_storage(data)
    field_types = _get_field_types(model, normalized_data)
    search_doc: dict[str, str | int | float] = {
        "__raw": json.dumps(normalized_data),
    }
    for key, value in normalized_data.items():
        if value is None:
            continue
        field_type = field_types.get(key, _field_type_from_value(value))
        if field_type == _DATE_FIELD:
            search_doc[f"{key}__ts"] = _to_timestamp(value)
            continue
        if field_type == _NUMBER_FIELD:
            search_doc[key] = float(value)
            continue
        if field_type == _BOOLEAN_FIELD:
            search_doc[key] = "true" if bool(value) else "false"
            continue
        search_doc[f"{key}__tag"] = str(value)
        search_doc[f"{key}__text"] = str(value)
    return search_doc


def _append_loaded_instance(
    instances: list[dict[str, Any]], raw_value: str | bytes | None
) -> None:
    loaded = load_json(raw_value)
    if loaded is not None:
        instances.append(loaded)


def _from_structured_redis_search_response(
    response: Mapping[str, Any],
) -> list[dict[str, Any]]:
    instances: list[dict[str, Any]] = []
    for result in response.get("results", []):
        extra_attributes = result.get("extra_attributes", {})
        _append_loaded_instance(instances, extra_attributes.get("__raw"))
    return instances


def _find_legacy_raw_value(raw_doc: list[Any]) -> str | bytes | None:
    for raw_index in range(0, len(raw_doc), 2):
        if str(raw_doc[raw_index]) != "__raw":
            continue
        if raw_index + 1 >= len(raw_doc):
            continue
        return raw_doc[raw_index + 1]
    return None


def _from_legacy_redis_search_response(response: list[Any]) -> list[dict[str, Any]]:
    instances: list[dict[str, Any]] = []
    rows = response[1:]
    for index in range(1, len(rows), 2):
        raw_doc = rows[index]
        if not isinstance(raw_doc, list):
            continue
        _append_loaded_instance(instances, _find_legacy_raw_value(raw_doc))
    return instances


def from_redis_search_response(response: Any) -> ModelSearchResult:
    if isinstance(response, dict):
        return Box(
            instances=_from_structured_redis_search_response(response),
            page=None,
        )
    if not isinstance(response, list) or len(response) < 1:
        return Box(instances=[], page=None)
    return Box(instances=_from_legacy_redis_search_response(response), page=None)
