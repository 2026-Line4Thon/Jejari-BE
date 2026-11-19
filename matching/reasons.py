"""
매칭 근거 문장 (S-09). 화면에 [{field, is_match, text}] 형태로 내려줍니다.

- 기본: 점수 계산 결과로 만드는 규칙 기반 문장 (항상 생성)
- 상위 후보: AI가 두 물건의 공개 정보만 보고 자연스러운 문장으로 다시 씀
  (습득물의 private_features는 입력에 절대 넣지 않음)
"""

import logging

from ai.services import AIError, write_match_reasons

from . import scoring

logger = logging.getLogger(__name__)

FIELDS = ('category', 'color', 'appearance', 'place', 'time')


def rule_reasons(lost, found, facts, scores):
    reasons = []

    is_cat = scoring.category_match(lost.category, found.category)
    reasons.append({
        'field': 'category',
        'is_match': is_cat,
        'text': (f'두 물건 모두 {found.category} 종류입니다.' if is_cat
                 else f'분실물은 {lost.category}, 습득물은 {found.category}로 종류가 다릅니다.'),
    })

    if lost.color and found.color:
        is_color = scoring.color_match(lost.color, found.color)
        text = (f'색상이 {found.color}(으)로 같거나 비슷합니다.' if is_color
                else f'분실물은 {lost.color}, 습득물은 {found.color}로 색상이 다릅니다.')
    else:
        is_color, text = False, '한쪽에 색상 정보가 없어 비교하지 못했습니다.'
    reasons.append({'field': 'color', 'is_match': is_color, 'text': text})

    is_look = scores['embedding'] >= 0.6
    reasons.append({
        'field': 'appearance',
        'is_match': is_look,
        'text': '물건 설명의 외형 특징이 비슷합니다.' if is_look else '물건 설명의 외형 특징이 일부만 비슷합니다.',
    })

    if facts.same_place:
        place_text = f'분실 장소와 습득 장소가 모두 {found.place.name}입니다.'
    else:
        place_text = (f'분실 장소({lost.place.name})와 습득 장소({found.place.name})가 '
                      f'약 {round(facts.distance_m, -1):.0f}m 떨어져 있습니다.')
    reasons.append({'field': 'place', 'is_match': scores['place'] >= 0.5, 'text': place_text})

    if facts.gap_hours <= 0:
        time_text = '분실 추정 시간 안에 습득되었습니다.'
    elif facts.gap_hours < 3:
        time_text = '분실 추정 시간 직후에 습득되었습니다.'
    else:
        time_text = f'분실 추정 시간 이후 약 {facts.gap_hours:.0f}시간 뒤에 습득되었습니다.'
    reasons.append({'field': 'time', 'is_match': scores['time'] >= 0.5, 'text': time_text})

    return reasons


def _public_item(item, when):
    return {
        'category': item.category,
        'item_name': item.item_name,
        'color': item.color,
        'brand': item.brand,
        'features': item.features or [],
        'description': item.description,
        'place': item.place.name,
        'location_detail': item.location_detail,
        **when,
    }


def ai_reasons(lost, found, base_reasons):
    """AI로 근거 문장을 다시 씀. 실패하거나 형식이 맞지 않으면 규칙 기반 문장을 그대로 반환."""
    payload = {
        'lost_item': _public_item(lost, {
            'lost_from': lost.lost_from.isoformat(), 'lost_to': lost.lost_to.isoformat(),
        }),
        # private_features는 넣지 않음 (소유권 확인 전용 비공개 정보)
        'found_item': _public_item(found, {'found_at': found.found_at.isoformat()}),
        'rule_based': base_reasons,
    }
    try:
        written = write_match_reasons(payload)
    except AIError as exc:
        logger.info('매칭 근거 생성 실패, 규칙 기반 사용: %s', exc)
        return base_reasons

    by_field = {r.get('field'): r for r in written if isinstance(r, dict)}
    result = []
    for base in base_reasons:
        r = by_field.get(base['field'])
        text = (r or {}).get('text')
        if isinstance(text, str) and text.strip():
            # 일치 여부는 점수 계산 결과를 그대로 사용 (AI가 판정을 바꾸지 않도록)
            result.append({**base, 'text': text.strip()})
        else:
            result.append(base)
    return result
