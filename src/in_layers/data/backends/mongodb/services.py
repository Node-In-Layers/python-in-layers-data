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

    def __init__(self, config: MongoBackendConfig):
        self.__config = config
        self.__client: Any = None
        self.__db: Any = None

    @staticmethod
    def create_unique_connection_string(config: MongoBackendConfig) -> str:
        """Create a unique connection string from config."""
        host = config.host
        port = config.port
        username = config.username
        password = config.password
        database = config.database

        if username and password:
            return f"mongodb://{username}:{password}@{host}:{port}/{database}"
        return f"mongodb://{host}:{port}/{database}"

    def __connect(self) -> None:
        """Connect to MongoDB (private method)."""
        from pymongo import MongoClient  # noqa: PLC0415

        connection_string = self.create_unique_connection_string(
            {
                "host": self.__config.host,
                "port": self.__config.port,
                "username": self.__config.username,
                "password": self.__config.password,
                "database": self.__config.database,
            }
        )
        self.__client = MongoClient(connection_string)
        self.__db = self.__client[self.__config.database]

    def __disconnect(self) -> None:
        """Disconnect from MongoDB (private method)."""
        if self.__client:
            self.__client.close()
            self.__client = None
            self.__db = None

    def __ensure_connected(self) -> None:
        """Ensure MongoDB connection is established."""
        if self.__db is None:
            self.__connect()

    def create(self, model: InLayersModel, data: Mapping) -> Mapping:
        """Create a new document in MongoDB."""
        self.__ensure_connected()

        collection_name = get_collection_name_for_model(model.get_model_definition())
        collection = self.__db[collection_name]
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
        collection = self.__db[collection_name]
        doc = collection.find_one({"_id": id})
        if not doc:
            return None
        # Remove _id and return
        result = {k: v for k, v in doc.items() if k != "_id"}
        return result

    def update(
        self, model: InLayersModel, id: PrimaryKeyType, data: Mapping
    ) -> Mapping:
        """Update a document by ID."""
        self.__ensure_connected()

        collection_name = get_collection_name_for_model(model.get_model_definition())
        collection = self.__db[collection_name]

        # Check if document exists
        existing = collection.find_one({"_id": id})
        if not existing:
            raise KeyError(f"Instance with id {id!r} not found")

        payload = dict(data)
        formatted = format_for_mongo(payload)

        # Ensure primary key field remains consistent
        pk_name = model.get_primary_key_name()
        formatted[pk_name] = id

        # Update with _id mapping
        update_data = {**formatted, "_id": id}
        collection.update_one({"_id": id}, {"$set": update_data})

        # Return without _id
        result = {k: v for k, v in update_data.items() if k != "_id"}
        return result

    def delete(self, model: InLayersModel, id: PrimaryKeyType) -> None:
        """Delete a document by ID."""
        self.__ensure_connected()

        collection_name = get_collection_name_for_model(model.get_model_definition())
        collection = self.__db[collection_name]
        collection.delete_one({"_id": id})

    def search(self, model: InLayersModel, query: ModelSearch) -> ModelSearchResult:
        """Search for documents matching the query."""
        self.__ensure_connected()

        collection_name = get_collection_name_for_model(model.get_model_definition())
        collection = self.__db[collection_name]

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
        collection = self.__db[collection_name]
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
        collection = self.__db[collection_name]
        collection.delete_many({"_id": {"$in": ids}})

    def dispose(self) -> None:
        """Clean up resources."""
        self.__disconnect()
