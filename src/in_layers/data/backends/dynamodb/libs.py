"""Pure functional utilities for DynamoDB query conversion and data formatting."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from box import Box
from in_layers.core.models.protocols import ModelDefinition
from pydantic import BaseModel


def _plainify_for_dynamodb(value: Any) -> Any:
    """
    Recursively convert application objects into DynamoDB-friendly Python types.

    Handles:
    - Pydantic BaseModel instances
    - Dataclasses (including Pydantic dataclasses)
    - Box instances
    - Mappings / sequences
    Leaves scalars (str, int, Decimal, bool, None, datetime, etc.) as-is; later
    steps will normalize datetimes/floats.
    """
    # Pydantic BaseModel
    if isinstance(value, BaseModel):
        # mode="python" keeps types (e.g. datetime) which we normalize later
        return _plainify_for_dynamodb(value.model_dump(mode="python"))

    # Dataclasses (including Pydantic dataclasses)
    if is_dataclass(value):
        return _plainify_for_dynamodb(asdict(value))

    # Box → dict
    if isinstance(value, Box):
        return _plainify_for_dynamodb(dict(value))

    # Mapping (but not already Box)
    if isinstance(value, Mapping):
        return {k: _plainify_for_dynamodb(v) for k, v in value.items()}

    # Lists / tuples / sets
    if isinstance(value, (list, tuple, set)):
        return [_plainify_for_dynamodb(v) for v in value]

    # Scalars and anything else we don't specially handle
    return value


def _convert_datetimes_to_iso(obj: Any) -> Any:
    """Recursively convert datetime objects to ISO strings."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _convert_datetimes_to_iso(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_datetimes_to_iso(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_convert_datetimes_to_iso(v) for v in obj)
    if isinstance(obj, set):
        return {_convert_datetimes_to_iso(v) for v in obj}
    return obj


def get_table_name_for_model(
    environment: str, model_definition: ModelDefinition
) -> str:
    """Generate a DynamoDB table name from a model definition."""
    name = model_definition.plural_name.replace("@", "").replace("/", "-")
    # Convert to kebab-case: insert hyphens before uppercase letters (except first)
    # and handle sequences of uppercase letters
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", name)
    return f"{name}-{environment}".lower()


def convert_all_floats_to_decimals(obj: Any) -> Any:
    """
    Recursively convert all float values in a nested structure to Decimal.
    This is useful for preparing data for DynamoDB, which requires numbers to be
    represented as Decimals to avoid precision issues.

    Args:
        obj: The input object, which can be a dict, list, float, or other types.
    Returns:
        The modified object with all float values converted to Decimal.
    """
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: convert_all_floats_to_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_all_floats_to_decimals(item) for item in obj]
    return obj


def format_for_dynamodb(data: Mapping[str, Any]) -> dict[str, Any]:
    """Format data for DynamoDB storage.

    DynamoDB natively handles:
    - Strings
    - Numbers (int, float, Decimal)
    - Binary data
    - Boolean
    - Null
    - Lists
    - Maps (dicts)
    - Sets (string sets, number sets, binary sets)

    The boto3 DynamoDBDocumentClient will handle conversion automatically,
    but we ensure:
    - Custom objects (Pydantic models, dataclasses, Box) are converted to plain
      Python structures
    - Datetime objects (at any depth) are converted to ISO format strings
    - Floats are converted to Decimal for numeric safety
    """
    # First, plainify anything complex (ErrorObject/ErrorDetails, etc.)
    plain = _plainify_for_dynamodb(data)
    # Then, normalize datetimes recursively
    with_dates = _convert_datetimes_to_iso(plain)
    # Finally, convert floats to Decimals
    return convert_all_floats_to_decimals(with_dates)


def from_dynamodb(item: dict[str, Any] | None) -> dict[str, Any]:
    """Convert a DynamoDB item to a plain dictionary.

    The boto3 DynamoDBDocumentClient already converts AttributeValue format
    to native Python types, so this is mainly for consistency and future-proofing.
    """
    if item is None:
        return {}
    return dict(item)


def build_scan_params(
    table_name: str, exclusive_start_key: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build parameters for a DynamoDB Scan operation."""
    params: dict[str, Any] = {
        "TableName": table_name,
    }
    if exclusive_start_key:
        params["ExclusiveStartKey"] = exclusive_start_key
    return params


def split_array_into_batches(array: list[Any], max_batch_size: int) -> list[list[Any]]:
    """Split an array into batches of maximum size.

    DynamoDB has limits on batch operations (e.g., BatchWriteItem max 25 items).
    """
    if not isinstance(array, list):
        raise ValueError("Input must be a list")
    if max_batch_size < 1:
        raise ValueError("max_batch_size must be at least 1")

    batches = []
    for i in range(0, len(array), max_batch_size):
        batches.append(array[i : i + max_batch_size])
    return batches
