from dataclasses import dataclass
from io import BytesIO
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()
Image.MAX_IMAGE_PIXELS = 30_000_000


class InvalidImage(ValueError):
    pass


@dataclass
class NormalizedImage:
    data: bytes
    width: int
    height: int
    thumbnail: bytes


def normalize_image(data: bytes, max_bytes: int = 12 * 1024 * 1024, min_dimension: int = 128) -> NormalizedImage:
    if not data or len(data) > max_bytes:
        raise InvalidImage('Choose an image smaller than 12 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in {'JPEG', 'PNG', 'WEBP', 'HEIF', 'HEIC'}:
                    raise InvalidImage('Use JPEG, PNG, WebP or HEIC images.')
                if min(source.size) < min_dimension or max(source.size) / min(source.size) > 8:
                    raise InvalidImage('Choose a clear photo at least 128 pixels on each side with a normal portrait aspect ratio.')
                source.load()
                oriented = ImageOps.exif_transpose(source)
                if oriented.mode in {'RGBA', 'LA'} or 'transparency' in oriented.info:
                    rgba = oriented.convert('RGBA')
                    white = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
                    image = Image.alpha_composite(white, rgba).convert('RGB')
                else:
                    image = oriented.convert('RGB')
                image.thumbnail((3072, 3072), Image.Resampling.LANCZOS)
                out = BytesIO()
                image.save(out, format='JPEG', quality=94, optimize=True)
                if len(out.getvalue()) > 7 * 1024 * 1024:
                    # Keep inline provider images within Google's 7 MB limit.
                    out = BytesIO()
                    image.save(out, format='JPEG', quality=88, optimize=True)
                if len(out.getvalue()) > 7 * 1024 * 1024:
                    raise InvalidImage('This image remains too large after normalization. Choose a smaller photo.')
                thumb = image.copy()
                thumb.thumbnail((400, 400), Image.Resampling.LANCZOS)
                small = BytesIO()
                thumb.save(small, format='JPEG', quality=86, optimize=True)
                return NormalizedImage(out.getvalue(), image.width, image.height, small.getvalue())
    except InvalidImage:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise InvalidImage('This image could not be decoded safely. Try a different photo.') from exc
