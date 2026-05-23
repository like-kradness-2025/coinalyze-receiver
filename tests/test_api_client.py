from __future__ import annotations

import pytest
from unittest.mock import Mock

from coinalyze_receiver.api import CoinalyzeAPIError, CoinalyzeClient
from coinalyze_receiver.config import ReceiverConfig


def test_coinalyze_client_raises_api_error_on_sdk_exception():
    class DummyConfig:
        api_key = "dummy"

    mock_sdk = Mock()
    mock_sdk.get_future_markets.side_effect = IOError("network")

    client = CoinalyzeClient(DummyConfig())  # type: ignore[arg-type]
    client._client = mock_sdk

    with pytest.raises(CoinalyzeAPIError, match="future-markets failed"):
        client.markets()
