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
- item_name은 "무선 이어폰 케이스", "반지갑"처럼 짧은 물건명으로 쓴다. 색상·브랜드는 넣지 않는다.
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
