# In Layers Data 
A data layer for the In Layers Core framework. 

NOTE: There are no explicit dependencies on any database. To use a specific database you must install it in your own system. These databases are "imported in" as the databases are actually used at runtime.

## How To Use
1. Install in-layers-data
1. Set `"in_layers_data"` to the `in_layers_core.models.model_backend` property
1. Add `in_layers_data` configuration to your config
1. Install database libraries to use. Example: `pymongo` or `boto3`

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