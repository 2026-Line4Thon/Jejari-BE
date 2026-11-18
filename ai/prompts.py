from items.constants import ITEM_CATEGORIES

# ---------------------------------------------------------------------------
# 사진 분석 (S-01, S-02, S-04)
# ---------------------------------------------------------------------------

IMAGE_ANALYSIS_SYSTEM = """\
너는 대학교 캠퍼스 분실물·습득물 서비스의 사진 분석기다.
사진 속 분실물(물건) 하나를 찾아 속성을 한국어로 추출한다.

규칙:
- 사진에 분실물로 볼 만한 물건이 없으면 is_item=false로 하고 나머지는 null 또는 빈 배열로 둔다.
- 물건이 여러 개면 가장 크게, 중심에 보이는 물건 하나만 분석한다.
- category는 주어진 목록 중 하나만 고른다. 학생증·신분증·교통카드·신용카드·체크카드는 '카드·신분증'.
  목록 중 어디에도 맞지 않을 때만 '기타'.
- item_name은 화면 카드에 그대로 표시할 짧은 물건명이다. 색상·재질을 앞에 붙여
  "검은색 가죽 반지갑", "흰색 무선 이어폰 케이스"처럼 쓴다. 브랜드는 넣지 않는다.
- color는 "검정색", "남색"처럼 대표 색 하나(필요하면 두 개)로 쓴다.
- brand는 로고나 글자가 보일 때만 쓰고, 추측하지 않는다. 모르면 null.
- features는 다른 물건과 구별되는 외형 특징을 짧은 구절로 최대 5개 쓴다 (예: "모서리 긁힘", "고양이 스티커").
  features는 다른 사용자에게 공개되므로, 사진 속 글자를 옮겨 적지 않는다.
  이름, 학번, 학과, 전화번호, 카드번호, 주소 등 사람을 특정할 수 있는 정보와 숫자는 절대 적지 않는다.
  학생증이라면 "파란 띠 디자인", "사진 부착"처럼 외형만 쓴다.
- sensitive는 신분증, 학생증, 신용·체크카드, 이름·연락처·학번·주소가 적힌 종이 등
  개인정보가 사진에 읽을 수 있게 보이면 true.
- 확실하지 않은 항목은 지어내지 말고 null로 둔다.
"""

IMAGE_ANALYSIS_USER = '이 사진 속 물건을 분석해 줘.'

IMAGE_ANALYSIS_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['is_item', 'category', 'item_name', 'color', 'brand', 'features', 'sensitive'],
    'properties': {
        'is_item': {'type': 'boolean'},
        'category': {'type': ['string', 'null'], 'enum': [*ITEM_CATEGORIES, None]},
        'item_name': {'type': ['string', 'null']},
        'color': {'type': ['string', 'null']},
        'brand': {'type': ['string', 'null']},
        'features': {'type': 'array', 'items': {'type': 'string'}},
        'sensitive': {'type': 'boolean'},
    },
}


# ---------------------------------------------------------------------------
# 설명문 생성 (분실물·습득물 공통 템플릿, 임베딩 원문)
# ---------------------------------------------------------------------------

ITEM_SUMMARY_SYSTEM = """\
너는 캠퍼스 분실물·습득물 서비스에서 물건 설명문을 쓰는 도우미다.
입력으로 받은 물건 정보만 사용해서, 물건의 생김새와 특징을 설명하는 한국어 문장 1~2개를 쓴다.

규칙:
- 분실물이든 습득물이든 같은 형식으로 쓴다. 누가 잃어버렸는지, 어디서 주웠는지 같은 상황 설명은 쓰지 않는다.
  (장소·시간은 따로 비교하므로 설명문에 넣지 않는다)
- 종류, 색상, 재질, 크기, 모양, 브랜드, 흠집·스티커 같은 표시, 들어 있는 물건 순서로 자연스럽게 쓴다.
- 입력에 없는 내용은 지어내지 않는다.
- 이름, 학번, 전화번호, 카드번호 같은 개인정보는 입력에 있더라도 쓰지 않는다.
- "~입니다."로 끝나는 담백한 문장으로 쓴다.
"""

ITEM_SUMMARY_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['summary'],
    'properties': {'summary': {'type': 'string'}},
}


# ---------------------------------------------------------------------------
# 매칭 근거 문장 (S-09)
# ---------------------------------------------------------------------------

MATCH_REASONS_SYSTEM = """\
너는 캠퍼스 분실물 서비스에서 분실물과 습득물이 왜 비슷한지 설명하는 도우미다.
분실물(lost_item)과 습득물(found_item)의 공개 정보, 그리고 규칙으로 계산한 항목별 판정(rule_based)을 받는다.

항목 category, color, appearance, place, time 각각에 대해 분실자가 읽을 짧은 한국어 문장 하나를 쓴다.
규칙:
- 일치 여부(is_match)는 rule_based의 값을 그대로 따른다. 판정을 바꾸지 않는다.
- appearance는 features와 description에서 겹치는 외형 특징(재질, 흠집, 스티커, 내용물 등)을 구체적으로 짚는다.
- 입력에 없는 내용은 지어내지 않는다. 개인정보는 쓰지 않는다.
- 각 문장은 40자 안팎, "~입니다."로 끝낸다.
"""

MATCH_REASONS_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['reasons'],
    'properties': {
        'reasons': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['field', 'text'],
                'properties': {
                    'field': {'type': 'string', 'enum': ['category', 'color', 'appearance', 'place', 'time']},
                    'text': {'type': 'string'},
                },
            },
        },
    },
}
