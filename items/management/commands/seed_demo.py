"""
시연·정확도 측정용 시드 데이터 등록.

    python manage.py seed_demo            # seed/seed_items.csv + seed/photos 로 등록 후 매칭·정확도 출력
    python manage.py seed_demo --reset    # 이전에 넣은 시드 데이터(시드 계정 소유)를 지우고 다시 등록

DB에 직접 넣지 않고 등록 API와 같은 서비스 함수(사진 분석 → 설명문 → 임베딩 → 저장)를 그대로 거칩니다.
OpenAI 키가 필요하고, 사진 수만큼 AI 호출이 일어납니다.
"""

import csv
import re
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ai.images import InvalidImage
from items import services
from items.models import FeatureChat, FoundItem, ItemImage, LostItem
from matching.engine import LOST, run_matching
from places.models import Place

EMAIL_DOMAIN = 'jejari.ac.kr'
OWNER = ('demo.owner', '데모분실자')
FINDERS = [('demo.finder1', '데모습득자1'), ('demo.finder2', '데모습득자2'), ('demo.finder3', '데모습득자3')]

RELATIVE_TIME = re.compile(r'^-(\d+)\s+(\d{1,2}):(\d{2})$')  # "-2 14:00" = 2일 전 14:00


def parse_time(value):
    value = (value or '').strip()
    if not value:
        return None
    tz = timezone.get_current_timezone()
    m = RELATIVE_TIME.match(value)
    if m:
        day = timezone.localdate() - timedelta(days=int(m.group(1)))
        return timezone.make_aware(datetime.combine(day, time(int(m.group(2)), int(m.group(3)))), tz)
    try:
        return timezone.make_aware(datetime.strptime(value, '%Y-%m-%d %H:%M'), tz)
    except ValueError as exc:
        raise CommandError(f'시간 형식 오류: {value!r} ("-2 14:00" 또는 "2026-11-20 15:20")') from exc


def blank(value):
    value = (value or '').strip()
    return value or None


