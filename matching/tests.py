import math
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from ai.services import AIError
from common.testing import make_found_item, make_lost_item, make_place, make_user
from matching import engine, scoring
from matching.models import MatchCandidate
from notifications.models import Notification


def vector(*weights):
    """앞쪽 차원에 weights를 넣고 단위 벡터로 정규화한 임베딩."""
    v = [0.0] * settings.EMBEDDING_DIMENSIONS
    for i, w in enumerate(weights):
        v[i] = float(w)
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def facts(**kwargs):
    base = dict(
        embedding_similarity=0.85, lost_category='지갑', found_category='지갑',
        lost_color='검정', found_color='검은색', lost_brand=None, found_brand=None,
        same_place=True, distance_m=0.0, gap_hours=0.0,
    )
    base.update(kwargs)
    return scoring.PairFacts(**base)


class ScoringTests(SimpleTestCase):
    def test_perfect_pair(self):
        scores, total = scoring.score(facts())
        self.assertEqual(scores, {'embedding': 1.0, 'tag': 1.0, 'place': 1.0, 'time': 1.0})
        self.assertEqual(total, 1.0)
        self.assertEqual(scoring.label_for(total), 'HIGH')

    def test_color_synonyms(self):
        self.assertTrue(scoring.color_match('네이비', '남색'))
        self.assertTrue(scoring.color_match('검정', '블랙'))
        self.assertFalse(scoring.color_match('남색', '빨간색'))

    def test_tag_score_only_compares_known_fields(self):
        # 색상 정보가 한쪽에 없으면 종류만 비교
        self.assertEqual(scoring.tag_score(facts(found_color=None)), 1.0)
        # 종류 일치, 색상 불일치, 브랜드 일치 → 2/3
        self.assertAlmostEqual(
            scoring.tag_score(facts(found_color='빨강', lost_brand='Apple', found_brand='apple')), 2 / 3
        )
        self.assertTrue(scoring.category_match('지갑', '카드지갑'))

    def test_place_and_time_decay(self):
        self.assertEqual(scoring.place_score(facts(same_place=False, distance_m=400)), 0.5)
        self.assertEqual(scoring.place_score(facts(same_place=False, distance_m=2000)), 0.0)
        self.assertEqual(scoring.time_score(facts(gap_hours=36)), 0.5)
        self.assertEqual(scoring.time_score(facts(gap_hours=100)), 0.0)

    def test_embedding_rescale(self):
        self.assertEqual(scoring.embedding_score(0.2), 0.0)
        self.assertEqual(scoring.embedding_score(0.9), 1.0)
        self.assertAlmostEqual(scoring.embedding_score(0.55), 0.5)

    def test_haversine(self):
        # 위도 0.001도 ≈ 111m
        self.assertAlmostEqual(scoring.haversine_m(37.5, 127.0, 37.501, 127.0), 111.2, delta=1)


