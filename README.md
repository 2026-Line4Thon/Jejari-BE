# Jejari-BE

repo/
├── config/                 # 프로젝트 설정
│   ├── settings/
│   │   ├── base.py         # 공통 설정
│   │   ├── dev.py          # 로컬 개발용
│   │   └── prod.py         # 배포용 (A가 이어서 작업)
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── apps/
│   ├── common/             # BaseModel, 공통 응답·예외
│   ├── accounts/           # A: 인증, User
│   ├── places/             # A: 건물 목록
│   ├── notifications/      # A: 알림
│   ├── chats/              # A: 채팅, 반환
│   ├── items/              # B: 분실물·습득물, ItemImage
│   ├── ai/                 # B: LLM·임베딩·블러 (모델 없이 서비스 코드만)
│   └── matching/           # B: 매칭 후보, 소유권 확인
├── manage.py
├── requirements.txt
├── docker-compose.yml      # 로컬 PostgreSQL + pgvector
├── .env.example
└── .gitignore