class Command(BaseCommand):
    help = '시드 CSV와 사진으로 분실물·습득물을 실제 등록 로직으로 넣고, 매칭 후 Top-1/Top-3 정확도를 출력'

    def add_arguments(self, parser):
        parser.add_argument('--csv', dest='csv_path', default='seed/seed_items.csv')
        parser.add_argument('--photos', dest='photo_dir', default='seed/photos')
        parser.add_argument('--reset', action='store_true', help='시드 계정이 가진 기존 데이터를 지우고 다시 등록')

    # ------------------------------------------------------------------
    def handle(self, *args, csv_path, photo_dir, reset, **options):
        csv_path, photo_dir = Path(csv_path), Path(photo_dir)
        if not csv_path.exists():
            raise CommandError(f'CSV가 없습니다: {csv_path}')
        with open(csv_path, encoding='utf-8-sig') as f:
            rows = [
                r for r in csv.DictReader(f)
                if not (r.get('pair_id') or '').upper().startswith('EX')  # 템플릿 예시 행 제외
            ]

        owner, finders = self._accounts()
        seed_users = [owner, *finders]
        if reset:
            self._reset(seed_users)
        elif LostItem.objects.filter(user__in=seed_users).exists() or FoundItem.objects.filter(
            finder__in=seed_users
        ).exists():
            raise CommandError('이미 시드 데이터가 있습니다. 다시 넣으려면 --reset 을 붙이세요.')

        places = {p.name: p for p in Place.objects.all()}
        found_by_pair, lost_items, skipped, found_count = {}, [], [], 0

        # 등록 중에는 백그라운드 매칭을 끄고, 전부 넣은 뒤 한 번에 실행
        with mock.patch.object(services, 'schedule_matching', lambda *a, **k: None):
            for i, row in enumerate(rows, start=2):  # CSV 2행부터 데이터
                label = f"{i}행 {row['row_type']} {row.get('photo_file') or row.get('item_name')}"
                try:
                    place = places[row['place'].strip()]
                except KeyError:
                    raise CommandError(f"{label}: 장소 '{row['place']}'가 없습니다. 있는 장소: {', '.join(places)}")

                user = owner if row['row_type'] == 'lost' else finders[i % len(finders)]
                try:
                    image, analysis = self._image(user, photo_dir, row.get('photo_file'))
                except (services.NoItemDetected, services.AnalysisUnavailable, InvalidImage) as exc:
                    skipped.append(f'{label}: 사진 분석 실패 ({type(exc).__name__})')
                    continue

                if row['row_type'] == 'found':
                    item = self._register_found(user, row, place, image, analysis)
                    found_count += 1
                    if blank(row.get('pair_id')):
                        found_by_pair[row['pair_id'].strip()] = item
                else:
                    item = self._register_lost(user, row, place, image)
                    lost_items.append((blank(row.get('pair_id')), item))
                self.stdout.write(f'  등록 {label} → #{item.id} {item.item_name}')

        self.stdout.write(self.style.SUCCESS(f'등록 완료: 습득물 {found_count}건, 분실물 {len(lost_items)}건'))
        for message in skipped:
            self.stdout.write(self.style.WARNING('  건너뜀 ' + message))

        self._match_and_report(lost_items, found_by_pair)
        self.stdout.write(f'\n시연 계정: {owner.email} (분실자), ' + ', '.join(f.email for f in finders) + ' (습득자)')

    # ------------------------------------------------------------------
    def _accounts(self):
        User = get_user_model()

        def get(prefix, nickname):
            email = f'{prefix}@{EMAIL_DOMAIN}'
            user = User.objects.filter(email=email).first()
            return user or User.objects.create_user(
                email=email, nickname=nickname, university_name='제자리대학교', is_verified=True
            )

        return get(*OWNER), [get(*f) for f in FINDERS]

    def _reset(self, users):
        counts = [
            LostItem.objects.filter(user__in=users).delete()[0],
            FoundItem.objects.filter(finder__in=users).delete()[0],
            FeatureChat.objects.filter(user__in=users).delete()[0],
            ItemImage.objects.filter(uploader__in=users).delete()[0],
        ]
        self.stdout.write(f'기존 시드 데이터 삭제: 연관 행 포함 {sum(counts)}건')

    def _image(self, user, photo_dir, photo_file):
        photo_file = blank(photo_file)
        if not photo_file:
            return None, None
        path = photo_dir / photo_file
        if not path.exists():
            raise CommandError(f'사진이 없습니다: {path}')
        with open(path, 'rb') as f:
            return services.create_analyzed_image(user, f)

    def _common(self, row, place, image, analysis):
        """CSV 값이 있으면 CSV, 비어 있으면 사진 분석값 (사용자 수정값이 AI 분석값보다 우선)."""
        ai = analysis.to_dict() if analysis else {}
        features = [f.strip() for f in (row.get('features') or '').split(';') if f.strip()]
        return {
            'image': image,
            'place': place,
            'location_detail': blank(row.get('location_detail')),
            'category': blank(row.get('category')) or ai.get('category') or '기타',
            'item_name': blank(row.get('item_name')) or ai.get('item_name') or '물건',
            'color': blank(row.get('color')) or ai.get('color'),
            'brand': blank(row.get('brand')) or ai.get('brand'),
            'features': features or ai.get('features') or [],
            'description': blank(row.get('description')),
        }

    def _register_found(self, user, row, place, image, analysis):
        if image is None:
            raise CommandError(f"습득물은 사진이 필요합니다: {row}")
        data = self._common(row, place, image, analysis)
        data.update({
            'found_at': parse_time(row['time_from']),
            'storage_status': blank(row.get('storage_status')) or FoundItem.StorageStatus.SELF,
            'storage_location': blank(row.get('storage_location')),
            'private_features': blank(row.get('private_features')),
        })
        return services.register_found_item(user, data)

    def _register_lost(self, user, row, place, image):
        data = self._common(row, place, image, None)  # 분실물은 주인이 쓴 글이 기준
        lost_from = parse_time(row['time_from'])
        data.update({
            'feature_chat': None,
            'lost_from': lost_from,
            'lost_to': parse_time(row.get('time_to')) or lost_from,
        })
        return services.register_lost_item(user, data)

    # ------------------------------------------------------------------
    def _match_and_report(self, lost_items, found_by_pair):
        self.stdout.write('\n매칭 실행 중...')
        for _, lost in lost_items:
            run_matching(LOST, lost.id)

        top1 = top3 = total = 0
        self.stdout.write('\n쌍  분실물                     정답 순위  후보 수  정답 라벨')
        for pair_id, lost in lost_items:
            answer = found_by_pair.get(pair_id) if pair_id else None
            if answer is None:
                continue
            total += 1
            ranked = list(lost.candidates.order_by('-total_score').values_list('found_item_id', 'similarity_label'))
            ids = [fid for fid, _ in ranked]
            rank = ids.index(answer.id) + 1 if answer.id in ids else None
            label = dict(ranked).get(answer.id, '-')
            top1 += rank == 1
            top3 += rank is not None and rank <= 3
            self.stdout.write(
                f"{pair_id:<3} {lost.item_name[:22]:<24} {rank or '없음':^8} {len(ids):^7} {label}"
            )

        if total:
            self.stdout.write(self.style.SUCCESS(
                f'\nTop-1 정확도 {top1}/{total} ({top1 / total:.0%}), Top-3 정확도 {top3}/{total} ({top3 / total:.0%})'
            ))
