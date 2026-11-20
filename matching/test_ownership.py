from unittest import mock

from rest_framework import status
from rest_framework.test import APITestCase

from ai.services import AIError
from chats.models import ChatRoom
from common.testing import make_candidate, make_found_item, make_image, make_lost_item, make_user
from matching.models import MatchCandidate, OwnershipCheck
from notifications.models import Notification

QUESTIONS = [
    {'text': '지갑 안쪽에 붙어 있던 스티커는 어떤 그림이었나요?', 'expected': '고양이'},
    {'text': '지갑 안에 들어 있던 카드는 무엇이었나요?', 'expected': '학생증'},
]
FOLLOW_UP = {'text': '지갑 바깥쪽 흠집은 어디에 있었나요?', 'expected': '오른쪽 아래 모서리'}


class OwnershipTestBase(APITestCase):
    def setUp(self):
        self.owner = make_user()
        self.finder = make_user()
        self.client.force_authenticate(self.owner)
        self.lost = make_lost_item(self.owner, status='CANDIDATE_FOUND')
        self.found = make_found_item(
            self.finder, status='CANDIDATE_FOUND',
            image=make_image(self.finder, ai_tags={'features': ['가죽 재질', '모서리 해짐']}),
            features=['가죽 재질'], private_features='안쪽에 고양이 스티커, 학생증 들어 있음',
        )
        self.candidate = make_candidate(self.lost, self.found)

        patches = {
            'questions': mock.patch('matching.ownership.generate_ownership_questions', return_value=QUESTIONS),
            'judge': mock.patch('matching.ownership.judge_ownership', return_value=('MATCHED', None)),
        }
        self.ai = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    def start(self, candidate=None):
        return self.client.post(f'/candidates/{(candidate or self.candidate).id}/ownership-checks')

    def answer(self, check_id, answers):
        return self.client.post(f'/ownership-checks/{check_id}/answers', {'answers': answers}, format='json')

    def answer_both(self, check_id):
        return self.answer(check_id, [
            {'question_id': 1, 'answer': '고양이 스티커요'},
            {'question_id': 2, 'answer': '학생증'},
        ])

    def refresh(self):
        for obj in (self.candidate, self.lost, self.found):
            obj.refresh_from_db()


