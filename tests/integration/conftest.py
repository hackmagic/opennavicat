"""Shared fixtures for integration tests — spins up MySQL/PostgreSQL via testcontainers."""

from __future__ import annotations

import os

import pytest

# Skip all integration tests if Docker is not available
pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION", "") == "1",
    reason="SKIP_INTEGRATION=1",
)


@pytest.fixture(scope="session")
def mysql_container():
    """Start a MySQL container for integration tests."""
    try:
        from testcontainers.mysql import MySqlContainer
    except ImportError:
        pytest.skip("testcontainers not installed")

    container = MySqlContainer("mysql:8.0", user="test", password="test", database="testdb")
    container.start()
    yield container
    container.stop()


@pytest.fixture(scope="session")
def postgres_container():
    """Start a PostgreSQL container for integration tests."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed")

    container = PostgresContainer("postgres:16", user="test", password="test", dbname="testdb")
    container.start()
    yield container
    container.stop()


@pytest.fixture
def mysql_conn_info(mysql_container):
    """Create a ConnectionInfo pointing at the test MySQL container."""
    from open_navicat.models.connection import ConnectionInfo

    host = mysql_container.get_container_host_ip()
    port = mysql_container.get_exposed_port(3306)
    return ConnectionInfo(
        name="test-mysql",
        host=host,
        port=int(port),
        user="test",
        password="test",
        database="testdb",
        engine="mysql",
    )


@pytest.fixture
def pg_conn_info(postgres_container):
    """Create a ConnectionInfo pointing at the test PostgreSQL container."""
    from open_navicat.models.connection import ConnectionInfo

    host = postgres_container.get_container_host_ip()
    port = postgres_container.get_exposed_port(5432)
    return ConnectionInfo(
        name="test-pg",
        host=host,
        port=int(port),
        user="test",
        password="test",
        database="testdb",
        engine="postgresql",
    )
