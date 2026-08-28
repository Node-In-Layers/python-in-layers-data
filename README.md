# In Layers Data 
A data layer for the In Layers Core framework. 

NOTE: There are no explicit dependencies on any database. To use a specific database you must install it in your own system. These databases are "imported in" as the databases are actually used at runtime.

Compatible with `in-layers-core` `1.x`.

## How To Use
1. Install in-layers-data
1. Set `"in_layers_data"` to the `in_layers_core.models.model_backend` property
1. Add `in_layers_data` configuration to your config
1. Install database libraries to use. Example: `pymongo` or `boto3`
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
                type="mongodb"
                # Connection information here
            ),
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

## Database Info
### Mongo 
Mongodb requires `pymongo`

### Dynamodb
Dynamodb requires `boto3`

#### Important
Dynamodb is very poor at performing search queries. While this is implemented, it is not-recommended for use. Instead use the retrieve.