@mock.patch('matching.reasons.write_match_reasons', side_effect=AIError('off'))
class EngineTests(APITestCase):
    def setUp(self):
        now = timezone.now()
        self.owner = make_user()
        self.finder = make_user()
        self.library = make_place(name='중앙도서관', latitude='37.5000000', longitude='127.0000000')
        self.far = make_place(name='체육관', latitude='37.5200000', longitude='127.0000000')

        self.lost = make_lost_item(
            self.owner, place=self.library, category='지갑', item_name='검은색 가죽 반지갑',
            color='검정', lost_from=now - timedelta(hours=5), lost_to=now - timedelta(hours=3),
            text_embedding=vector(1),
        )
        common = dict(place=self.library, category='지갑', color='검은색', found_at=now - timedelta(hours=2))
        self.match = make_found_item(self.finder, item_name='검정 반지갑', text_embedding=vector(1), **common)
        self.unrelated = make_found_item(
            self.finder, place=self.far, category='우산', item_name='파란 우산', color='파랑',
            found_at=now - timedelta(hours=2), text_embedding=vector(0, 1),
        )
        self.completed = make_found_item(self.finder, status='COMPLETED', text_embedding=vector(1), **common)
        self.too_early = make_found_item(
            self.finder, place=self.library, category='지갑', found_at=now - timedelta(hours=10),
            text_embedding=vector(1),
        )
        self.own = make_found_item(self.owner, text_embedding=vector(1), **common)

    def test_lost_registration_creates_only_valid_candidate(self, _ai):
        created = engine.run_matching(engine.LOST, self.lost.id)

        self.assertEqual([r.found.id for r in created], [self.match.id])
        candidate = MatchCandidate.objects.get()
        self.assertEqual(candidate.similarity_label, 'HIGH')
        self.assertAlmostEqual(candidate.total_score, 1.0, delta=0.01)
        self.assertEqual([r['field'] for r in candidate.match_reasons],
                         ['category', 'color', 'appearance', 'place', 'time'])
        self.assertTrue(all(r['is_match'] for r in candidate.match_reasons))

        self.lost.refresh_from_db()
        self.match.refresh_from_db()
        self.assertEqual(self.lost.status, 'CANDIDATE_FOUND')
        self.assertEqual(self.match.status, 'CANDIDATE_FOUND')

        notification = Notification.objects.get()
        self.assertEqual(notification.user, self.owner)
        self.assertEqual(notification.type, 'MATCH_CANDIDATE')
        self.assertEqual((notification.target_type, notification.target_id), ('CANDIDATE', candidate.id))

    def test_rerun_does_not_duplicate_or_revive_excluded(self, _ai):
        engine.run_matching(engine.LOST, self.lost.id)
        MatchCandidate.objects.update(status=MatchCandidate.Status.EXCLUDED)
        self.assertEqual(engine.run_matching(engine.LOST, self.lost.id), [])
        self.assertEqual(MatchCandidate.objects.count(), 1)
        self.assertEqual(MatchCandidate.objects.get().status, 'EXCLUDED')

    def test_found_registration_matches_existing_lost_items(self, _ai):
        created = engine.run_matching(engine.FOUND, self.match.id)
        self.assertEqual([r.lost.id for r in created], [self.lost.id])
        self.assertEqual(engine.run_matching(engine.FOUND, self.unrelated.id), [])

    def test_ai_reasons_replace_text_but_keep_match_flags(self, ai):
        ai.side_effect = None
        ai.return_value = [{'field': 'appearance', 'text': '두 지갑 모두 검은색 가죽입니다.'}]
        engine.run_matching(engine.LOST, self.lost.id)

        reasons = {r['field']: r for r in MatchCandidate.objects.get().match_reasons}
        self.assertEqual(reasons['appearance']['text'], '두 지갑 모두 검은색 가죽입니다.')
        self.assertTrue(reasons['appearance']['is_match'])
        self.assertIn('중앙도서관', reasons['place']['text'])  # AI가 안 준 항목은 규칙 문장 유지

        payload = ai.call_args.args[0]
        self.assertNotIn('private_features', payload['found_item'])

    def test_low_score_pair_is_not_saved(self, _ai):
        self.match.text_embedding = vector(1, 3)  # 유사도 약 0.32
        self.match.place = self.far
        self.match.save()
        self.assertEqual(engine.run_matching(engine.LOST, self.lost.id), [])

    def test_schedule_matching_runs_after_commit_in_thread(self, _ai):
        with mock.patch('matching.engine.threading.Thread') as thread:
            with self.captureOnCommitCallbacks(execute=True):
                engine.schedule_matching(engine.LOST, self.lost.id)
        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs['args'], (engine.LOST, self.lost.id))
        thread.return_value.start.assert_called_once()


@mock.patch('matching.reasons.write_match_reasons', side_effect=AIError('off'))
class DevMatchingAPITests(APITestCase):
    def setUp(self):
        now = timezone.now()
        place = make_place()
        self.lost = make_lost_item(
            make_user(), place=place, category='지갑', color='검정',
            lost_from=now - timedelta(hours=2), lost_to=now - timedelta(hours=1), text_embedding=vector(1),
        )
        make_found_item(
            make_user(), place=place, category='지갑', color='검정',
            found_at=now - timedelta(minutes=30), text_embedding=vector(1),
        )
        self.admin = make_user(is_staff=True)
        self.url = f'/dev/matching/{self.lost.id}'

    @override_settings(DEBUG=True)
    def test_admin_runs_matching_with_scores(self, _ai):
        self.client.force_authenticate(self.admin)
        res = self.client.post(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['candidates_created'], 1)
        candidate = res.data['candidates'][0]
        self.assertEqual(set(candidate['scores']), {'embedding', 'tag', 'place', 'time'})
        self.assertEqual(candidate['similarity_label'], '높은 유사도')

    @override_settings(DEBUG=True)
    def test_non_admin_forbidden(self, _ai):
        self.client.force_authenticate(make_user())
        self.assertEqual(self.client.post(self.url).status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(DEBUG=False)
    def test_disabled_when_not_debug(self, _ai):
        self.client.force_authenticate(self.admin)
        res = self.client.post(self.url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.data['detail'], '분실물을 찾을 수 없습니다.')
