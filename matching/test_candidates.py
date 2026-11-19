from rest_framework import status
from rest_framework.test import APITestCase

from common.testing import make_candidate, make_found_item, make_image, make_lost_item, make_place, make_user
from matching.models import MatchCandidate, OwnershipCheck

REASONS = [
    {'field': 'category', 'is_match': True, 'text': '두 물건 모두 지갑 종류입니다.'},
    {'field': 'place', 'is_match': True, 'text': '분실 장소와 습득 장소가 모두 중앙도서관입니다.'},
]


class CandidateAPITestBase(APITestCase):
    def setUp(self):
        self.owner = make_user()
        self.finder = make_user()
        self.stranger = make_user()
        self.client.force_authenticate(self.owner)

        self.place = make_place(name='중앙도서관')
        self.lost = make_lost_item(self.owner, status='CANDIDATE_FOUND')
        self.found_high = make_found_item(
            self.finder, place=self.place,
            image=make_image(self.finder, image_url='/media/items/high.jpg'),
            category='카드지갑', item_name='남색 가죽 카드지갑', color='남색',
            features=['학생증 포함', '가죽 재질'], private_features='안쪽 포켓에 고양이 스티커',
            status='CANDIDATE_FOUND',
        )
        self.found_low = make_found_item(self.finder, item_name='검정 지갑', status='CANDIDATE_FOUND')
        self.found_excluded = make_found_item(self.finder, item_name='제외된 지갑')

        self.high = make_candidate(
            self.lost, self.found_high, total_score=0.82,
            similarity_label='HIGH', match_reasons=REASONS,
        )
        self.low = make_candidate(self.lost, self.found_low, total_score=0.55, similarity_label='LOW')
        self.excluded = make_candidate(
            self.lost, self.found_excluded, total_score=0.9, status=MatchCandidate.Status.EXCLUDED
        )


class CandidateListTests(CandidateAPITestBase):
    def url(self, item_id):
        return f'/items/lost/{item_id}/candidates'

    def test_list_sorted_without_excluded_or_scores(self):
        res = self.client.get(self.url(self.lost.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['lost_item_id'], self.lost.id)
        self.assertEqual(res.data['status'], 'CANDIDATE_FOUND')
        self.assertEqual([c['candidate_id'] for c in res.data['candidates']], [self.high.id, self.low.id])
        self.assertNotIn('message', res.data)

        first = res.data['candidates'][0]
        self.assertEqual(first['similarity_label'], '높은 유사도')
        self.assertEqual(first['status'], 'CANDIDATE')
        self.assertEqual(first['found_item'], {
            'found_item_id': self.found_high.id,
            'image_url': 'http://testserver/media/items/high.jpg',
            'category': '카드지갑',
            'item_name': '남색 가죽 카드지갑',
            'color': '남색',
            'place_name': '중앙도서관',
            'found_at': first['found_item']['found_at'],
        })
        self.assertNotIn('total_score', first)

    def test_empty_list_has_message(self):
        lost = make_lost_item(self.owner)
        res = self.client.get(self.url(lost.id))
        self.assertEqual(res.data['candidates'], [])
        self.assertEqual(res.data['status'], 'WAITING')
        self.assertEqual(res.data['message'], '비슷한 물건이 등록되면 알려드릴게요.')

    def test_permissions(self):
        self.client.force_authenticate(self.stranger)
        self.assertEqual(self.client.get(self.url(self.lost.id)).status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.get(self.url(999999))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.data['detail'], '분실물을 찾을 수 없습니다.')


class CandidateDetailTests(CandidateAPITestBase):
    def test_detail_with_reasons_and_no_private_features(self):
        res = self.client.get(f'/candidates/{self.high.id}')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['candidate_id'], self.high.id)
        self.assertEqual(res.data['similarity_label'], '높은 유사도')
        self.assertEqual(list(res.data['found_item']), [
            'found_item_id', 'image_url', 'category', 'item_name', 'color', 'brand',
            'features', 'place_name', 'found_at',
        ])
        self.assertEqual(res.data['found_item']['features'], ['학생증 포함', '가죽 재질'])
        self.assertEqual(res.data['reasons'], REASONS)
        self.assertNotIn('고양이', str(res.data))
        self.assertNotIn('total_score', res.data)

    def test_permissions(self):
        # 습득자도 분실물 쪽 후보 상세는 볼 수 없음
        for user in (self.stranger, self.finder):
            self.client.force_authenticate(user)
            self.assertEqual(
                self.client.get(f'/candidates/{self.high.id}').status_code, status.HTTP_403_FORBIDDEN
            )
        res = self.client.get('/candidates/999999')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.data['detail'], '매칭 후보를 찾을 수 없습니다.')


class CandidateRejectTests(CandidateAPITestBase):
    def reject(self, candidate):
        return self.client.post(f'/candidates/{candidate.id}/reject')

    def test_reject(self):
        res = self.reject(self.low)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data, {
            'candidate_id': self.low.id, 'status': 'EXCLUDED', 'message': '후보에서 제외했어요.',
        })
        self.low.refresh_from_db()
        self.assertEqual(self.low.status, 'EXCLUDED')

        # 목록에서 빠짐, 다른 후보가 남아 있어 분실물은 CANDIDATE_FOUND 유지
        ids = [c['candidate_id'] for c in self.client.get(f'/items/lost/{self.lost.id}/candidates').data['candidates']]
        self.assertEqual(ids, [self.high.id])
        self.lost.refresh_from_db()
        self.assertEqual(self.lost.status, 'CANDIDATE_FOUND')
        # 습득물은 진행 중인 후보가 없어져 WAITING으로 돌아감
        self.found_low.refresh_from_db()
        self.assertEqual(self.found_low.status, 'WAITING')

    def test_rejecting_last_candidate_returns_lost_item_to_waiting(self):
        self.reject(self.low)
        self.reject(self.high)
        self.lost.refresh_from_db()
        self.assertEqual(self.lost.status, 'WAITING')

    def test_reject_twice_is_ok(self):
        self.reject(self.low)
        res = self.reject(self.low)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['status'], 'EXCLUDED')

    def test_conflict_after_ownership_check_started(self):
        verifying = make_candidate(
            make_lost_item(self.owner), make_found_item(self.finder),
            status=MatchCandidate.Status.VERIFYING,
        )
        res = self.reject(verifying)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['detail'], '이미 소유권 확인이 진행된 후보는 제외할 수 없습니다.')

        # 상태는 CANDIDATE여도 확인 기록이 있으면 제외 불가
        OwnershipCheck.objects.create(candidate=self.high, questions=['q'])
        self.assertEqual(self.reject(self.high).status_code, status.HTTP_409_CONFLICT)
        self.high.refresh_from_db()
        self.assertEqual(self.high.status, 'CANDIDATE')

    def test_permissions(self):
        self.client.force_authenticate(self.stranger)
        self.assertEqual(self.reject(self.low).status_code, status.HTTP_403_FORBIDDEN)
        self.low.refresh_from_db()
        self.assertEqual(self.low.status, 'CANDIDATE')
        self.assertEqual(self.client.post('/candidates/999999/reject').status_code, status.HTTP_404_NOT_FOUND)
