"""Unit tests for MongoDB libs module."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from box import Box

from in_layers.core.models.protocols import (
    DatastoreValueType,
    EqualitySymbol,
    PropertyOptions,
    _DatesAfterOptions,
    _DatesBeforeOptions,
    DatesAfterQuery,
    DatesBeforeQuery,
    PropertyQuery,
)
from in_layers.data.backends.mongodb.libs import (
    _as_link,
    build_mongo_find_value,
    build_string_pattern,
    escape_regex,
    format_for_mongo,
    get_collection_name_for_model,
    handle_mongo_query,
    process_mongo_array,
    regex_object_for_pattern,
    threeitize,
    to_mongo,
)


class _StubModelDefinition:
    """Stub model definition for testing."""

    def __init__(self, plural_name: str = "MyPluralNames"):
        self.plural_name = plural_name


class TestGetCollectionNameForModel:
    """Tests for get_collection_name_for_model."""

    def test_should_get_expected_name(self):
        """Should convert model name to kebab-case."""
        model_def = _StubModelDefinition("MyPluralNames")
        actual = get_collection_name_for_model(model_def)
        expected = "my-plural-names"
        assert actual == expected

    def test_should_handle_camel_case(self):
        """Should handle camelCase names."""
        model_def = _StubModelDefinition("UserAccounts")
        actual = get_collection_name_for_model(model_def)
        expected = "user-accounts"
        assert actual == expected

    def test_should_remove_at_symbols(self):
        """Should remove @ symbols from names."""
        model_def = _StubModelDefinition("@My@Model@")
        actual = get_collection_name_for_model(model_def)
        expected = "my-model"
        assert actual == expected

    def test_should_replace_slashes(self):
        """Should replace / with - in names."""
        model_def = _StubModelDefinition("My/Model/Name")
        actual = get_collection_name_for_model(model_def)
        expected = "my-model-name"
        assert actual == expected


class TestEscapeRegex:
    """Tests for escape_regex."""

    def test_should_escape_special_characters(self):
        """Should escape regex special characters."""
        input_str = "test.*+?^${}()|[]\\"
        actual = escape_regex(input_str)
        # Should escape all special regex characters
        assert "\\." in actual
        assert "\\*" in actual
        assert "\\+" in actual

    def test_should_handle_plain_string(self):
        """Should handle plain strings without special characters."""
        input_str = "plaintext"
        actual = escape_regex(input_str)
        assert actual == "plaintext"


class TestBuildStringPattern:
    """Tests for build_string_pattern."""

    def test_should_build_starts_with_pattern(self):
        """Should build pattern for starts_with."""
        actual = build_string_pattern(
            "test", starts_with=True, ends_with=False, includes=False
        )
        assert actual == "^test"

    def test_should_build_ends_with_pattern(self):
        """Should build pattern for ends_with."""
        actual = build_string_pattern(
            "test", starts_with=False, ends_with=True, includes=False
        )
        assert actual == "test$"

    def test_should_build_includes_pattern(self):
        """Should build pattern for includes."""
        actual = build_string_pattern(
            "test", starts_with=False, ends_with=False, includes=True
        )
        assert actual == "test"

    def test_should_build_exact_match_pattern(self):
        """Should build pattern for exact match (default)."""
        actual = build_string_pattern(
            "test", starts_with=False, ends_with=False, includes=False
        )
        assert actual == "^test$"

    def test_should_escape_special_chars_in_pattern(self):
        """Should escape special characters in pattern."""
        actual = build_string_pattern(
            "test.*", starts_with=True, ends_with=False, includes=False
        )
        assert "\\." in actual
        assert "\\*" in actual


class TestRegexObjectForPattern:
    """Tests for regex_object_for_pattern."""

    def test_should_create_case_sensitive_regex(self):
        """Should create regex without options for case sensitive."""
        actual = regex_object_for_pattern("^test$", case_sensitive=True)
        expected = {"$regex": "^test$"}
        assert actual == expected

    def test_should_create_case_insensitive_regex(self):
        """Should create regex with 'i' option for case insensitive."""
        actual = regex_object_for_pattern("^test$", case_sensitive=False)
        expected = {"$regex": "^test$", "$options": "i"}
        assert actual == expected


class TestBuildMongoFindValue:
    """Tests for build_mongo_find_value."""

    def test_should_handle_null_value(self):
        """Should handle null/None values."""
        query = PropertyQuery(
            type="property",
            key="test",
            value=None,
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": None}
        assert actual == expected

    def test_should_handle_datetime_object(self):
        """Should handle datetime objects."""
        the_date = datetime(2020, 1, 1, 0, 0, 0)
        query = PropertyQuery(
            type="property",
            key="test",
            value=the_date,
            value_type=DatastoreValueType.date,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": the_date}
        assert actual == expected

    def test_should_handle_string_exact_match_case_insensitive(self):
        """Should handle string exact match (case insensitive by default)."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(case_sensitive=False),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": {"$regex": "^value1$", "$options": "i"}}
        assert actual == expected

    def test_should_handle_string_exact_match_case_sensitive(self):
        """Should handle string exact match (case sensitive)."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(case_sensitive=True),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": "value1"}
        assert actual == expected

    def test_should_handle_string_starts_with(self):
        """Should handle starts_with option."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(starts_with=True),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": {"$regex": "^value1", "$options": "i"}}
        assert actual == expected

    def test_should_handle_string_ends_with(self):
        """Should handle ends_with option."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(ends_with=True),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": {"$regex": "value1$", "$options": "i"}}
        assert actual == expected

    def test_should_handle_string_includes(self):
        """Should handle includes option."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(includes=True),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": {"$regex": "value1", "$options": "i"}}
        assert actual == expected

    def test_should_handle_string_starts_with_case_sensitive(self):
        """Should handle starts_with with case sensitive."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(starts_with=True, case_sensitive=True),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": {"$regex": "^value1"}}
        assert actual == expected

    def test_should_handle_string_ends_with_case_sensitive(self):
        """Should handle ends_with with case sensitive."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(ends_with=True, case_sensitive=True),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": {"$regex": "value1$"}}
        assert actual == expected

    def test_should_handle_string_not_equals_plain_exact(self):
        """Should handle not-equals with plain exact match (case sensitive)."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.ne,
            options=PropertyOptions(case_sensitive=True),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": {"$ne": "value1"}}
        assert actual == expected

    def test_should_handle_string_not_equals_with_includes(self):
        """Should handle not-equals with includes using $not and regex."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.ne,
            options=PropertyOptions(includes=True),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": {"$not": {"$regex": "value1", "$options": "i"}}}
        assert actual == expected

    def test_should_throw_for_unsupported_equality_symbol_on_strings(self):
        """Should throw for unsupported equality symbols on strings."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.gt,
            options=PropertyOptions(),
        )
        with pytest.raises(ValueError, match="Symbol .* is unhandled for string type"):
            build_mongo_find_value(query)

    def test_should_handle_number_with_eq(self):
        """Should handle number with equals."""
        query = PropertyQuery(
            type="property",
            key="test",
            value=5,
            value_type=DatastoreValueType.number,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": {"$eq": 5}}
        assert actual == expected

    def test_should_handle_number_with_gt(self):
        """Should handle number with greater than."""
        query = PropertyQuery(
            type="property",
            key="test",
            value=5,
            value_type=DatastoreValueType.number,
            equality_symbol=EqualitySymbol.gt,
            options=PropertyOptions(),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": {"$gt": 5}}
        assert actual == expected

    def test_should_handle_number_with_gte(self):
        """Should handle number with greater than or equal."""
        query = PropertyQuery(
            type="property",
            key="test",
            value=5,
            value_type=DatastoreValueType.number,
            equality_symbol=EqualitySymbol.gte,
            options=PropertyOptions(),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": {"$gte": 5}}
        assert actual == expected

    def test_should_handle_number_with_lt(self):
        """Should handle number with less than."""
        query = PropertyQuery(
            type="property",
            key="test",
            value=5,
            value_type=DatastoreValueType.number,
            equality_symbol=EqualitySymbol.lt,
            options=PropertyOptions(),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": {"$lt": 5}}
        assert actual == expected

    def test_should_handle_number_with_lte(self):
        """Should handle number with less than or equal."""
        query = PropertyQuery(
            type="property",
            key="test",
            value=5,
            value_type=DatastoreValueType.number,
            equality_symbol=EqualitySymbol.lte,
            options=PropertyOptions(),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": {"$lte": 5}}
        assert actual == expected

    def test_should_handle_number_with_ne(self):
        """Should handle number with not equals."""
        query = PropertyQuery(
            type="property",
            key="test",
            value=5,
            value_type=DatastoreValueType.number,
            equality_symbol=EqualitySymbol.ne,
            options=PropertyOptions(),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": {"$ne": 5}}
        assert actual == expected

    def test_should_throw_for_unhandled_equality_symbol_on_numbers(self):
        """Should throw for unhandled equality symbols on numbers."""
        # Create a manual PropertyQuery using Box to bypass frozen dataclass restriction
        # This allows us to test with an invalid equality_symbol value
        query = Box(
            type="property",
            key="test",
            value=5,
            value_type=DatastoreValueType.number,
            equality_symbol="==",  # Invalid symbol not in EqualitySymbol enum
            options=PropertyOptions(),
        )
        with pytest.raises(ValueError, match="Symbol .* is unhandled"):
            build_mongo_find_value(query)

    def test_should_handle_object_values(self):
        """Should handle object values (fallback case)."""
        query = PropertyQuery(
            type="property",
            key="test",
            value={"a": 1},
            value_type=DatastoreValueType.object,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        actual = build_mongo_find_value(query)
        expected = {"test": {"a": 1}}
        assert actual == expected


class TestHandleMongoQuery:
    """Tests for handle_mongo_query."""

    def test_should_handle_property_query(self):
        """Should handle a PropertyQuery."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        actual = handle_mongo_query(query)
        # Should return regex for case-insensitive string match
        assert "test" in actual
        assert "$regex" in actual["test"]

    def test_should_handle_dates_before_with_equal_to_and_before_false(self):
        """Should handle datesBefore with equalToAndBefore=false."""
        query = DatesBeforeQuery(
            type="datesBefore",
            key="my-key",
            date="2020-01-01",
            value_type=DatastoreValueType.string,
            options=_DatesBeforeOptions(equal_to_and_before=False),
        )
        actual = handle_mongo_query(query)
        expected = {"my-key": {"$lt": "2020-01-01"}}
        assert actual == expected

    def test_should_handle_dates_before_with_equal_to_and_before_true(self):
        """Should handle datesBefore with equalToAndBefore=true."""
        query = DatesBeforeQuery(
            type="datesBefore",
            key="my-key",
            date="2020-01-01",
            value_type=DatastoreValueType.string,
            options=_DatesBeforeOptions(equal_to_and_before=True),
        )
        actual = handle_mongo_query(query)
        expected = {"my-key": {"$lte": "2020-01-01"}}
        assert actual == expected

    def test_should_handle_dates_before_with_date_type(self):
        """Should handle datesBefore with date value type."""
        the_date = datetime(2020, 1, 1, 0, 0, 0)
        query = DatesBeforeQuery(
            type="datesBefore",
            key="my-key",
            date=the_date.isoformat(),
            value_type=DatastoreValueType.date,
            options=_DatesBeforeOptions(equal_to_and_before=False),
        )
        actual = handle_mongo_query(query)
        # Should convert ISO string to datetime
        assert "my-key" in actual
        assert "$lt" in actual["my-key"]

    def test_should_handle_dates_after_with_equal_to_and_after_false(self):
        """Should handle datesAfter with equalToAndAfter=false."""
        query = DatesAfterQuery(
            type="datesAfter",
            key="my-key",
            date="2020-01-01",
            value_type=DatastoreValueType.string,
            options=_DatesAfterOptions(equal_to_and_after=False),
        )
        actual = handle_mongo_query(query)
        expected = {"my-key": {"$gt": "2020-01-01"}}
        assert actual == expected

    def test_should_handle_dates_after_with_equal_to_and_after_true(self):
        """Should handle datesAfter with equalToAndAfter=true."""
        query = DatesAfterQuery(
            type="datesAfter",
            key="my-key",
            date="2020-01-01",
            value_type=DatastoreValueType.string,
            options=_DatesAfterOptions(equal_to_and_after=True),
        )
        actual = handle_mongo_query(query)
        expected = {"my-key": {"$gte": "2020-01-01"}}
        assert actual == expected

    def test_should_handle_dates_after_with_date_type(self):
        """Should handle datesAfter with date value type."""
        the_date = datetime(2020, 1, 1, 0, 0, 0)
        query = DatesAfterQuery(
            type="datesAfter",
            key="my-key",
            date=the_date.isoformat(),
            value_type=DatastoreValueType.date,
            options=_DatesAfterOptions(equal_to_and_after=False),
        )
        actual = handle_mongo_query(query)
        # Should convert ISO string to datetime
        assert "my-key" in actual
        assert "$gt" in actual["my-key"]

    def test_should_throw_for_unhandled_token(self):
        """Should throw for unhandled query token."""
        with pytest.raises(ValueError, match="Unhandled query token"):
            handle_mongo_query("invalid")  # type: ignore[arg-type]

    def test_should_raise_value_error_for_invalid_date_string_in_dates_before(self):
        """Should raise ValueError for invalid date string in datesBefore."""
        # Use Box to create query with invalid string date when value_type is date
        query = Box(
            type="datesBefore",
            key="my-key",
            date="completely-invalid-date-format-xyz",
            value_type=DatastoreValueType.date,
            options=_DatesBeforeOptions(equal_to_and_before=False),
        )
        with pytest.raises(ValueError, match="Invalid isoformat string"):
            handle_mongo_query(query)

    def test_should_raise_value_error_for_invalid_date_string_in_dates_after(self):
        """Should raise ValueError for invalid date string in datesAfter."""
        # Use Box to create query with invalid string date when value_type is date
        query = Box(
            type="datesAfter",
            key="my-key",
            date="completely-invalid-date-format-xyz",
            value_type=DatastoreValueType.date,
            options=_DatesAfterOptions(equal_to_and_after=False),
        )
        with pytest.raises(ValueError, match="Invalid isoformat string"):
            handle_mongo_query(query)

    def test_should_raise_value_error_for_invalid_iso_string_in_dates_before(self):
        """Should raise ValueError for invalid ISO string in datesBefore with equal_to_and_before=True."""
        query = Box(
            type="datesBefore",
            key="my-key",
            date="not-a-valid-iso-date-123",
            value_type=DatastoreValueType.date,
            options=_DatesBeforeOptions(equal_to_and_before=True),
        )
        with pytest.raises(ValueError, match="Invalid isoformat string"):
            handle_mongo_query(query)

    def test_should_raise_value_error_for_invalid_iso_string_in_dates_after(self):
        """Should raise ValueError for invalid ISO string in datesAfter with equal_to_and_after=True."""
        query = Box(
            type="datesAfter",
            key="my-key",
            date="not-a-valid-iso-date-123",
            value_type=DatastoreValueType.date,
            options=_DatesAfterOptions(equal_to_and_after=True),
        )
        with pytest.raises(ValueError, match="Invalid isoformat string"):
            handle_mongo_query(query)


