# In Layers Data
A data layer for the In Layers Core framework.

NOTE: There are no explicit dependencies on any database. To use a specific database you must install it in your own system. These databases are "imported in" as the databases are actually used at runtime.

## How To Use
1. Install in-layers-data
1. Set `"in_layers_data"` to the `in_layers_core.models.model_backend` property
1. Add `in_layers_data` configuration to your config
1. Install database libraries to use. Example: `pymongo`, `boto3`, or `redis`
1. Dispose the data services when your application shuts down so database connections are cleaned up

### Configuration Example
```python
# config_base.py
from box import Box
def get_base_config():
    return Box(
        ...,
        in_layers_core=Box(
            ...
            models=Box(
                model_backend="in_layers_data",
            )
        ),
        in_layers_data=Box(
            default=Box(
                type="redis",
                host="localhost",
                port=6379,
                redis_stack=True,
                # Connection information here
            ),
            # Example JSON backend:
            # default=Box(
            #     type="json",
            #     file_path="./tmp/dev-database.json",
            #     directory_mode=False,
            #     write_buffer_ms=10,
            # ),
            # Optional: Set "domain" or "domain.ModelPluralNames" to a specific database configuration.
            # model_to_backend=Box(
            #     "domain.ModelPluralNames"=Box(
            #         type="mongodb",
            #         host="different-host"
            #     )
            # )
        )
    )


```

### Backend Routing Order

When `model_to_backend` is configured, backend selection works in this order:

1. `domain.ModelPluralName`
1. `domain`
1. `default`

This lets you set a default backend, override an entire domain, and still override an individual model when needed.

### Shutdown / Cleanup Example

Call `system.services["in_layers_data"].dispose()` during shutdown. This is important for cleaning up backend resources such as database clients.

```python
from in_layers.core import SystemProps, load_system

from config_base import get_base_config


def main():
    system = load_system(
        SystemProps(
            environment="prod",
            config=get_base_config(),
        )
    )

    try:
        users = system.services["mydomain"].cruds["Users"].search({})
        print(users)
    finally:
        system.services["in_layers_data"].dispose()
```

## Key Features
- Drop in, Swappable Databases
- Multi-database support
- Low dependencies 

## Databases Supported
- Mongodb
- Dynamodb
- Redis
- Json

## Database Info
### Mongo 
Mongodb requires `pymongo`

### Dynamodb
Dynamodb requires `boto3`

### Redis
Redis requires `redis`. Redis search support is implemented against Redis Stack / RediSearch and expects `redis_stack=True` in backend configuration.

### Json
Json uses the Python standard library only, so it does not require an additional database client package.

Supported JSON backend config:

```python
default=Box(
    type="json",
    file_path="./tmp/dev-database.json",
    directory_mode=False,
    write_buffer_ms=10,
)
```

- `file_path` points to a single JSON file, or to a directory root when `directory_mode=True`
- `directory_mode=True` stores one JSON file per model collection
- writes are buffered in memory and flushed on read/dispose
- shutdown should still call `system.services["in_layers_data"].dispose()` so pending writes are persisted
- TTL is model-scoped, not backend-wide. To enable expiry for a model, declare
  `ttl_property_name` on the `@model(...)` decorator in `in-layers-core`, for
  example `@model(..., ttl_property_name="ttl")`.
- When `ttl_property_name` is set, the JSON backend automatically deletes
  expired records for that model. TTL values should be integer Unix timestamps
  in minutes.

### Feature Tests
Mongo and Redis feature tests both spin up containers automatically with `testcontainers`, so they do not require long-lived local database instances. Mongo uses a `mongo` image and Redis uses `redis/redis-stack-server`.

If you want to point feature tests at existing local services instead, you can still provide `mongoUrl` and `redisUrl` in `.env-cucumber.json` as overrides.

#### Important
Dynamodb is very poor at performing search queries. While this is implemented, it is not-recommended for use. Instead use the retrieve.