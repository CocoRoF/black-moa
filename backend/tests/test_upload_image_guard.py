from __future__ import annotations

import pytest

from memora.core.errors import ValidationFailed
from memora.services.uploads import _resize_image, _sniff


def test_magic_prefixed_but_malformed_image_fails_closed():
    data = b"\xff\xd8\xffnot-a-real-jpeg"
    assert _sniff(data, "image/jpeg") == "image/jpeg"
    with pytest.raises(ValidationFailed) as exc:
        _resize_image(data, "image/jpeg")
    assert exc.value.code == "invalid_image"
