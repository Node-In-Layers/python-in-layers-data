"""Unit tests for DynamoDB services module."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from box import Box

from in_layers.core.models.protocols import (
    InLayersModel,
    ModelDefinition,
    ModelSearch,
    PrimaryKeyType,
    PropertyQuery,
    PropertyOptions,
    DatastoreValueType,
    EqualitySymbol,
)
from in_layers.data.backends.dynamodb.services import DynamoDBBackend
from in_layers.data.protocols import DynamoDBBackendConfig, SupportedBackend


class _StubModelDefinition:
    """Stub model definition for testing."""

    def __init__(
        self,
        plural_name: str = "TestModels",
        domain: str = "test",
        primary_key: str = "id",
    ):
        self.plural_name = plural_name
        self.domain = domain
        self.primary_key = primary_key


class _StubModel:
    """Stub model for testing."""

    def __init__(self, model_def: ModelDefinition | None = None):
        self._model_def = model_def or _StubModelDefinition()

    def get_model_definition(self) -> ModelDefinition:
        """Get model definition."""
        return self._model_def

    def get_primary_key_name(self) -> str:
        """Get primary key name."""
        return self._model_def.primary_key


def _create_mock_config(boto3_mock: Any | None = None) -> DynamoDBBackendConfig:
    """Create a mock DynamoDBBackendConfig."""
    return Box(
        type=SupportedBackend.DynamoDB,
        region="us-east-1",
        endpoint_url=None,
        aws_access_key_id=None,
        aws_secret_access_key=None,
        boto3=boto3_mock,
    )


def _create_mock_table():
    """Create a mock DynamoDB table."""
    table = MagicMock()
    table.put_item = MagicMock()
    table.update_item = MagicMock()
    table.get_item = MagicMock(return_value={"Item": None})
    table.delete_item = MagicMock()
    table.scan = MagicMock(return_value={"Items": [], "LastEvaluatedKey": None})
    table.batch_writer = MagicMock()
    return table


class TestCreateUniqueConnectionString:
    """Tests for create_unique_connection_string."""

    def test_should_create_connection_string_with_region(self):
        """Should create connection string with region."""
        config = _create_mock_config()
        config.region = "us-west-2"
        actual = DynamoDBBackend.create_unique_connection_string(config)
        assert "region=us-west-2" in actual

    def test_should_create_connection_string_with_endpoint_url(self):
        """Should create connection string with endpoint URL."""
        config = _create_mock_config()
        config.endpoint_url = "http://localhost:8000"
        actual = DynamoDBBackend.create_unique_connection_string(config)
        assert "endpoint=http://localhost:8000" in actual

    def test_should_use_default_region_when_none(self):
        """Should use default region when None."""
        config = _create_mock_config()
        config.region = None
        actual = DynamoDBBackend.create_unique_connection_string(config)
        assert "region=us-east-1" in actual

    def test_should_handle_empty_endpoint_url(self):
        """Should handle empty endpoint URL."""
        config = _create_mock_config()
        config.endpoint_url = ""
        actual = DynamoDBBackend.create_unique_connection_string(config)
        assert "endpoint=" not in actual


class TestCreate:
    """Tests for create method."""

    def test_should_create_item_with_provided_primary_key(self):
        """Should create item with provided primary key."""
        mock_table = _create_mock_table()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        data = {"id": "my-id", "name": "my-name"}

        result = backend.create(model, data)

        assert result["id"] == "my-id"
        assert result["name"] == "my-name"
        mock_table.put_item.assert_called_once()
        call_args = mock_table.put_item.call_args
        assert call_args[1]["Item"]["id"] == "my-id"
        assert call_args[1]["Item"]["name"] == "my-name"

    def test_should_generate_primary_key_when_not_provided(self):
        """Should generate primary key when not provided."""
        mock_table = _create_mock_table()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        data = {"name": "my-name"}

        result = backend.create(model, data)

        assert "id" in result
        assert isinstance(result["id"], str)
        assert len(result["id"]) > 0
        mock_table.put_item.assert_called_once()


class TestRetrieve:
    """Tests for retrieve method."""

    def test_should_retrieve_item_by_id(self):
        """Should retrieve item by ID."""
        mock_table = _create_mock_table()
        mock_table.get_item.return_value = {"Item": {"id": "my-id", "name": "my-name"}}
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()

        result = backend.retrieve(model, "my-id")

        assert result is not None
        assert result["id"] == "my-id"
        assert result["name"] == "my-name"
        mock_table.get_item.assert_called_once_with(Key={"id": "my-id"})

    def test_should_return_none_when_item_not_found(self):
        """Should return None when item not found."""
        mock_table = _create_mock_table()
        mock_table.get_item.return_value = {"Item": None}
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()

        result = backend.retrieve(model, "non-existent")

        assert result is None


class TestUpdate:
    """Tests for update method."""

    def test_should_update_existing_item(self):
        """Should update existing item."""
        mock_table = _create_mock_table()
        # First call: check if item exists, second call: retrieve updated item
        mock_table.get_item.side_effect = [
            {"Item": {"id": "my-id", "name": "old-name"}},
            {"Item": {"id": "my-id", "name": "new-name"}},
        ]
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        data = {"name": "new-name"}

        result = backend.update(model, "my-id", data)

        assert result["id"] == "my-id"
        assert result["name"] == "new-name"
        mock_table.update_item.assert_called_once()

    def test_should_raise_key_error_when_item_not_found(self):
        """Should raise KeyError when item not found."""
        mock_table = _create_mock_table()
        # When item doesn't exist, get_item returns dict without "Item" key
        mock_table.get_item.return_value = {}
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        data = {"name": "new-name"}

        with pytest.raises(KeyError, match="Instance with id 'non-existent' not found"):
            backend.update(model, "non-existent", data)


class TestDelete:
    """Tests for delete method."""

    def test_should_delete_item_by_id(self):
        """Should delete item by ID."""
        mock_table = _create_mock_table()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()

        backend.delete(model, "my-id")

        mock_table.delete_item.assert_called_once_with(Key={"id": "my-id"})


class TestSearch:
    """Tests for search method."""

    def test_should_call_scan_once_when_last_evaluated_key_is_empty(self):
        """Should call scan once when LastEvaluatedKey is empty."""
        mock_table = _create_mock_table()
        mock_table.scan.return_value = {"Items": [], "LastEvaluatedKey": None}
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        query = ModelSearch(query=[], take=None, sort=None, page=None)

        backend.search(model, query)

        assert mock_table.scan.call_count == 1

    def test_should_process_string_value_result(self):
        """Should be able to process a string value result."""
        mock_table = _create_mock_table()
        mock_table.scan.return_value = {
            "Items": [{"id": "my-id", "name": "my-name"}],
            "LastEvaluatedKey": None,
        }
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        query = ModelSearch(
            query=[
                PropertyQuery(
                    type="property",
                    key="name",
                    value="my-name",
                    value_type=DatastoreValueType.string,
                    equality_symbol=EqualitySymbol.eq,
                    options=PropertyOptions(),
                )
            ],
            take=None,
            sort=None,
            page=None,
        )

        result = backend.search(model, query)

        assert len(result.instances) == 1
        assert result.instances[0]["id"] == "my-id"
        assert result.instances[0]["name"] == "my-name"

    def test_should_process_null_value_results(self):
        """Should be able to process a null value results."""
        mock_table = _create_mock_table()
        mock_table.scan.return_value = {
            "Items": [{"id": "my-id", "name": None}],
            "LastEvaluatedKey": None,
        }
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        query = ModelSearch(
            query=[
                PropertyQuery(
                    type="property",
                    key="name",
                    value=None,
                    value_type=DatastoreValueType.string,
                    equality_symbol=EqualitySymbol.eq,
                    options=PropertyOptions(),
                )
            ],
            take=None,
            sort=None,
            page=None,
        )

        result = backend.search(model, query)

        assert len(result.instances) == 1
        assert result.instances[0]["id"] == "my-id"
        assert result.instances[0]["name"] is None

    def test_should_process_array_of_strings(self):
        """Should be able to process an array of strings."""
        mock_table = _create_mock_table()
        mock_table.scan.return_value = {
            "Items": [{"id": "my-id", "names": ["a", "b"]}],
            "LastEvaluatedKey": None,
        }
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        query = ModelSearch(
            query=[
                PropertyQuery(
                    type="property",
                    key="id",
                    value="my-id",
                    value_type=DatastoreValueType.string,
                    equality_symbol=EqualitySymbol.eq,
                    options=PropertyOptions(),
                )
            ],
            take=None,
            sort=None,
            page=None,
        )

        result = backend.search(model, query)

        assert len(result.instances) == 1
        assert result.instances[0]["id"] == "my-id"
        assert result.instances[0]["names"] == ["a", "b"]

    def test_should_return_only_one_object_if_query_has_take_1(self):
        """Should return only 1 object if query has take:1 even if there are two results."""
        mock_table = _create_mock_table()
        mock_table.scan.return_value = {
            "Items": [
                {"id": "my-id", "name": "name1"},
                {"id": "my-id2", "name": "name2"},
            ],
            "LastEvaluatedKey": None,
        }
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        query = ModelSearch(
            query=[
                PropertyQuery(
                    type="property",
                    key="name",
                    value="name",
                    value_type=DatastoreValueType.string,
                    equality_symbol=EqualitySymbol.eq,
                    options=PropertyOptions(starts_with=True),
                )
            ],
            take=1,
            sort=None,
            page=None,
        )

        result = backend.search(model, query)

        assert len(result.instances) == 1
        assert result.page is None  # When using take, page should be None

    def test_should_call_scan_twice_when_last_evaluated_key_present(self):
        """Should call scan twice when LastEvaluatedKey is present then empty."""
        mock_table = _create_mock_table()
        # First call returns with LastEvaluatedKey
        # Second call returns empty
        mock_table.scan.side_effect = [
            {"Items": [], "LastEvaluatedKey": "try-again"},
            {"Items": [{"something": "returned"}], "LastEvaluatedKey": None},
        ]
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        query = ModelSearch(
            query=[
                PropertyQuery(
                    type="property",
                    key="name",
                    value="my-name",
                    value_type=DatastoreValueType.string,
                    equality_symbol=EqualitySymbol.eq,
                    options=PropertyOptions(),
                )
            ],
            take=None,
            sort=None,
            page=None,
        )

        backend.search(model, query)

        assert mock_table.scan.call_count == 2

    def test_should_call_scan_twice_when_take_2_and_3_items_returned(self):
        """Should call scan twice when take:2 and 3 items are returned."""
        mock_table = _create_mock_table()
        mock_table.scan.side_effect = [
            {"Items": [], "LastEvaluatedKey": "try-again"},
            {
                "Items": [
                    {"name": "returned"},
                    {"name": "returned2"},
                    {"name": "returned3"},
                ],
                "LastEvaluatedKey": "another-value",
            },
        ]
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        query = ModelSearch(
            query=[
                PropertyQuery(
                    type="property",
                    key="name",
                    value="returned",
                    value_type=DatastoreValueType.string,
                    equality_symbol=EqualitySymbol.eq,
                    options=PropertyOptions(starts_with=True),
                )
            ],
            take=2,
            sort=None,
            page=None,
        )

        backend.search(model, query)

        assert mock_table.scan.call_count == 2

    def test_should_return_all_items_when_query_is_empty(self):
        """Should return all items when query is empty (not an empty set)."""
        mock_table = _create_mock_table()
        mock_table.scan.return_value = {
            "Items": [
                {"id": "1", "name": "item1"},
                {"id": "2", "name": "item2"},
                {"id": "3", "name": "item3"},
            ],
            "LastEvaluatedKey": None,
        }
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        # Empty query should return all items
        query = ModelSearch(query=[], take=None, sort=None, page=None)

        result = backend.search(model, query)

        # Should return all 3 items, not an empty set
        assert len(result.instances) == 3
        assert result.instances[0]["id"] == "1"
        assert result.instances[1]["id"] == "2"
        assert result.instances[2]["id"] == "3"

    def test_should_return_all_available_items_when_take_is_larger_than_available(self):
        """Should return all available items when take is larger than number of items found."""
        mock_table = _create_mock_table()
        # Simulate 3 items in the database
        mock_table.scan.return_value = {
            "Items": [
                {"id": "1", "name": "item1"},
                {"id": "2", "name": "item2"},
                {"id": "3", "name": "item3"},
            ],
            "LastEvaluatedKey": None,
        }
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        # Request 4 items but only 3 are available
        query = ModelSearch(query=[], take=4, sort=None, page=None)

        result = backend.search(model, query)

        # Should return all 3 available items, not 0
        assert len(result.instances) == 3
        assert result.instances[0]["id"] == "1"
        assert result.instances[1]["id"] == "2"
        assert result.instances[2]["id"] == "3"
        assert result.page is None  # When using take, page should be None

    def test_should_return_all_available_items_when_take_equals_available(self):
        """Should return all items when take equals the number of items found."""
        mock_table = _create_mock_table()
        # Simulate 3 items in the database
        mock_table.scan.return_value = {
            "Items": [
                {"id": "1", "name": "item1"},
                {"id": "2", "name": "item2"},
                {"id": "3", "name": "item3"},
            ],
            "LastEvaluatedKey": None,
        }
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        # Request exactly 3 items (same as available)
        query = ModelSearch(query=[], take=3, sort=None, page=None)

        result = backend.search(model, query)

        # Should return all 3 items
        assert len(result.instances) == 3
        assert result.instances[0]["id"] == "1"
        assert result.instances[1]["id"] == "2"
        assert result.instances[2]["id"] == "3"
        assert result.page is None  # When using take, page should be None


class TestCount:
    """Tests for count method."""

    def test_should_accumulate_count_across_scan_pages(self):
        mock_table = _create_mock_table()
        mock_table.scan.side_effect = [
            {"Count": 2, "LastEvaluatedKey": {"id": "next"}},
            {"Count": 1, "LastEvaluatedKey": None},
        ]
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        actual = backend.count(_StubModel())

        assert actual == 3


class TestBulkInsert:
    """Tests for bulk_insert method."""

    def test_should_format_objects_correctly_for_batch_write(self):
        """Should format objects correctly when passed to batch writer."""
        mock_table = _create_mock_table()
        mock_writer = MagicMock()
        mock_table.batch_writer.return_value.__enter__.return_value = mock_writer
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        data = [
            {"id": "1", "name": "my-name"},
            {"id": "2", "name": "my-name"},
            {"id": "3", "name": "my-name"},
            {"id": "4", "name": "my-name"},
            {"id": "5", "name": "my-name"},
        ]

        backend.bulk_insert(model, data)

        # Should be called 5 times (one for each item)
        assert mock_writer.put_item.call_count == 5

    def test_should_not_call_batch_writer_if_no_items(self):
        """Should not call batch writer if there are no items."""
        mock_table = _create_mock_table()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        data: list[dict] = []

        backend.bulk_insert(model, data)

        mock_table.batch_writer.assert_not_called()

    def test_should_split_into_batches_when_more_than_25_items(self):
        """Should split into batches when more than 25 items."""
        mock_table = _create_mock_table()
        mock_writer = MagicMock()
        mock_table.batch_writer.return_value.__enter__.return_value = mock_writer
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        # Create 30 items
        data = [{"id": str(i), "name": f"name-{i}"} for i in range(30)]

        backend.bulk_insert(model, data)

        # Should be called twice (25 + 5)
        assert mock_table.batch_writer.call_count == 2


class TestBulkDelete:
    """Tests for bulk_delete method."""

    def test_should_delete_multiple_items(self):
        """Should delete multiple items by IDs."""
        mock_table = _create_mock_table()
        mock_writer = MagicMock()
        mock_table.batch_writer.return_value.__enter__.return_value = mock_writer
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        ids = ["id1", "id2", "id3"]

        backend.bulk_delete(model, ids)

        assert mock_writer.delete_item.call_count == 3

    def test_should_split_into_batches_when_more_than_25_ids(self):
        """Should split into batches when more than 25 IDs."""
        mock_table = _create_mock_table()
        mock_writer = MagicMock()
        mock_table.batch_writer.return_value.__enter__.return_value = mock_writer
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        # Create 30 IDs
        ids = [str(i) for i in range(30)]

        backend.bulk_delete(model, ids)

        # Should be called twice (25 + 5)
        assert mock_table.batch_writer.call_count == 2


class TestDispose:
    """Tests for dispose method."""

    def test_should_disconnect_on_dispose(self):
        """Should disconnect on dispose."""
        mock_table = _create_mock_table()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)
        backend._DynamoDBBackend__client = MagicMock()

        backend.dispose()

        assert backend._DynamoDBBackend__client is None
        assert backend._DynamoDBBackend__table_client is None


class TestConnectConfig:
    """Tests for connection configuration options."""

    def test_should_use_region_when_provided(self):
        """Should use region when provided in config."""
        mock_table = _create_mock_table()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        mock_boto3.client.return_value = MagicMock()
        config = _create_mock_config(boto3_mock=mock_boto3)
        config.region = "us-west-2"
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        backend.create(model, {"id": "test", "name": "test"})

        # Verify region was passed to client
        mock_boto3.client.assert_called_once()
        call_kwargs = mock_boto3.client.call_args[1]
        assert call_kwargs["region_name"] == "us-west-2"

    def test_should_use_endpoint_url_when_provided(self):
        """Should use endpoint_url when provided in config."""
        mock_table = _create_mock_table()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        mock_boto3.client.return_value = MagicMock()
        config = _create_mock_config(boto3_mock=mock_boto3)
        config.endpoint_url = "http://localhost:8000"
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        backend.create(model, {"id": "test", "name": "test"})

        # Verify endpoint_url was passed to client
        mock_boto3.client.assert_called_once()
        call_kwargs = mock_boto3.client.call_args[1]
        assert call_kwargs["endpoint_url"] == "http://localhost:8000"

    def test_should_use_aws_credentials_when_provided(self):
        """Should use AWS credentials when provided in config."""
        mock_table = _create_mock_table()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        mock_boto3.client.return_value = MagicMock()
        config = _create_mock_config(boto3_mock=mock_boto3)
        config.aws_access_key_id = "test-key"
        config.aws_secret_access_key = "test-secret"
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        backend.create(model, {"id": "test", "name": "test"})

        # Verify credentials were passed to client
        mock_boto3.client.assert_called_once()
        call_kwargs = mock_boto3.client.call_args[1]
        assert call_kwargs["aws_access_key_id"] == "test-key"
        assert call_kwargs["aws_secret_access_key"] == "test-secret"

    def test_should_not_use_region_when_none(self):
        """Should not use region when None."""
        mock_table = _create_mock_table()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        mock_boto3.client.return_value = MagicMock()
        config = _create_mock_config(boto3_mock=mock_boto3)
        config.region = None
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        backend.create(model, {"id": "test", "name": "test"})

        # Verify region was NOT passed to client
        mock_boto3.client.assert_called_once()
        call_kwargs = mock_boto3.client.call_args[1]
        assert "region_name" not in call_kwargs

    def test_should_not_call_connect_when_already_connected(self):
        """Should not call connect when already connected."""
        mock_table = _create_mock_table()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)
        # Set client to non-None to simulate already connected
        backend._DynamoDBBackend__client = MagicMock()
        backend._DynamoDBBackend__table_client = mock_resource

        model = _StubModel()
        # First call should not trigger connect
        backend.create(model, {"id": "test", "name": "test"})

        # Verify boto3.client was not called (already connected)
        mock_boto3.client.assert_not_called()


class TestBulkInsertCoverage:
    """Tests for bulk_insert coverage."""

    def test_should_generate_primary_key_when_not_provided_in_bulk_insert(self):
        """Should generate primary key when not provided in bulk_insert."""
        mock_table = _create_mock_table()
        mock_writer = MagicMock()
        mock_table.batch_writer.return_value.__enter__.return_value = mock_writer
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3 = MagicMock()
        mock_boto3.resource.return_value = mock_resource
        config = _create_mock_config(boto3_mock=mock_boto3)
        context = MagicMock()
        context.environment = "test"
        backend = DynamoDBBackend(context, config)

        model = _StubModel()
        data = [{"name": "item1"}, {"name": "item2"}]

        backend.bulk_insert(model, data)

        # Verify that put_item was called with generated IDs
        assert mock_writer.put_item.call_count == 2
        # Check that IDs were generated
        calls = mock_writer.put_item.call_args_list
        for call in calls:
            item = call[1]["Item"]
            assert "id" in item
            assert isinstance(item["id"], str)
            assert len(item["id"]) > 0
