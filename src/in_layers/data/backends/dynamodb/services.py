"""DynamoDB backend implementation for InLayers models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from box import Box
from in_layers.core.models.backends import (
    _apply_sort,
    _apply_take,
    _matches_query_tokens,
)
from in_layers.core.models.protocols import (
    InLayersModel,
    ModelSearch,
    ModelSearchResult,
    PrimaryKeyType,
)

from in_layers.data.protocols import DynamoDBBackendConfig

from .libs import (
    format_for_dynamodb,
    from_dynamodb,
    get_table_name_for_model,
    split_array_into_batches,
)

# DynamoDB batch operation limits
MAX_BATCH_WRITE_SIZE = 25
SCAN_RETURN_THRESHOLD = 1000


class DynamoDBBackend:
    """DynamoDB backend implementation."""

    def __init__(self, config: DynamoDBBackendConfig):
        self.__config = config
        self.__client: Any = None
        self.__table_client: Any = None

    @staticmethod
    def create_unique_connection_string(config: DynamoDBBackendConfig) -> str:
        """Create a unique connection string from config."""
        region = config.region or "us-east-1"
        endpoint_url = config.endpoint_url or ""

        parts = [f"region={region}"]
        if endpoint_url:
            parts.append(f"endpoint={endpoint_url}")

        return "|".join(parts)

    def __connect(self) -> None:
        """Connect to DynamoDB (private method)."""
        # Use boto3 from config if provided (for testing), otherwise import it
        if self.__config.boto3 is not None:
            boto3 = self.__config.boto3
        else:
            import boto3  # pragma: no cover # noqa: PLC0415

        # Build client configuration
        client_kwargs: dict[str, Any] = {}
        if self.__config.region:
            client_kwargs["region_name"] = self.__config.region
        if self.__config.endpoint_url:
            client_kwargs["endpoint_url"] = self.__config.endpoint_url
        if self.__config.aws_access_key_id and self.__config.aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = self.__config.aws_access_key_id
            client_kwargs["aws_secret_access_key"] = self.__config.aws_secret_access_key

        # Create DynamoDB client
        self.__client = boto3.client("dynamodb", **client_kwargs)

        # Create DynamoDB resource for easier table operations
        dynamodb_resource = boto3.resource("dynamodb", **client_kwargs)
        self.__table_client = dynamodb_resource

    def __disconnect(self) -> None:
        """Disconnect from DynamoDB (private method)."""
        # boto3 clients don't need explicit closing, but we can clear references
        self.__client = None
        self.__table_client = None

    def __ensure_connected(self) -> None:
        """Ensure DynamoDB connection is established."""
        if self.__client is None:
            self.__connect()

    def create(self, model: InLayersModel, data: Mapping) -> Mapping:
        """Create a new item in DynamoDB."""
        self.__ensure_connected()

        table_name = get_table_name_for_model(model.get_model_definition())
        table = self.__table_client.Table(table_name)

        payload = dict(data)
        formatted = format_for_dynamodb(payload)

        pk_name = model.get_primary_key_name()
        pk_value = formatted.get(pk_name)
        if pk_value is None:
            pk_value = str(uuid4())
            formatted[pk_name] = pk_value

        # Ensure primary key is a string (DynamoDB requirement)
        formatted[pk_name] = str(pk_value)

        # Put item in DynamoDB
        table.put_item(Item=formatted)
        return formatted

    def retrieve(self, model: InLayersModel, id: PrimaryKeyType) -> Mapping | None:
        """Retrieve an item by ID."""
        self.__ensure_connected()

        table_name = get_table_name_for_model(model.get_model_definition())
        table = self.__table_client.Table(table_name)

        pk_name = model.get_primary_key_name()
        key = {pk_name: str(id)}

        response = table.get_item(Key=key)
        item = response.get("Item")
        if not item:
            return None

        return from_dynamodb(item)

    def update(
        self, model: InLayersModel, id: PrimaryKeyType, data: Mapping
    ) -> Mapping:
        """Update an item by ID."""
        self.__ensure_connected()

        table_name = get_table_name_for_model(model.get_model_definition())
        table = self.__table_client.Table(table_name)

        pk_name = model.get_primary_key_name()
        key = {pk_name: str(id)}

        # Check if item exists
        existing = table.get_item(Key=key)
        if "Item" not in existing:
            raise KeyError(f"Instance with id {id!r} not found")

        payload = dict(data)
        formatted = format_for_dynamodb(payload)

        # Ensure primary key field remains consistent
        formatted[pk_name] = str(id)

        # Update item in DynamoDB
        table.put_item(Item=formatted)
        return formatted

    def delete(self, model: InLayersModel, id: PrimaryKeyType) -> None:
        """Delete an item by ID."""
        self.__ensure_connected()

        table_name = get_table_name_for_model(model.get_model_definition())
        table = self.__table_client.Table(table_name)

        pk_name = model.get_primary_key_name()
        key = {pk_name: str(id)}

        table.delete_item(Key=key)

    def search(self, model: InLayersModel, query: ModelSearch) -> ModelSearchResult:
        """Search for items matching the query.

        Note: DynamoDB Scan operations are expensive and should be used sparingly.
        For production use, consider using Query operations with Global Secondary Indexes (GSI)
        or Local Secondary Indexes (LSI) for better performance.

        This implementation continues scanning across pages until:
        - Threshold is met (SCAN_RETURN_THRESHOLD if no take specified)
        - No more keys (LastEvaluatedKey is null)
        - Take limit is reached (if take is specified)
        """
        self.__ensure_connected()

        table_name = get_table_name_for_model(model.get_model_definition())
        table = self.__table_client.Table(table_name)

        # Start recursive scanning
        result = self._do_search_until_threshold_or_no_last_evaluated_key(
            table, query, []
        )

        return Box(instances=result["instances"], page=result["page"])

    def _do_search_until_threshold_or_no_last_evaluated_key(
        self,
        table: Any,
        query: ModelSearch,
        old_instances_found: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Recursively scan DynamoDB until threshold is met or no more keys.

        This matches the TypeScript implementation's behavior of continuing
        to scan across pages until enough filtered results are found.
        """
        # Build scan parameters
        scan_kwargs: dict[str, Any] = {}
        if query.page:
            scan_kwargs["ExclusiveStartKey"] = query.page

        # Execute scan
        response = table.scan(**scan_kwargs)
        items = response.get("Items", [])

        # Convert DynamoDB items to plain dicts
        unfiltered = [from_dynamodb(item) for item in items]

        # Apply filtering using the same logic as MemoryBackend
        filtered = [r for r in unfiltered if _matches_query_tokens(r, query.query)]

        # Combine with previously found instances
        all_filtered = filtered + old_instances_found

        # Determine threshold
        using_take = query.take is not None and query.take > 0
        take = query.take if using_take else SCAN_RETURN_THRESHOLD

        # Get pagination key
        last_evaluated_key = response.get("LastEvaluatedKey")

        # Check stopping conditions:
        # 1. We have enough results (more than threshold)
        # 2. No more keys to evaluate
        # 3. If using take, we've hit our max
        # Note: TypeScript uses > (strictly greater), meaning we continue if we have exactly 'take' items
        stop_for_threshold = len(all_filtered) > take
        stop_for_no_more = last_evaluated_key is None

        if stop_for_threshold or stop_for_no_more:
            # Apply sorting and take limit
            sorted_instances = _apply_sort(all_filtered, query.sort)
            limited_instances = _apply_take(sorted_instances, query.take)

            # Return page: null when using take, otherwise return LastEvaluatedKey
            page = None if using_take else last_evaluated_key

            return {
                "instances": [dict(x) for x in limited_instances],
                "page": page,
            }

        # Continue scanning with the new page key
        # Create a new ModelSearch with updated page (frozen dataclass requires new instance)
        new_query = ModelSearch(
            query=query.query,
            take=query.take,
            sort=query.sort,
            page=last_evaluated_key,
        )
        return self._do_search_until_threshold_or_no_last_evaluated_key(
            table, new_query, all_filtered
        )

    def bulk_insert(self, model: InLayersModel, data: list[Mapping]) -> None:
        """Bulk insert items."""
        self.__ensure_connected()

        table_name = get_table_name_for_model(model.get_model_definition())
        table = self.__table_client.Table(table_name)
        pk_name = model.get_primary_key_name()

        # Prepare items
        items = []
        for item in data:
            payload = dict(item)
            formatted = format_for_dynamodb(payload)

            pk_value = formatted.get(pk_name)
            if pk_value is None:

                pk_value = str(uuid4())
                formatted[pk_name] = pk_value

            formatted[pk_name] = str(pk_value)
            items.append(formatted)

        # Split into batches (DynamoDB BatchWriteItem limit is 25)
        batches = split_array_into_batches(items, MAX_BATCH_WRITE_SIZE)

        # Write batches
        for batch in batches:
            with table.batch_writer() as writer:
                for item in batch:
                    writer.put_item(Item=item)

    def bulk_delete(self, model: InLayersModel, ids: list[PrimaryKeyType]) -> None:
        """Bulk delete items by IDs."""
        self.__ensure_connected()

        table_name = get_table_name_for_model(model.get_model_definition())
        table = self.__table_client.Table(table_name)
        pk_name = model.get_primary_key_name()

        # Prepare keys
        keys = [{pk_name: str(id)} for id in ids]

        # Split into batches
        batches = split_array_into_batches(keys, MAX_BATCH_WRITE_SIZE)

        # Delete batches
        for batch in batches:
            with table.batch_writer() as writer:
                for key in batch:
                    writer.delete_item(Key=key)

    def dispose(self) -> None:
        """Clean up resources."""
        self.__disconnect()
