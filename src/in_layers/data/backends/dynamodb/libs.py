"""Pure functional utilities for DynamoDB query conversion and data formatting."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from in_layers.core.models.protocols import ModelDefinition


def get_table_name_for_model(model_definition: ModelDefinition) -> str:
    """Generate a DynamoDB table name from a model definition."""
    name = model_definition.plural_name.replace("@", "").replace("/", "-")
    # Convert to kebab-case: insert hyphens before uppercase letters (except first)
    # and handle sequences of uppercase letters
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", name)
    return name.lower()


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
    but we ensure datetime objects are converted to ISO format strings.
    """
    result = dict(data)
    # Convert datetime objects to ISO format strings for DynamoDB

    for key, value in result.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
    return result


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
