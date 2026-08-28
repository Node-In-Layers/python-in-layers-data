"""MongoDB backend implementation for InLayers models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from box import Box
from in_layers.core.models.protocols import (
    InLayersModel,
    ModelSearch,
    ModelSearchResult,
    PrimaryKeyType,
    SortOrder,
)

from in_layers.data.protocols import MongoBackendConfig

from .libs import (
    format_for_mongo,
    get_collection_name_for_model,
    to_mongo,
)


class MongoBackend:
    """MongoDB backend implementation."""

    def __init__(self, context, config: MongoBackendConfig):
        self.__context = context
        self.__config = config
        self.__client: Any = None

    @staticmethod
    def create_unique_connection_string(config: MongoBackendConfig) -> str:
        """Create a unique connection string from config."""
        host = config.host
        port = getattr(config, "port", None)
        username = getattr(config, "username", None)
        password = getattr(config, "password", None)
        database = getattr(config, "database", None)

        connection_string = "mongodb://"
        if username:
            connection_string += f"{username}:{password}@"
        connection_string += f"{host}"
        if port:
            connection_string += f":{port}"
        if database:
            connection_string += f"/{database}"
        return connection_string

    def __connect(self) -> None:
        """Connect to MongoDB (private method)."""
        from pymongo import MongoClient  # noqa: PLC0415

        connection_string = self.create_unique_connection_string(self.__config)
        self.__client = MongoClient(connection_string)

    def __get_database(self):
        default_database_name = f"{self.__context.config.system_name}-{self.__context.config.environment}".lower()
        database_name = getattr(self.__config, "database", default_database_name)
        return self.__client[database_name]

    def __disconnect(self) -> None:
        """Disconnect from MongoDB (private method)."""
        if self.__client:
            self.__client.close()
            self.__client = None

    def __ensure_connected(self) -> None:
        """Ensure MongoDB connection is established."""
        if self.__client is None:
            self.__connect()

    def get_raw_client(self) -> Any:
        self.__ensure_connected()
        return self.__get_database()

    def get_backend_name(self) -> str:
        return "mongodb"

    def create(self, model: InLayersModel, data: Mapping) -> Mapping:
        """Create a new document in MongoDB."""
        self.__ensure_connected()

        collection_name = get_collection_name_for_model(model.get_model_definition())
        database = self.__get_database()
        collection = database[collection_name]
        payload = dict(data)
        formatted = format_for_mongo(payload)

        pk_name = model.get_primary_key_name()
        pk_value = formatted.get(pk_name)
        if pk_value is None:
            # Generate a simple ID - in production you might want UUID

            pk_value = str(uuid4())
            formatted[pk_name] = pk_value

        # Use _id as MongoDB's primary key, mapping from model's primary key
        insert_data = {**formatted, "_id": pk_value}
        collection.insert_one(insert_data)
        # Return without _id
        result = {k: v for k, v in insert_data.items() if k != "_id"}
        return result

    def retrieve(self, model: InLayersModel, id: PrimaryKeyType) -> Mapping | None:
        """Retrieve a document by ID."""
        self.__ensure_connected()

        collection_name = get_collection_name_for_model(model.get_model_definition())
        database = self.__get_database()
        collection = database[collection_name]
        doc = collection.find_one({"_id": id})
        if not doc:
            return None
        # Remove _id and return
        result = {k: v for k, v in doc.items() if k != "_id"}
        return result

    def update(
        self, model: InLayersModel, id: PrimaryKeyType, data: Mapping
    ) -> Mapping:
        """Update a document by ID.

        Supports partial updates - only the fields provided in data will be updated.
        Returns the full merged object (original + updates).
        """
        self.__ensure_connected()

        collection_name = get_collection_name_for_model(model.get_model_definition())
        database = self.__get_database()
        collection = database[collection_name]

        # Check if document exists
        existing = collection.find_one({"_id": id})
        if not existing:
            raise KeyError(f"Instance with id {id!r} not found")

        payload = dict(data)
        formatted = format_for_mongo(payload)

        # Ensure primary key field remains consistent
        pk_name = model.get_primary_key_name()
        formatted[pk_name] = id

        # Update with _id mapping - use $set for partial update
        update_data = {**formatted, "_id": id}
        collection.update_one({"_id": id}, {"$set": update_data})

        # Retrieve the updated document to return the full merged object
        updated = collection.find_one({"_id": id})
        if not updated:
            raise KeyError(f"Instance with id {id!r} not found after update")

        # Return without _id
        result = {k: v for k, v in updated.items() if k != "_id"}
        return result

    def delete(self, model: InLayersModel, id: PrimaryKeyType) -> None:
        """Delete a document by ID."""
        self.__ensure_connected()

        collection_name = get_collection_name_for_model(model.get_model_definition())
        database = self.__get_database()
        collection = database[collection_name]
        collection.delete_one({"_id": id})

    def search(self, model: InLayersModel, query: ModelSearch) -> ModelSearchResult:
        """Search for documents matching the query."""
        self.__ensure_connected()

        collection_name = get_collection_name_for_model(model.get_model_definition())
        database = self.__get_database()
        collection = database[collection_name]

        # Build aggregation pipeline
        pipeline = []

        # Add match stage if there's a query
        if query.query:
            mongo_query = to_mongo(query.query)
            pipeline.extend(mongo_query)
        else:
            pipeline.append({"$match": {}})

        # Add sort stage if needed
        if query.sort:
            sort_direction = 1 if query.sort.order == SortOrder.asc else -1
            pipeline.append({"$sort": {query.sort.key: sort_direction}})

        # Add limit stage if needed
        if query.take:
            pipeline.append({"$limit": query.take})

        # Execute aggregation
        results = list(collection.aggregate(pipeline))
        instances = [{k: v for k, v in doc.items() if k != "_id"} for doc in results]

        return Box(instances=instances, page=query.page)

    def bulk_insert(self, model: InLayersModel, data: list[Mapping]) -> None:
        """Bulk insert documents."""
        from pymongo.operations import UpdateOne  # noqa: PLC0415

        self.__ensure_connected()

        collection_name = get_collection_name_for_model(model.get_model_definition())
        database = self.__get_database()
        collection = database[collection_name]
        pk_name = model.get_primary_key_name()

        # Prepare bulk write operations
        operations = []
        for item in data:
            payload = dict(item)
            formatted = format_for_mongo(payload)

            pk_value = formatted.get(pk_name)
            if pk_value is None:
                pk_value = str(uuid4())
                formatted[pk_name] = pk_value

            doc = {**formatted, "_id": pk_value}
            operations.append(
                UpdateOne(
                    {"_id": pk_value},
                    {"$set": doc},
                    upsert=True,
                )
            )

        if operations:
            collection.bulk_write(operations)

    def bulk_delete(self, model: InLayersModel, ids: list[PrimaryKeyType]) -> None:
        """Bulk delete documents by IDs."""
        self.__ensure_connected()

        collection_name = get_collection_name_for_model(model.get_model_definition())
        database = self.__get_database()
        collection = database[collection_name]
        collection.delete_many({"_id": {"$in": ids}})

    def dispose(self) -> None:
        """Clean up resources."""
        self.__disconnect()
