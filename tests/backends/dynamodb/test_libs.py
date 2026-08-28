"""Unit tests for DynamoDB libs module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from in_layers.core.protocols import ErrorDetails, ErrorObject
from in_layers.core.models.protocols import ModelDefinition
from in_layers.data.backends.dynamodb.libs import (
    build_scan_params,
    format_for_dynamodb,
    from_dynamodb,
    get_table_name_for_model,
    split_array_into_batches,
)


class _StubModelDefinition:
    """Stub model definition for testing."""

    def __init__(self, plural_name: str = "MyPluralNames"):
        self.plural_name = plural_name


class TestGetTableNameForModel:
    """Tests for get_table_name_for_model."""

    def test_should_return_kebab_case_for_camel_case(self):
        """Should return kebab-case for camelCase input."""
        model_def = _StubModelDefinition("MyTable")
        actual = get_table_name_for_model("test", model_def)
        expected = "my-table-test"
        assert actual == expected

    def test_should_return_kebab_case_for_pascal_case(self):
        """Should return kebab-case for PascalCase input."""
        model_def = _StubModelDefinition("MyPluralNames")
        actual = get_table_name_for_model("test", model_def)
        expected = "my-plural-names-test"
        assert actual == expected

    def test_should_return_lowercase_for_already_kebab_case(self):
        """Should return lowercase for already kebab-case input."""
        model_def = _StubModelDefinition("my-table")
        actual = get_table_name_for_model("test", model_def)
        expected = "my-table-test"
        assert actual == expected

    def test_should_handle_underscores(self):
        """Should handle underscores in names."""
        model_def = _StubModelDefinition("My_Table")
        actual = get_table_name_for_model("test", model_def)
        # Underscores should be preserved, then converted
        assert "my" in actual.lower()
        assert "table" in actual.lower()

    def test_should_remove_at_symbols(self):
        """Should remove @ symbols from names."""
        model_def = _StubModelDefinition("@My@Model@")
        actual = get_table_name_for_model("test", model_def)
        expected = "my-model-test"
        assert actual == expected

    def test_should_replace_slashes(self):
        """Should replace / with - in names."""
        model_def = _StubModelDefinition("My/Model/Name")
        actual = get_table_name_for_model("test", model_def)
        expected = "my-model-name-test"
        assert actual == expected


class TestSplitArrayIntoArraysOfMaxSize:
    """Tests for split_array_into_batches."""

    def test_should_throw_exception_if_input_is_not_array(self):
        """Should throw an exception if the input is not a list."""
        with pytest.raises(ValueError, match="Input must be a list"):
            split_array_into_batches("input", 2)

    def test_should_throw_exception_if_max_batch_size_is_less_than_one(self):
        """Should throw an exception if max_batch_size is less than 1."""
        with pytest.raises(ValueError, match="max_batch_size must be at least 1"):
            split_array_into_batches([1, 2, 3], 0)

    def test_should_split_array_of_10_into_5_sets_of_2(self):
        """Should split an array of 10 into 5 sets of 2."""
        input_array = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        actual = split_array_into_batches(input_array, 2)
        expected = [
            [1, 2],
            [3, 4],
            [5, 6],
            [7, 8],
            [9, 10],
        ]
        assert actual == expected

    def test_should_split_array_of_11_into_5_sets_of_2_and_1_set_of_1(self):
        """Should split an array of 11 into 5 sets of 2 and 1 set of 1."""
        input_array = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        actual = split_array_into_batches(input_array, 2)
        expected = [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10], [11]]
        assert actual == expected

    def test_should_handle_empty_array(self):
        """Should handle empty array."""
        actual = split_array_into_batches([], 2)
        expected = []
        assert actual == expected

    def test_should_handle_single_element_array(self):
        """Should handle single element array."""
        actual = split_array_into_batches([1], 2)
        expected = [[1]]
        assert actual == expected

    def test_should_handle_batch_size_larger_than_array(self):
        """Should handle batch size larger than array."""
        actual = split_array_into_batches([1, 2, 3], 10)
        expected = [[1, 2, 3]]
        assert actual == expected


class TestFormatForDynamodb:
    """Tests for format_for_dynamodb."""

    def test_should_convert_datetime_to_iso_format(self):
        """Should convert datetime objects to ISO format strings."""
        the_date = datetime(2020, 1, 1, 12, 30, 45)
        data = {"myDate": the_date, "name": "test"}
        actual = format_for_dynamodb(data)
        assert actual["myDate"] == the_date.isoformat()
        assert actual["name"] == "test"

    def test_should_preserve_non_datetime_values(self):
        """Should preserve non-datetime values (normalizing floats to Decimal)."""
        data = {"name": "test", "age": 25, "active": True, "score": 98.5}
        actual = format_for_dynamodb(data)
        assert actual["name"] == "test"
        assert actual["age"] == 25
        assert actual["active"] is True
        assert isinstance(actual["score"], Decimal)
        assert actual["score"] == Decimal("98.5")

    def test_should_handle_none_values(self):
        """Should handle None values."""
        data = {"name": None, "age": 25}
        actual = format_for_dynamodb(data)
        assert actual["name"] is None
        assert actual["age"] == 25

    def test_should_handle_empty_dict(self):
        """Should handle empty dictionary."""
        data = {}
        actual = format_for_dynamodb(data)
        assert actual == {}

    def test_should_convert_error_object_to_plain_dict(self):
        """Should convert ErrorObject dataclasses into plain nested dictionaries."""
        cause = ErrorDetails(
            code="CAUSE_CODE",
            message="Cause message",
        )
        error_details = ErrorDetails(
            code="ERR_CODE",
            message="Top level message",
            cause=cause,
        )
        data = {"id": "123", "error": error_details}

        actual = format_for_dynamodb(data)

        # Top-level remains a dict
        assert isinstance(actual, dict)
        # Error field should be a plain dict, not a dataclass instance
        assert isinstance(actual["error"], dict)
        assert actual["error"]["code"] == "ERR_CODE"
        assert actual["error"]["message"] == "Top level message"
        # Nested cause should also be a plain dict
        assert isinstance(actual["error"]["cause"], dict)
        assert actual["error"]["cause"]["code"] == "CAUSE_CODE"
        assert actual["error"]["cause"]["message"] == "Cause message"


class TestFromDynamodb:
    """Tests for from_dynamodb."""

    def test_should_convert_item_to_dict(self):
        """Should convert DynamoDB item to plain dictionary."""
        item = {"id": "my-id", "name": "my-name", "age": 25}
        actual = from_dynamodb(item)
        expected = {"id": "my-id", "name": "my-name", "age": 25}
        assert actual == expected

    def test_should_handle_none_item(self):
        """Should handle None item."""
        actual = from_dynamodb(None)
        expected = {}
        assert actual == expected

    def test_should_handle_empty_dict(self):
        """Should handle empty dictionary."""
        actual = from_dynamodb({})
        expected = {}
        assert actual == expected

    def test_should_handle_nested_dicts(self):
        """Should handle nested dictionaries."""
        item = {"id": "my-id", "metadata": {"key": "value"}}
        actual = from_dynamodb(item)
        expected = {"id": "my-id", "metadata": {"key": "value"}}
        assert actual == expected

    def test_should_handle_lists(self):
        """Should handle lists in items."""
        item = {"id": "my-id", "tags": ["tag1", "tag2"]}
        actual = from_dynamodb(item)
        expected = {"id": "my-id", "tags": ["tag1", "tag2"]}
        assert actual == expected


class TestBuildScanParams:
    """Tests for build_scan_params."""

    def test_should_build_params_without_exclusive_start_key(self):
        """Should build params without ExclusiveStartKey."""
        actual = build_scan_params("my-table")
        expected = {"TableName": "my-table"}
        assert actual == expected

    def test_should_build_params_with_exclusive_start_key(self):
        """Should build params with ExclusiveStartKey."""
        start_key = {"id": {"S": "last-id"}}
        actual = build_scan_params("my-table", start_key)
        expected = {
            "TableName": "my-table",
            "ExclusiveStartKey": start_key,
        }
        assert actual == expected

    def test_should_handle_none_exclusive_start_key(self):
        """Should handle None ExclusiveStartKey."""
        actual = build_scan_params("my-table", None)
        expected = {"TableName": "my-table"}
        assert actual == expected
