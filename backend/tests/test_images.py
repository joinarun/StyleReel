from io import BytesIO

import pytest
from PIL import Image

from app.images import normalize_image


@pytest.mark.parametrize('dimensions', [(64, 96), (1024, 80), (80, 1024)])
def test_decodable_small_or_unusual_photos_are_normalized_without_quality_gate(dimensions):
    buffer = BytesIO()
    Image.new('RGB', dimensions, '#507a9c').save(buffer, 'PNG')
    result = normalize_image(buffer.getvalue())
    assert (result.width, result.height) == dimensions
    with Image.open(BytesIO(result.data)) as image:
        assert image.format == 'JPEG'
        assert image.size == dimensions
