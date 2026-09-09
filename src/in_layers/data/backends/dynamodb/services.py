"""DynamoDB backend implementation for InLayers models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from botocore.exceptions import ClientError
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

# Error code when table or requested resource does not exist
_RESOURCE_NOT_FOUND = "ResourceNotFoundException"


def _is_resource_not_found(e: ClientError) -> bool:
    return e.response.get("Error", {}).get("Code") == _RESOURCE_NOT_FOUND


class DynamoDBBackend:
    """DynamoDB backend implementation."""

    def __init__(self, context, config: DynamoDBBackendConfig):
        self.__context = context
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

    def __get_config_value(self, key: str, default_value: Any = None) -> Any:
        if key in self.__config:
            return self.__config[key]
        return default_value

    def __connect(self) -> None:
        """Connect to DynamoDB (private method)."""
        # Use boto3 from config if provided (for testing), otherwise import it
        if self.__get_config_value("boto3") is not None:
            boto3 = self.__get_config_value("boto3")
        else:
            import boto3  # pragma: no cover # noqa: PLC0415

        region = self.__get_config_value("region")
        endpoint_url = self.__get_config_value("endpoint_url")
        aws_access_key_id = self.__get_config_value("aws_access_key_id")
        aws_secret_access_key = self.__get_config_value("aws_secret_access_key")
        client_kwargs: dict[str, Any] = {}
        if region:
            client_kwargs["region_name"] = region
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        if aws_access_key_id:
            client_kwargs["aws_access_key_id"] = aws_access_key_id
        if aws_secret_access_key:
            client_kwargs["aws_secret_access_key"] = aws_secret_access_key

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

    def get_raw_client(self) -> Any:
        self.__ensure_connected()
        return self.__table_client

    def get_backend_name(self) -> str:
        return "dynamodb"

    def create(self, model: InLayersModel, data: Mapping) -> Mapping:
        """Create a new item in DynamoDB."""
        self.__ensure_connected()

        table_name = get_table_name_for_model(
            self.__context.config.environment, model.get_model_definition()
        )
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
        """Retrieve an item by ID. Returns empty dict if table or item is not found."""
        self.__ensure_connected()

        table_name = get_table_name_for_model(
            self.__context.config.environment, model.get_model_definition()
        )
        table = self.__table_client.Table(table_name)

        pk_name = model.get_primary_key_name()
        key = {pk_name: str(id)}

        try:
            response = table.get_item(Key=key)
        except ClientError as e:
            if _is_resource_not_found(e):
                return None
            raise

        item = response.get("Item")
        if not item:
            return None

        return from_dynamodb(item)

    def update(
        self, model: InLayersModel, id: PrimaryKeyType, data: Mapping
    ) -> Mapping:
        """Update an item by ID.

        Supports partial updates - only the fields provided in data will be updated.
        Returns the full merged object (original + updates).
        """
        self.__ensure_connected()

        table_name = get_table_name_for_model(
            self.__context.config.environment, model.get_model_definition()
        )
        table = self.__table_client.Table(table_name)

        pk_name = model.get_primary_key_name()
        key = {pk_name: str(id)}

        # Check if item exists
        try:
            existing = table.get_item(Key=key)
        except ClientError as e:
            if _is_resource_not_found(e):
                raise KeyError(f"Instance with id {id!r} not found") from e
            raise

        if "Item" not in existing:
            raise KeyError(f"Instance with id {id!r} not found")

        payload = dict(data)
        formatted = format_for_dynamodb(payload)

        # Ensure primary key field remains consistent
        formatted[pk_name] = str(id)

        # Build UpdateExpression for partial update
        # DynamoDB requires SET expressions for each attribute
        update_expressions = []
        expression_attribute_names = {}
        expression_attribute_values = {}

        for attr_name, attr_value in formatted.items():
            # Skip the primary key as it's in the Key parameter
            if attr_name == pk_name:
                continue

            # Use attribute name placeholders to handle reserved words
            name_placeholder = f"#attr_{attr_name}"
            value_placeholder = f":val_{attr_name}"

            expression_attribute_names[name_placeholder] = attr_name
            expression_attribute_values[value_placeholder] = attr_value
            update_expressions.append(f"{name_placeholder} = {value_placeholder}")

        if not update_expressions:
            # No fields to update (only primary key was provided)
            # Just return the existing item
            return from_dynamodb(existing["Item"])

        # Build the update expression
        update_expression = f"SET {', '.join(update_expressions)}"

        # Perform partial update using update_item
        table.update_item(
            Key=key,
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values,
        )

        # Retrieve the updated item to return the full merged object
        try:
            updated = table.get_item(Key=key)
        except ClientError as e:
            if _is_resource_not_found(e):
                raise KeyError(f"Instance with id {id!r} not found after update") from e
            raise

        if "Item" not in updated:
            raise KeyError(f"Instance with id {id!r} not found after update")

        return from_dynamodb(updated["Item"])

    def delete(self, model: InLayersModel, id: PrimaryKeyType) -> None:
        """Delete an item by ID. No-op if table or item does not exist."""
        self.__ensure_connected()

        table_name = get_table_name_for_model(
            self.__context.config.environment, model.get_model_definition()
        )
        table = self.__table_client.Table(table_name)

        pk_name = model.get_primary_key_name()
        key = {pk_name: str(id)}

        try:
            table.delete_item(Key=key)
        except ClientError as e:
            if _is_resource_not_found(e):
                return
            raise

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

        table_name = get_table_name_for_model(
            self.__context.config.environment, model.get_model_definition()
        )
        table = self.__table_client.Table(table_name)

        # Start recursive scanning; return empty result if table does not exist
        try:
            result = self._do_search_until_threshold_or_no_last_evaluated_key(
                table, query, []
            )
        except ClientError as e:
            if _is_resource_not_found(e):
                return Box(instances=[], page=None)
            raise

        return Box(instances=result["instances"], page=result["page"])

    def count(self, model: InLayersModel) -> int:
        """Count items in the model table."""
        self.__ensure_connected()

        table_name = get_table_name_for_model(
            self.__context.config.environment, model.get_model_definition()
        )
        table = self.__table_client.Table(table_name)

        scan_kwargs: dict[str, Any] = {"Select": "COUNT"}
        total_count = 0
        while True:
            try:
                response = table.scan(**scan_kwargs)
            except ClientError as e:
                if _is_resource_not_found(e):
                    return 0
                raise
            total_count += int(response.get("Count", 0))
            last_evaluated_key = response.get("LastEvaluatedKey")
            if last_evaluated_key is None:
                return total_count
            scan_kwargs["ExclusiveStartKey"] = last_evaluated_key

    def _do_search_until_threshold_or_no_last_evaluated_key(
        self,
        table: Any,
        search: ModelSearch,
        old_instances_found: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Recursively scan DynamoDB until threshold is met or no more keys.

        This matches the TypeScript implementation's behavior of continuing
        to scan across pages until enough filtered results are found.
        """
        # Build scan parameters
        scan_kwargs: dict[str, Any] = {}
        # Ensure query is always a list (handle None case)
        query = getattr(search, "query", []) or []
        take = getattr(search, "take", None)
        sort = getattr(search, "sort", None)
        if getattr(search, "page", None):
            scan_kwargs["ExclusiveStartKey"] = search.page

        # Execute scan
        response = table.scan(**scan_kwargs)
        items = response.get("Items", [])

        # Convert DynamoDB items to plain dicts
        unfiltered = [from_dynamodb(item) for item in items]

        # Apply filtering using the same logic as MemoryBackend
        filtered = [r for r in unfiltered if _matches_query_tokens(r, query)]

        # Combine with previously found instances
        all_filtered = filtered + old_instances_found

        # Determine threshold
        using_take = take is not None and take > 0
        threshold = take if using_take else SCAN_RETURN_THRESHOLD

        # Get pagination key
        last_evaluated_key = response.get("LastEvaluatedKey")

        # Check stopping conditions:
        # 1. We have enough results (more than threshold)
        # 2. No more keys to evaluate
        # Note: TypeScript uses > (strictly greater), meaning we continue if we have exactly 'threshold' items
        stop_for_threshold = len(all_filtered) > threshold
        stop_for_no_more = last_evaluated_key is None

        if stop_for_threshold or stop_for_no_more:
            # Apply sorting and take limit
            sorted_instances = _apply_sort(all_filtered, sort)
            # Apply take limit (use original take value, not threshold)
            limited_instances = _apply_take(sorted_instances, take)

            # Return page: null when using take, otherwise return LastEvaluatedKey
            page = None if using_take else last_evaluated_key

            return {
                "instances": [dict(x) for x in limited_instances],
                "page": page,
            }

        # Continue scanning with the new page key
        # Create a new ModelSearch with updated page (frozen dataclass requires new instance)
        new_query = ModelSearch(
            query=query,
            take=take,
            sort=sort,
            page=last_evaluated_key,
        )
        return self._do_search_until_threshold_or_no_last_evaluated_key(
            table, new_query, all_filtered
        )

    def bulk_insert(self, model: InLayersModel, data: list[Mapping]) -> None:
        """Bulk insert items."""
        self.__ensure_connected()

        table_name = get_table_name_for_model(
            self.__context.config.environment, model.get_model_definition()
        )
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
        """Bulk delete items by IDs. No-op if table does not exist."""
        self.__ensure_connected()

        table_name = get_table_name_for_model(
            self.__context.config.environment, model.get_model_definition()
        )
        table = self.__table_client.Table(table_name)
        pk_name = model.get_primary_key_name()

        # Prepare keys
        keys = [{pk_name: str(id)} for id in ids]

        # Split into batches
        batches = split_array_into_batches(keys, MAX_BATCH_WRITE_SIZE)

        # Delete batches; tolerate missing table
        try:
            for batch in batches:
                with table.batch_writer() as writer:
                    for key in batch:
                        writer.delete_item(Key=key)
        except ClientError as e:
            if _is_resource_not_found(e):
                return
            raise

    def dispose(self) -> None:
        """Clean up resources."""
        self.__disconnect()
