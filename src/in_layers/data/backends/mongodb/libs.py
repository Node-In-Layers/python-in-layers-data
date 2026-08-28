"""Pure functional utilities for MongoDB query conversion and data formatting."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from in_layers.core.models.protocols import (
    BooleanQuery,
    DatastoreValueType,
    EqualitySymbol,
    ModelDefinition,
    PropertyQuery,
    QueryTokens,
)


def get_collection_name_for_model(model_definition: ModelDefinition) -> str:
    """Generate a MongoDB collection name from a model definition."""
    name = model_definition.plural_name.replace("@", "").replace("/", "-")
    # Convert to kebab-case: insert hyphens before uppercase letters (except first)
    # and handle sequences of uppercase letters
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", name)
    return f"{name}".lower()


def escape_regex(s: str) -> str:
    """Escape special regex characters in a string."""
    return re.escape(s)


def build_string_pattern(
    raw: str, starts_with: bool, ends_with: bool, includes: bool
) -> str:
    """Build a regex pattern for string matching."""
    escaped = escape_regex(raw)
    if starts_with:
        return f"^{escaped}"
    if ends_with:
        return f"{escaped}$"
    if includes:
        return escaped
    # default: exact match
    return f"^{escaped}$"


def regex_object_for_pattern(pattern: str, case_sensitive: bool) -> dict[str, Any]:
    """Create a MongoDB regex object from a pattern."""
    if case_sensitive:
        return {"$regex": pattern}
    return {"$regex": pattern, "$options": "i"}


def build_mongo_find_value(query: PropertyQuery) -> dict[str, Any]:  # noqa: PLR0911
    """Convert a PropertyQuery to a MongoDB query value."""
    value = query.value
    if value is None:
        return {query.key: None}

    # Handle date objects
    if hasattr(value, "isoformat"):  # datetime objects
        return {query.key: value}

    if query.value_type == DatastoreValueType.string:
        case_sensitive = bool(query.options.case_sensitive)
        starts_with = bool(query.options.starts_with)
        ends_with = bool(query.options.ends_with)
        includes = bool(query.options.includes)

        if query.equality_symbol not in (EqualitySymbol.eq, EqualitySymbol.ne):
            raise ValueError(
                f"Symbol {query.equality_symbol} is unhandled for string type"
            )

        raw = str(value)
        pattern = build_string_pattern(raw, starts_with, ends_with, includes)
        regex_obj = regex_object_for_pattern(pattern, case_sensitive)

        if query.equality_symbol == EqualitySymbol.ne:
            is_plain_exact = (
                not starts_with and not ends_with and not includes and case_sensitive
            )
            if is_plain_exact:
                return {query.key: {"$ne": raw}}
            return {query.key: {"$not": regex_obj}}

        use_regex = starts_with or ends_with or includes or not case_sensitive
        if use_regex:
            return {query.key: regex_obj}
        return {query.key: raw}

    if query.value_type == DatastoreValueType.number:
        equality_symbol_to_mongo = {
            EqualitySymbol.eq: "$eq",
            EqualitySymbol.gt: "$gt",
            EqualitySymbol.gte: "$gte",
            EqualitySymbol.lt: "$lt",
            EqualitySymbol.lte: "$lte",
            EqualitySymbol.ne: "$ne",
        }
        mongo_symbol = equality_symbol_to_mongo.get(query.equality_symbol)
        if not mongo_symbol:
            raise ValueError(f"Symbol {query.equality_symbol} is unhandled")
        return {query.key: {mongo_symbol: query.value}}

    return {query.key: value}


def threeitize(
    data: list[QueryTokens],
) -> list[tuple[QueryTokens, BooleanQuery, QueryTokens]]:
    """Convert a list of tokens into three-tuples of (left, link, right)."""
    if len(data) in (0, 1):
        return []
    if len(data) % 2 == 0:
        raise ValueError("Must be an odd number of 3 or greater.")
    three = (data[0], _as_link(data[1]), data[2])
    rest = data[2:]
    more = threeitize(rest)
    return [three, *more]


def _as_link(value: QueryTokens) -> BooleanQuery:
    """Convert a token to a BooleanQuery link."""
    if value in {"AND", "OR"}:
        return value
    raise ValueError("Must have AND/OR between statements")


def process_mongo_array(
    tokens: list[QueryTokens],
) -> dict[str, Any]:
    """Process an array of query tokens into a MongoDB query."""
    # If we don't have any AND/OR, it's all an AND
    if all(t != "AND" and t != "OR" for t in tokens):  # noqa: PLR1714
        return {"$and": [handle_mongo_query(t) for t in tokens]}

    # Process with threeitize
    threes = threeitize(tokens)
    threes.reverse()
    result: dict[str, Any] = {}
    for a, link, b in threes:
        a_query = handle_mongo_query(a)
        if result:
            result = {f"${link.lower()}": [a_query, result]}
        else:
            b_query = handle_mongo_query(b)
            result = {f"${link.lower()}": [a_query, b_query]}
    return result


def handle_mongo_query(token: QueryTokens | list[QueryTokens]) -> dict[str, Any]:
    """Convert a query token to a MongoDB query object."""
    # Handle list of tokens (the main query)
    if isinstance(token, list):
        return process_mongo_array(token)

    # Check by shape (duck typing) rather than isinstance
    # PropertyQuery has type="property" and value attribute
    if (
        hasattr(token, "type")
        and getattr(token, "type", None) == "property"
        and hasattr(token, "value")
    ):
        return build_mongo_find_value(token)

    # DatesBeforeQuery has type="datesBefore" and date attribute
    if (
        hasattr(token, "type")
        and getattr(token, "type", None) == "datesBefore"
        and hasattr(token, "date")
    ):
        date_value = token.date
        if (
            hasattr(token, "value_type") and token.value_type == DatastoreValueType.date
        ) and isinstance(date_value, str):
            # Convert string to datetime if needed
            date_value = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
        operator = (
            "$lte"
            if (hasattr(token, "options") and token.options.equal_to_and_before)
            else "$lt"
        )
        return {token.key: {operator: date_value}}

    # DatesAfterQuery has type="datesAfter" and date attribute
    if (
        hasattr(token, "type")
        and getattr(token, "type", None) == "datesAfter"
        and hasattr(token, "date")
    ):
        date_value = token.date
        if (
            hasattr(token, "value_type") and token.value_type == DatastoreValueType.date
        ) and isinstance(date_value, str):
            date_value = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
        operator = (
            "$gte"
            if (hasattr(token, "options") and token.options.equal_to_and_after)
            else "$gt"
        )
        return {token.key: {operator: date_value}}

    raise ValueError(f"Unhandled query token {token}")


def to_mongo(query: list[QueryTokens]) -> list[dict[str, Any]]:
    """Convert a query list to MongoDB aggregation pipeline stages."""
    if not query:
        return [{"$match": {}}]
    # Pass the list directly to handle_mongo_query, which will process it as an array
    match_query = handle_mongo_query(query)
    return [{"$match": match_query}]


def convert_decimals_to_float(value: Any) -> Any:
    """Recursively convert Decimal values to float for MongoDB serialization.

    MongoDB cannot serialize Decimal objects, so we need to convert them to float.
    This function walks through nested structures (dicts, lists, etc.) and converts
    any Decimal values it finds.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: convert_decimals_to_float(v) for k, v in value.items()}
    if isinstance(value, list):
        return [convert_decimals_to_float(item) for item in value]
    if isinstance(value, tuple):
        return tuple(convert_decimals_to_float(item) for item in value)
    return value


def format_for_mongo(data: Mapping[str, Any]) -> dict[str, Any]:
    """Format data for MongoDB storage, converting dates, decimals, and other types."""
    result = dict(data)
    # Convert datetime objects (they're already in the right format for MongoDB)
    # In the TypeScript version, this iterates over model properties to find Datetime types
    # For Python, we'll preserve datetime objects as-is (MongoDB handles them natively)
    # and convert string ISO dates if they're clearly datetime values
    for key, value in result.items():
        if isinstance(value, datetime):
            result[key] = value
        else:
            # Convert any Decimal values to float (recursively)
            result[key] = convert_decimals_to_float(value)
    return result
