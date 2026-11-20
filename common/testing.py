"""
테스트용 데이터 생성 헬퍼.

LostItem·FoundItem은 place, image, description, text_embedding 등 필수 컬럼이 많아서
테스트마다 직접 채우지 않고 이 함수들로 만들고, 필요한 값만 kwargs로 덮어씁니다.
"""

from itertools import count

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

_seq = count(1)


def zero_vector():
    return [0.0] * settings.EMBEDDING_DIMENSIONS


def make_user(**kwargs):
    n = next(_seq)
    kwargs.setdefault('email', f'user{n}@university.ac.kr')
    kwargs.setdefault('nickname', f'익명학우{n}')
    return get_user_model().objects.create_user(**kwargs)


def make_place(**kwargs):
    from places.models import Place

    n = next(_seq)
    name = kwargs.pop('name', f'테스트건물{n}')
    kwargs.setdefault('latitude', '37.5000000')
    kwargs.setdefault('longitude', '127.0000000')
    # places 0002 마이그레이션이 테스트 DB에도 캠퍼스 건물을 넣으므로, 같은 이름이면 좌표만 테스트 값으로 맞춰 재사용
    place, _ = Place.objects.update_or_create(name=name, defaults=kwargs)
    return place


def make_image(uploader, **kwargs):
    from items.models import ItemImage

    n = next(_seq)
    kwargs.setdefault('image_url', f'https://s3.example.com/public/{n}.jpg')
    kwargs.setdefault('original_image_key', f'private/{n}.jpg')
    return ItemImage.objects.create(uploader=uploader, **kwargs)


def make_found_item(finder, **kwargs):
    from items.models import FoundItem

    if 'place' not in kwargs:
        kwargs['place'] = make_place()
    if 'image' not in kwargs:
        kwargs['image'] = make_image(finder)
    kwargs.setdefault('category', '전자기기')
    kwargs.setdefault('item_name', '무선 이어폰 케이스')
    kwargs.setdefault('description', kwargs['item_name'])
    kwargs.setdefault('found_at', timezone.now())
    kwargs.setdefault('text_embedding', zero_vector())
    return FoundItem.objects.create(finder=finder, **kwargs)


def make_lost_item(user, **kwargs):
    from items.models import LostItem

    now = timezone.now()
    if 'place' not in kwargs:
        kwargs['place'] = make_place()
    kwargs.setdefault('category', '전자기기')
    kwargs.setdefault('item_name', '무선 이어폰 케이스')
    kwargs.setdefault('description', kwargs['item_name'])
    kwargs.setdefault('lost_from', now - timezone.timedelta(hours=3))
    kwargs.setdefault('lost_to', now)
    kwargs.setdefault('text_embedding', zero_vector())
    return LostItem.objects.create(user=user, **kwargs)


def make_candidate(lost_item, found_item, **kwargs):
    from matching.models import MatchCandidate

    kwargs.setdefault('total_score', 0.8)
    kwargs.setdefault('similarity_label', MatchCandidate.SimilarityLabel.HIGH)
    return MatchCandidate.objects.create(lost_item=lost_item, found_item=found_item, **kwargs)
