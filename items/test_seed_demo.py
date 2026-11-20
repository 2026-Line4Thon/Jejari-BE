import csv
import io
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import override_settings
from django.utils import timezone
from django.utils.functional import empty
from PIL import Image
from rest_framework.test import APITestCase

from ai.services import AIError, ImageAnalysis
from common.storage import private_storage
from common.testing import make_place, zero_vector
from items.management.commands.seed_demo import parse_time
from items.models import FoundItem, LostItem

HEADER = ['row_type', 'pair_id', 'photo_file', 'category', 'item_name', 'color', 'description',
          'place', 'location_detail', 'time_from', 'time_to', 'storage_status', 'private_features']


class ParseTimeTests(APITestCase):
    def test_relative_and_absolute(self):
        two_days_ago = parse_time('-2 14:05')
        self.assertEqual(timezone.localtime(two_days_ago).date(), timezone.localdate() - timezone.timedelta(days=2))
        self.assertEqual((two_days_ago.hour, two_days_ago.minute), (14, 5))
        self.assertEqual(parse_time('2026-11-20 15:20').minute, 20)
        self.assertIsNone(parse_time(''))
        with self.assertRaises(CommandError):
            parse_time('어제 오후')


class SeedDemoCommandTests(APITestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.settings_override = override_settings(
            MEDIA_ROOT=str(self.tmp / 'media'), PRIVATE_MEDIA_ROOT=str(self.tmp / 'private')
        )
        self.settings_override.enable()
        private_storage._wrapped = empty
        (self.tmp / 'photos').mkdir()
        Image.new('RGB', (100, 80), 'black').save(self.tmp / 'photos' / 'wallet.png')
        make_place(name='중앙도서관')

        rows = [
            ['found', '1', 'wallet.png', '', '', '', '', '중앙도서관', '3층', '-1 14:00', '', '', '고양이 스티커'],
            ['lost', '1', '', '지갑', '검은색 반지갑', '검정', '학생증이 있어요', '중앙도서관', '', '-1 12:00', '-1 14:00', '', ''],
            ['found', 'EX1', 'wallet.png', '', '', '', '', '중앙도서관', '', '-1 10:00', '', '', ''],
        ]
        self.csv_path = self.tmp / 'seed.csv'
        with open(self.csv_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(HEADER)
            writer.writerows(rows)

        analysis = ImageAnalysis(is_item=True, category='지갑', item_name='검은색 가죽 반지갑', color='검정')
        patches = [
            mock.patch('items.services.analyze_item_image', return_value=analysis),
            mock.patch('items.services.summarize_item', return_value='검은색 가죽 반지갑입니다.'),
            mock.patch('items.services.embed_text', return_value=[1.0] + zero_vector()[1:]),
            mock.patch('matching.reasons.write_match_reasons', side_effect=AIError('off')),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.settings_override.disable()
        private_storage._wrapped = empty
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_seed(self, *extra):
        out = io.StringIO()
        call_command('seed_demo', '--csv', str(self.csv_path), '--photos', str(self.tmp / 'photos'),
                     *extra, stdout=out)
        return out.getvalue()

    def test_registers_matches_and_reports_accuracy(self):
        output = self.run_seed()

        found = FoundItem.objects.get()  # EX 예시 행은 건너뜀
        self.assertEqual(found.item_name, '검은색 가죽 반지갑')  # CSV가 비어 있으면 사진 분석값
        self.assertEqual(found.private_features, '고양이 스티커')
        self.assertEqual(found.storage_status, 'SELF')
        lost = LostItem.objects.get()
        self.assertEqual(lost.user.email, 'demo.owner@jejari.ac.kr')
        self.assertEqual(lost.candidates.get().found_item, found)
        self.assertIn('Top-1 정확도 1/1 (100%)', output)

    def test_rerun_requires_reset(self):
        self.run_seed()
        with self.assertRaises(CommandError):
            self.run_seed()
        self.run_seed('--reset')
        self.assertEqual(FoundItem.objects.count(), 1)
        self.assertEqual(LostItem.objects.count(), 1)

    def test_unknown_place_fails_clearly(self):
        with open(self.csv_path, 'a', encoding='utf-8', newline='') as f:
            csv.writer(f).writerow(['found', '', 'wallet.png', '', '', '', '', '없는건물', '', '-1 10:00', '', '', ''])
        with self.assertRaisesMessage(CommandError, '없는건물'):
            self.run_seed()