class TestProcessMongoArray:
    """Tests for process_mongo_array."""

    def test_should_handle_simple_and_query(self):
        """Should handle a simple AND query."""
        query1 = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        query2 = PropertyQuery(
            type="property",
            key="test2",
            value="value2",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        tokens = [query1, "AND", query2]
        actual = process_mongo_array(tokens)
        assert "$and" in actual
        assert len(actual["$and"]) == 2

    def test_should_handle_simple_or_query(self):
        """Should handle a simple OR query."""
        query1 = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        query2 = PropertyQuery(
            type="property",
            key="test",
            value="value2",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        tokens = [query1, "OR", query2]
        actual = process_mongo_array(tokens)
        assert "$or" in actual
        assert len(actual["$or"]) == 2

    def test_should_handle_query_without_links_as_and(self):
        """Should handle queries without AND/OR links as AND."""
        query1 = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        query2 = PropertyQuery(
            type="property",
            key="test2",
            value="value2",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        tokens = [query1, query2]
        actual = process_mongo_array(tokens)
        assert "$and" in actual
        assert len(actual["$and"]) == 2

    def test_should_handle_complex_and_or_query(self):
        """Should handle a complex AND/OR query."""
        query1 = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        query2 = PropertyQuery(
            type="property",
            key="test",
            value="value2",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        query3 = PropertyQuery(
            type="property",
            key="prop2",
            value=2,
            value_type=DatastoreValueType.number,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        tokens = [query1, "OR", query2, "AND", query3]
        actual = process_mongo_array(tokens)
        # Should have $or at the top level
        assert "$or" in actual or "$and" in actual


class TestToMongo:
    """Tests for to_mongo."""

    def test_should_handle_empty_query(self):
        """Should handle empty query."""
        actual = to_mongo([])
        expected = [{"$match": {}}]
        assert actual == expected

    def test_should_handle_null_property_query(self):
        """Should handle null property query."""
        query = PropertyQuery(
            type="property",
            key="test",
            value=None,
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        actual = to_mongo([query])
        expected = [{"$match": {"$and": [{"test": None}]}}]
        assert actual == expected

    def test_should_handle_number_with_gt(self):
        """Should handle number with greater than."""
        query = PropertyQuery(
            type="property",
            key="test",
            value=5,
            value_type=DatastoreValueType.number,
            equality_symbol=EqualitySymbol.gt,
            options=PropertyOptions(),
        )
        actual = to_mongo([query])
        expected = [{"$match": {"$and": [{"test": {"$gt": 5}}]}}]
        assert actual == expected

    def test_should_handle_number_with_eq(self):
        """Should handle number with equals."""
        query = PropertyQuery(
            type="property",
            key="test",
            value=5,
            value_type=DatastoreValueType.number,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        actual = to_mongo([query])
        expected = [{"$match": {"$and": [{"test": {"$eq": 5}}]}}]
        assert actual == expected

    def test_should_handle_string_case_sensitive(self):
        """Should handle case sensitive string."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(case_sensitive=True),
        )
        actual = to_mongo([query])
        expected = [{"$match": {"$and": [{"test": "value1"}]}}]
        assert actual == expected

    def test_should_handle_string_ends_with(self):
        """Should handle endsWith option."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(ends_with=True),
        )
        actual = to_mongo([query])
        assert actual[0]["$match"]["$and"][0]["test"]["$regex"] == "value1$"
        assert actual[0]["$match"]["$and"][0]["test"]["$options"] == "i"

    def test_should_handle_string_starts_with(self):
        """Should handle startsWith option."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(starts_with=True),
        )
        actual = to_mongo([query])
        assert actual[0]["$match"]["$and"][0]["test"]["$regex"] == "^value1"
        assert actual[0]["$match"]["$and"][0]["test"]["$options"] == "i"

    def test_should_handle_string_includes(self):
        """Should handle includes option."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(includes=True),
        )
        actual = to_mongo([query])
        assert actual[0]["$match"]["$and"][0]["test"]["$regex"] == "value1"
        assert actual[0]["$match"]["$and"][0]["test"]["$options"] == "i"

    def test_should_handle_string_starts_with_case_sensitive(self):
        """Should handle startsWith with case sensitive."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(starts_with=True, case_sensitive=True),
        )
        actual = to_mongo([query])
        assert actual[0]["$match"]["$and"][0]["test"]["$regex"] == "^value1"
        assert "$options" not in actual[0]["$match"]["$and"][0]["test"]

    def test_should_handle_string_ends_with_case_sensitive(self):
        """Should handle endsWith with case sensitive."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(ends_with=True, case_sensitive=True),
        )
        actual = to_mongo([query])
        assert actual[0]["$match"]["$and"][0]["test"]["$regex"] == "value1$"
        assert "$options" not in actual[0]["$match"]["$and"][0]["test"]

    def test_should_handle_not_equals_plain_exact(self):
        """Should handle not-equals plain exact (case sensitive)."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.ne,
            options=PropertyOptions(case_sensitive=True),
        )
        actual = to_mongo([query])
        expected = [{"$match": {"$and": [{"test": {"$ne": "value1"}}]}}]
        assert actual == expected

    def test_should_handle_not_equals_with_includes(self):
        """Should handle not-equals with includes using $not and regex."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.ne,
            options=PropertyOptions(includes=True),
        )
        actual = to_mongo([query])
        assert "$not" in actual[0]["$match"]["$and"][0]["test"]
        assert "$regex" in actual[0]["$match"]["$and"][0]["test"]["$not"]

    def test_should_throw_for_unsupported_equality_symbol_on_strings(self):
        """Should throw for unsupported equality symbols on strings."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.gt,
            options=PropertyOptions(),
        )
        with pytest.raises(ValueError, match="Symbol .* is unhandled for string type"):
            to_mongo([query])

    def test_should_handle_simple_and_query(self):
        """Should handle a simple AND query."""
        query1 = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        query2 = PropertyQuery(
            type="property",
            key="test2",
            value="value2",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        actual = to_mongo([query1, "AND", query2])
        assert "$and" in actual[0]["$match"]
        assert len(actual[0]["$match"]["$and"]) == 2

    def test_should_handle_simple_or_query(self):
        """Should handle a simple OR query."""
        query1 = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        query2 = PropertyQuery(
            type="property",
            key="test",
            value="value2",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        actual = to_mongo([query1, "OR", query2])
        assert "$or" in actual[0]["$match"]
        assert len(actual[0]["$match"]["$or"]) == 2

    def test_should_handle_dates_after_with_date_type(self):
        """Should handle datesAfter when it's a date."""
        the_date = datetime(2020, 1, 1, 0, 0, 0)
        query = DatesAfterQuery(
            type="datesAfter",
            key="my-key",
            date=the_date.isoformat(),
            value_type=DatastoreValueType.date,
            options=_DatesAfterOptions(equal_to_and_after=False),
        )
        actual = to_mongo([query])
        assert "$gt" in actual[0]["$match"]["$and"][0]["my-key"]

    def test_should_handle_dates_after_with_equal_to_and_after_false(self):
        """Should handle datesAfter with equalToAndAfter=false."""
        query = DatesAfterQuery(
            type="datesAfter",
            key="my-key",
            date="2020-01-01",
            value_type=DatastoreValueType.string,
            options=_DatesAfterOptions(equal_to_and_after=False),
        )
        actual = to_mongo([query])
        expected = [{"$match": {"$and": [{"my-key": {"$gt": "2020-01-01"}}]}}]
        assert actual == expected

    def test_should_handle_dates_after_with_equal_to_and_after_true(self):
        """Should handle datesAfter with equalToAndAfter=true."""
        query = DatesAfterQuery(
            type="datesAfter",
            key="my-key",
            date="2020-01-01",
            value_type=DatastoreValueType.string,
            options=_DatesAfterOptions(equal_to_and_after=True),
        )
        actual = to_mongo([query])
        expected = [{"$match": {"$and": [{"my-key": {"$gte": "2020-01-01"}}]}}]
        assert actual == expected

    def test_should_handle_dates_before_with_equal_to_and_before_false(self):
        """Should handle datesBefore with equalToAndBefore=false."""
        query = DatesBeforeQuery(
            type="datesBefore",
            key="my-key",
            date="2020-01-01",
            value_type=DatastoreValueType.string,
            options=_DatesBeforeOptions(equal_to_and_before=False),
        )
        actual = to_mongo([query])
        expected = [{"$match": {"$and": [{"my-key": {"$lt": "2020-01-01"}}]}}]
        assert actual == expected

    def test_should_handle_dates_before_with_equal_to_and_before_true(self):
        """Should handle datesBefore with equalToAndBefore=true."""
        query = DatesBeforeQuery(
            type="datesBefore",
            key="my-key",
            date="2020-01-01",
            value_type=DatastoreValueType.string,
            options=_DatesBeforeOptions(equal_to_and_before=True),
        )
        actual = to_mongo([query])
        expected = [{"$match": {"$and": [{"my-key": {"$lte": "2020-01-01"}}]}}]
        assert actual == expected

    def test_should_handle_object_values(self):
        """Should handle object values correctly."""
        query = PropertyQuery(
            type="property",
            key="test",
            value={"a": 1},
            value_type=DatastoreValueType.object,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        actual = to_mongo([query])
        expected = [{"$match": {"$and": [{"test": {"a": 1}}]}}]
        assert actual == expected


class TestThreeitize:
    """Tests for threeitize function."""

    def test_should_raise_error_for_even_number_of_items(self):
        """Should raise ValueError for even number of items."""
        query1 = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        query2 = PropertyQuery(
            type="property",
            key="test2",
            value="value2",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        # Even number of items (2) should raise error
        with pytest.raises(ValueError, match="Must be an odd number of 3 or greater"):
            threeitize([query1, query2])


class TestAsLink:
    """Tests for _as_link function."""

    def test_should_return_and_for_and_token(self):
        """Should return AND for AND token."""
        result = _as_link("AND")
        assert result == "AND"

    def test_should_return_or_for_or_token(self):
        """Should return OR for OR token."""
        result = _as_link("OR")
        assert result == "OR"

    def test_should_raise_error_for_invalid_token(self):
        """Should raise ValueError for invalid token."""
        query = PropertyQuery(
            type="property",
            key="test",
            value="value1",
            value_type=DatastoreValueType.string,
            equality_symbol=EqualitySymbol.eq,
            options=PropertyOptions(),
        )
        with pytest.raises(ValueError, match="Must have AND/OR between statements"):
            _as_link(query)


class TestFormatForMongo:
    """Tests for format_for_mongo."""

    def test_should_handle_datetime_object(self):
        """Should properly handle a datetime object."""
        the_date = datetime(2020, 1, 1, 0, 0, 0)
        data = {"myDate": the_date}
        actual = format_for_mongo(data)
        expected = {"myDate": the_date}
        assert actual == expected

    def test_should_handle_undefined_datetime(self):
        """Should properly handle undefined datetime."""
        data = {"myDate": None}
        actual = format_for_mongo(data)
        expected = {"myDate": None}
        assert actual == expected

    def test_should_preserve_other_values(self):
        """Should preserve other non-datetime values."""
        data = {"name": "test", "age": 25, "active": True}
        actual = format_for_mongo(data)
        assert actual == data
