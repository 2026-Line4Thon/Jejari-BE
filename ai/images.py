"""사진 전처리와 민감정보 블러 (S-04). 영역 탐지 없이 사진 전체를 블러합니다."""

import io

from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

PUBLIC_MAX_SIDE = 1600  # 공개용 이미지 최대 변 길이
AI_MAX_SIDE = 1024  # AI 분석용 (토큰 절약)
JPEG_QUALITY = 85


class InvalidImage(ValueError):
    pass


ALLOWED_FORMATS = ('JPEG', 'PNG')


def load_image(file):
    """업로드 파일 → 방향 보정된 RGB 이미지. EXIF(위치 정보 등)는 이후 저장 시 제거됨."""
    try:
        image = Image.open(file)
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImage('이미지 파일을 읽을 수 없습니다.') from exc
    if image.format not in ALLOWED_FORMATS:
        raise InvalidImage(f'지원하지 않는 이미지 형식입니다: {image.format}')
    image = ImageOps.exif_transpose(image)
    return _to_rgb_on_white(image)


def _to_rgb_on_white(image):
    """
    RGB로 변환. 투명 배경(PNG 등)은 그냥 convert('RGB')하면 검은색이 되므로 흰 배경 위에 합성한다.
    (검은 물건이 검은 배경에 묻혀 안 보이는 문제 방지)
    """
    if image.mode == 'P' and 'transparency' in image.info:
        image = image.convert('RGBA')
    if image.mode in ('RGBA', 'LA'):
        background = Image.new('RGB', image.size, (255, 255, 255))
        background.paste(image, mask=image.getchannel('A'))
        return background
    return image.convert('RGB') if image.mode != 'RGB' else image


def resized(image, max_side):
    image = image.copy()
    image.thumbnail((max_side, max_side))
    return image


def to_jpeg_bytes(image, max_side=PUBLIC_MAX_SIDE):
    buffer = io.BytesIO()
    resized(image, max_side).save(buffer, format='JPEG', quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue()


def blur(image):
    """사진 전체를 알아볼 수 없을 정도로 블러. 반경은 이미지 크기에 비례."""
    radius = max(image.size) / 25
    return image.filter(ImageFilter.GaussianBlur(radius=radius))
