"""Behave environment configuration and hooks."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

# Add features directory to path for imports
features_dir = Path(__file__).parent
if str(features_dir) not in sys.path:
    sys.path.insert(0, str(features_dir))

# Import after path is set up
from steps.steps import _cleanout_database
from testcontainers.core.container import DockerContainer

MONGO_IMAGE = os.environ.get("IN_LAYERS_TEST_MONGO_IMAGE", "mongo:8.0")
MONGO_PORT = 27017
MONGO_STARTUP_TIMEOUT_SECONDS = 120
REDIS_STACK_IMAGE = "redis/redis-stack-server:latest"
REDIS_PORT = 6379
REDIS_STARTUP_TIMEOUT_SECONDS = 120


def _wait_for_mongo(url: str) -> None:
    from pymongo import MongoClient  # pragma: no cover # noqa: PLC0415

    last_error = None
    started_at = time.monotonic()
    while time.monotonic() - started_at < MONGO_STARTUP_TIMEOUT_SECONDS:
        client = None
        try:
            client = MongoClient(url, serverSelectionTimeoutMS=1000)
            client.admin.command("ping")
            client.close()
            return
        except Exception as error:
            last_error = error
            time.sleep(1)
        finally:
            if client is not None:
                client.close()
    raise RuntimeError("Mongo test container did not become ready") from last_error


def _wait_for_redis(url: str) -> None:
    import redis  # pragma: no cover # noqa: PLC0415

    last_error = None
    started_at = time.monotonic()
    while time.monotonic() - started_at < REDIS_STARTUP_TIMEOUT_SECONDS:
        client = None
        try:
            client = redis.from_url(url, decode_responses=True)
            client.ping()
            client.close()
            return
        except Exception as error:
            last_error = error
            time.sleep(1)
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
    raise RuntimeError(
        "Redis Stack test container did not become ready"
    ) from last_error


def _start_mongo_container(context) -> None:
    container = DockerContainer(MONGO_IMAGE).with_exposed_ports(MONGO_PORT)
    container.start()
    host = container.get_container_host_ip()
    port = container.get_exposed_port(MONGO_PORT)
    context.mongo_container = container
    context.mongo_url = f"mongodb://{host}:{port}"
    _wait_for_mongo(context.mongo_url)


def _start_redis_stack_container(context) -> None:
    container = DockerContainer(REDIS_STACK_IMAGE).with_exposed_ports(REDIS_PORT)
    container.start()
    host = container.get_container_host_ip()
    port = container.get_exposed_port(REDIS_PORT)
    context.redis_container = container
    context.redis_url = f"redis://{host}:{port}"
    _wait_for_redis(context.redis_url)


def _stop_mongo_container(context) -> None:
    container = getattr(context, "mongo_container", None)
    if container is None:
        return
    container.stop()
    delattr(context, "mongo_container")
    if hasattr(context, "mongo_url"):
        delattr(context, "mongo_url")


def _stop_redis_stack_container(context) -> None:
    container = getattr(context, "redis_container", None)
    if container is None:
        return
    container.stop()
    delattr(context, "redis_container")
    if hasattr(context, "redis_url"):
        delattr(context, "redis_url")


def before_scenario(context, scenario):
    """Run before each scenario."""
    effective_tags = getattr(scenario, "effective_tags", scenario.tags)
    context.backend_name = "redis" if "redis" in effective_tags else "mongodb"
    if context.backend_name == "redis":
        _start_redis_stack_container(context)
    else:
        _start_mongo_container(context)
    _cleanout_database(context)
    # Setup will be done in the "an orm is setup" step


def after_scenario(context, scenario):
    """Run after each scenario."""
    if hasattr(context, "backend"):
        context.backend.dispose()
        delattr(context, "backend")
    try:
        _cleanout_database(context)
    finally:
        if getattr(context, "backend_name", None) == "redis":
            _stop_redis_stack_container(context)
        else:
            _stop_mongo_container(context)
