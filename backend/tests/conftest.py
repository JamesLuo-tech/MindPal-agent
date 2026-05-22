import pytest
import pytest_asyncio
from unittest.mock import AsyncMock


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def mock_redis():
    return AsyncMock()