class StartCheckTests(OwnershipTestBase):
    def test_creates_questions_without_answers(self):
        res = self.start()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['candidate_id'], self.candidate.id)
        self.assertEqual((res.data['attempt_no'], res.data['remaining_attempts']), (1, 2))
        self.assertEqual(res.data['questions'], [
            {'question_id': 1, 'text': QUESTIONS[0]['text']},
            {'question_id': 2, 'text': QUESTIONS[1]['text']},
        ])
        self.assertNotIn('고양이', str(res.data))  # 기대 답변은 응답에 없음

        check = OwnershipCheck.objects.get(id=res.data['check_id'])
        self.assertEqual(check.questions[0]['expected'], '고양이')
        self.refresh()
        self.assertEqual(self.candidate.status, 'VERIFYING')
        self.assertEqual((self.lost.status, self.found.status), ('VERIFYING', 'VERIFYING'))

        secret, public = self.ai['questions'].call_args.args
        self.assertEqual(secret['private_features'], '안쪽에 고양이 스티커, 학생증 들어 있음')
        self.assertNotIn('hidden_ai_tags', secret)  # 비공개 특징이 있으면 AI 태그는 쓰지 않음
        self.assertNotIn('private_features', public)

    def test_ai_tags_used_only_without_private_features(self):
        self.found.private_features = ''
        self.found.save()
        self.start()
        secret, _ = self.ai['questions'].call_args.args
        self.assertEqual(secret, {'hidden_ai_tags': ['모서리 해짐']})  # 공개 features에 없는 AI 태그만

    def test_single_question_when_one_fact(self):
        self.ai['questions'].return_value = QUESTIONS[:1]
        res = self.start()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(res.data['questions']), 1)
        res = self.answer(res.data['check_id'], [{'question_id': 1, 'answer': '고양이요'}])
        self.assertEqual(res.data['result'], 'MATCHED')

    def test_reuses_open_check(self):
        first = self.start()
        second = self.start()
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data['check_id'], first.data['check_id'])
        self.assertEqual(self.ai['questions'].call_count, 1)
        self.assertEqual(OwnershipCheck.objects.count(), 1)

    def test_conflicts(self):
        for state in ('EXCLUDED', 'MATCHED'):
            MatchCandidate.objects.filter(id=self.candidate.id).update(status=state)
            res = self.start()
            self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, state)
            self.assertEqual(res.data['detail'], '소유권 확인을 진행할 수 없는 후보입니다.')

        MatchCandidate.objects.filter(id=self.candidate.id).update(status='LOCKED')
        res = self.start()
        self.assertEqual(res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(res.data['detail'], '소유권 확인 시도 횟수를 초과했습니다.')

    def test_ai_failure_does_not_use_an_attempt(self):
        self.ai['questions'].side_effect = AIError('timeout')
        res = self.start()
        self.assertEqual(res.status_code, status.HTTP_504_GATEWAY_TIMEOUT)
        self.assertFalse(OwnershipCheck.objects.exists())
        self.refresh()
        self.assertEqual(self.candidate.status, 'CANDIDATE')

    def test_permissions(self):
        self.client.force_authenticate(self.finder)
        self.assertEqual(self.start().status_code, status.HTTP_403_FORBIDDEN)
        res = self.client.post('/candidates/999999/ownership-checks')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


class SubmitAnswersTests(OwnershipTestBase):
    def setUp(self):
        super().setUp()
        self.check_id = self.start().data['check_id']

    def test_matched_creates_chat_room(self):
        res = self.answer_both(self.check_id)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['result'], 'MATCHED')
        self.assertEqual(res.data['message'], '소유권이 확인되었어요. 습득자와 채팅을 시작할 수 있어요.')
        room = ChatRoom.objects.get(candidate=self.candidate)
        self.assertEqual(res.data['chat_room_id'], room.id)
        self.assertEqual((room.owner, room.finder), (self.owner, self.finder))

        self.refresh()
        self.assertEqual(self.candidate.status, 'MATCHED')
        self.assertEqual((self.lost.status, self.found.status), ('CHATTING', 'CHATTING'))
        self.assertEqual(Notification.objects.filter(type='CHAT_STARTED').count(), 2)

        # 판정에 기대 답변과 분실자 답변이 함께 전달됨
        qa, secret, public, allow_follow_up = self.ai['judge'].call_args.args
        self.assertNotIn('private_features', public)
        self.assertEqual(qa[0], {'question': QUESTIONS[0]['text'], 'expected': '고양이', 'answer': '고양이 스티커요'})
        self.assertTrue(allow_follow_up)

        detail = self.client.get(f'/ownership-checks/{self.check_id}')
        self.assertEqual(detail.data['result'], 'MATCHED')
        self.assertEqual(detail.data['chat_room_id'], room.id)
        self.assertEqual((detail.data['attempt_no'], detail.data['remaining_attempts']), (1, 2))
        self.assertNotIn('고양이', str(detail.data))

        # 판정이 끝난 건은 다시 제출 불가
        res = self.answer_both(self.check_id)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['detail'], '이미 판정이 완료된 소유권 확인입니다.')

    def test_need_more_then_mismatch(self):
        self.ai['judge'].return_value = ('NEED_MORE', FOLLOW_UP)
        res = self.answer_both(self.check_id)
        self.assertEqual(res.data['result'], 'NEED_MORE')
        self.assertEqual(res.data['message'], '조금 더 확인이 필요해요.')
        self.assertEqual(res.data['questions'], [{'question_id': 3, 'text': FOLLOW_UP['text']}])
        self.assertNotIn('chat_room_id', res.data)

        # 추가 질문에만 답하면 됨, 이번에는 추가 질문 없이 최종 판정
        self.ai['judge'].return_value = ('MISMATCH', None)
        res = self.answer(self.check_id, [{'question_id': 3, 'answer': '모르겠어요'}])
        self.assertEqual(res.data['result'], 'MISMATCH')
        self.assertEqual(res.data['remaining_attempts'], 1)
        qa, _, _, allow_follow_up = self.ai['judge'].call_args.args
        self.assertEqual(len(qa), 3)
        self.assertFalse(allow_follow_up)

        self.refresh()
        self.assertEqual(self.candidate.status, 'MISMATCHED')
        self.assertEqual((self.lost.status, self.found.status), ('CANDIDATE_FOUND', 'CANDIDATE_FOUND'))

    def test_two_mismatches_lock_candidate(self):
        self.ai['judge'].return_value = ('MISMATCH', None)
        self.answer_both(self.check_id)

        retry = self.start()
        self.assertEqual(retry.status_code, status.HTTP_201_CREATED)
        self.assertEqual((retry.data['attempt_no'], retry.data['remaining_attempts']), (2, 1))

        res = self.answer_both(retry.data['check_id'])
        self.assertEqual(res.data['remaining_attempts'], 0)
        self.refresh()
        self.assertEqual(self.candidate.status, 'LOCKED')
        self.assertEqual(self.start().status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        # 잠긴 후보만 있던 분실물은 매칭 대기로 돌아감
        self.assertEqual(self.lost.status, 'WAITING')

    def test_validation(self):
        res = self.client.post(f'/ownership-checks/{self.check_id}/answers', {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('answers', res.data)

        for answers in (
            [{'question_id': 1, 'answer': '고양이'}],
            [{'question_id': 1, 'answer': '고양이'}, {'question_id': 2, 'answer': '  '}],
        ):
            res = self.answer(self.check_id, answers)
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(res.data['detail'], '모든 질문에 답변해 주세요.')
        self.ai['judge'].assert_not_called()

    def test_judge_failure_keeps_check_open(self):
        self.ai['judge'].side_effect = AIError('timeout')
        self.assertEqual(self.answer_both(self.check_id).status_code, status.HTTP_504_GATEWAY_TIMEOUT)
        check = OwnershipCheck.objects.get(id=self.check_id)
        self.assertEqual((check.result, check.answers), ('PENDING', None))

        self.ai['judge'].side_effect = None
        self.assertEqual(self.answer_both(self.check_id).data['result'], 'MATCHED')

    def test_permissions(self):
        self.client.force_authenticate(self.finder)
        self.assertEqual(self.answer_both(self.check_id).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.get(f'/ownership-checks/{self.check_id}').status_code, status.HTTP_403_FORBIDDEN
        )
        res = self.client.get('/ownership-checks/999999')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.data['detail'], '소유권 확인 내역을 찾을 수 없습니다.')


class JudgeOwnershipServiceTests(APITestCase):
    """ai.services.judge_ownership의 후처리 (추가 질문을 더 할 수 없으면 불일치)."""

    def test_need_more_without_follow_up_becomes_mismatch(self):
        from ai import client
        from ai.services import judge_ownership

        raw = {'result': 'NEED_MORE', 'follow_up': FOLLOW_UP}
        with mock.patch.object(client, 'chat_json', return_value=raw):
            self.assertEqual(judge_ownership([], {}, {}, allow_follow_up=True), ('NEED_MORE', FOLLOW_UP))
            self.assertEqual(judge_ownership([], {}, {}, allow_follow_up=False), ('MISMATCH', None))
        with mock.patch.object(client, 'chat_json', return_value={'result': 'NEED_MORE', 'follow_up': None}):
            self.assertEqual(judge_ownership([], {}, {}, allow_follow_up=True), ('MISMATCH', None))
