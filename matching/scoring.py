"""
매칭 점수 계산 (S-05 ~ S-08). DB·AI를 쓰지 않는 순수 함수라 테스트와 튜닝이 쉽도록 분리.

최종 점수 = 임베딩 0.5 + 태그(종류·색상·브랜드) 0.2 + 장소 0.2 + 시간 0.1
"""

import math
from dataclasses import dataclass

WEIGHTS = {'embedding': 0.5, 'tag': 0.2, 'place': 0.2, 'time': 0.1}

# 텍스트 임베딩 코사인 유사도는 관련 없는 문장도 0.2~0.3 정도가 나와서 0~1로 다시 펼친다.
EMBEDDING_SIM_FLOOR = 0.25
EMBEDDING_SIM_CEIL = 0.85

# 이 거리 이상 떨어지면 장소 점수 0. 시드된 캠퍼스(places 0002)는 건물 간 최대 약 350m라 400m로 설정
PLACE_ZERO_DISTANCE_M = 400
TIME_ZERO_GAP_HOURS = 72  # 분실 추정 시간 이후 이만큼 지나 습득하면 시간 점수 0

MIN_TOTAL_SCORE = 0.5  # 이 점수 이상만 후보로 저장
LABEL_THRESHOLDS = (('HIGH', 0.75), ('MEDIUM', 0.6), ('LOW', 0.0))

# 같은 색으로 볼 표현 묶음 (사용자·AI가 서로 다르게 쓰는 경우)
COLOR_GROUPS = [
    {'검정', '검은', '검은색', '블랙', '까만', '까만색', '흑색'},
    {'흰', '흰색', '하얀', '하얀색', '화이트', '백색', '아이보리', '크림', '미색'},
    {'회색', '그레이', '쥐색', '은색', '실버'},
    {'남색', '네이비', '감색', '진파랑', '진한 파랑'},
    {'파랑', '파란', '파란색', '블루', '하늘색', '스카이블루'},
    {'빨강', '빨간', '빨간색', '붉은', '레드', '적색'},
    {'분홍', '분홍색', '핑크', '연분홍'},
    {'노랑', '노란', '노란색', '옐로', '옐로우'},
    {'초록', '초록색', '녹색', '그린', '연두', '연두색', '카키'},
    {'갈색', '브라운', '고동색', '밤색', '베이지'},
    {'보라', '보라색', '퍼플', '라벤더'},
    {'주황', '주황색', '오렌지'},
    {'금색', '골드'},
]


@dataclass
class PairFacts:
    """점수 계산에 필요한 두 물건의 정보 (모델 객체 대신 값만)."""

    embedding_similarity: float
    lost_category: str
    found_category: str
    lost_color: str | None
    found_color: str | None
    lost_brand: str | None
    found_brand: str | None
    same_place: bool
    distance_m: float
    gap_hours: float  # 분실 추정 끝 시각 이후 습득까지 걸린 시간 (범위 안이면 0)


def _norm(text):
    return (text or '').replace(' ', '').lower()


def _strip_saek(text):
    """'붉은색' → '붉은'. 색 이름 끝의 '색'을 떼서 비교."""
    return text[:-1] if len(text) > 1 and text.endswith('색') else text


def _color_key(color):
    """
    같은 색으로 볼 묶음 번호. 단순 포함 비교만 하면 '붉은색'에 '은색'(회색 묶음)이 걸리므로
    1) '색'을 뗀 단어가 정확히 같은 묶음을 먼저 찾고 2) 없으면 가장 길게 포함되는 단어의 묶음을 쓴다.
    """
    if not color:
        return None
    value = _norm(color)
    base = _strip_saek(value)
    best, best_len = None, 0
    for i, group in enumerate(COLOR_GROUPS):
        for word in group:
            word = _strip_saek(_norm(word))
            if base == word:
                return i
            if word in value and len(word) > best_len:
                best, best_len = i, len(word)
    return best if best is not None else value


def category_match(a, b):
    a, b = _norm(a), _norm(b)
    return bool(a and b and (a == b or a in b or b in a))


def color_match(a, b):
    ka, kb = _color_key(a), _color_key(b)
    return ka is not None and ka == kb


def brand_match(a, b):
    return bool(a and b and _norm(a) == _norm(b))


def embedding_score(similarity):
    scaled = (similarity - EMBEDDING_SIM_FLOOR) / (EMBEDDING_SIM_CEIL - EMBEDDING_SIM_FLOOR)
    return min(1.0, max(0.0, scaled))


def tag_score(facts):
    """비교 가능한 항목(양쪽 다 값이 있는 항목)만 평균. 종류는 항상 비교."""
    results = [category_match(facts.lost_category, facts.found_category)]
    if facts.lost_color and facts.found_color:
        results.append(color_match(facts.lost_color, facts.found_color))
    if facts.lost_brand and facts.found_brand:
        results.append(brand_match(facts.lost_brand, facts.found_brand))
    return sum(results) / len(results)


def place_score(facts):
    if facts.same_place:
        return 1.0
    return max(0.0, 1 - facts.distance_m / PLACE_ZERO_DISTANCE_M)


def time_score(facts):
    return max(0.0, 1 - facts.gap_hours / TIME_ZERO_GAP_HOURS)


def score(facts):
    """항목별 점수 dict와 가중 합산 점수를 반환."""
    scores = {
        'embedding': embedding_score(facts.embedding_similarity),
        'tag': tag_score(facts),
        'place': place_score(facts),
        'time': time_score(facts),
    }
    total = sum(WEIGHTS[k] * v for k, v in scores.items())
    return {k: round(v, 3) for k, v in scores.items()}, round(total, 3)


def label_for(total):
    for label, threshold in LABEL_THRESHOLDS:
        if total >= threshold:
            return label
    return 'LOW'


def haversine_m(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(float, (lat1, lon1, lat2, lon2))
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
