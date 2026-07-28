import json
from unittest.mock import MagicMock

from fastapi import Request

from app.error_handlers import _handle_domain_exception


async def test_handle_domain_exception_unknown_exception_returns_500():
    """Exception whose MRO doesn't match any mapped type → 500 fallback."""
    request = MagicMock(spec=Request)
    response = await _handle_domain_exception(request, ValueError("boom"))
    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": "boom"}
