# Jejari-BE

AI 기반 캠퍼스 분실물·습득물 자동 매칭 서비스 **제자리** 백엔드 (Line4Thon)

## 구조

```
Jejari-BE/
├── config/
│   ├── settings.py         # 단일 settings, .env로 개발·배포 구분
│   ├── urls.py             # admin, /schema/, /docs/(Swagger)
│   ├── wsgi.py
│   └── asgi.py
├── common/                 # BaseModel, 공통 응답·예외, pgvector 확장 마이그레이션
├── accounts/               # A: 학교 이메일 인증, User
├── places/                 # A: 건물(Place)
├── notifications/          # A: 알림
├── chats/                  # A: 채팅, 반환 완료
├── items/                  # B: 분실물·습득물, ItemImage, FeatureChat
├── ai/                     # B: LLM·임베딩·블러 (서비스 코드만)
├── matching/               # B: 매칭 후보, 소유권 확인
├── manage.py
├── requirements.txt
├── docker-compose.yml      # 로컬 PostgreSQL + pgvector
└── .env.example
```

## 로컬 실행

```bash
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env           # DJANGO_SECRET_KEY 채우기
docker compose up -d           # PostgreSQL + pgvector (localhost:5432)

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

- Swagger: http://localhost:8000/docs/
- 모든 모델은 `common.models.BaseModel`을 상속합니다.
- `VectorField`를 쓰는 앱의 첫 마이그레이션은 `('common', '0001_pgvector_extension')`에 의존해야 합니다.
