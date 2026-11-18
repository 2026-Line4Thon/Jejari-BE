from unittest import mock

from rest_framework import status
from rest_framework.test import APITestCase

from ai.services import AIError
from common.testing import make_image, make_user
from items.models import FeatureChat, FeatureChatTurn

URL = '/items/lost/feature-chats'
KNOWN = {'category': '지갑', 'color': '검정', 'size': None, 'material': None,
         'shape': None, 'marks': None, 'brand': None}


def ai_question(step, known):
    return {'text': f'{known.get("category", "물건")} {step} 질문', 'options': ['가', '나', '다']}


class FeatureChatTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_authenticate(self.user)
        self.image = make_image(self.user, ai_tags={'category': '지갑', 'color': '검정', 'features': []})

        patches = {
            'extract': mock.patch('items.feature_chat.extract_known_features', return_value=dict(KNOWN)),
            'question': mock.patch('items.feature_chat.write_feature_question', side_effect=ai_question),
            'summary': mock.patch(
                'items.feature_chat.summarize_item',
                return_value='손바닥만 한 검은색 가죽 반지갑으로, 학생증이 들어 있습니다.',
            ),
        }
        self.ai = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    def start(self, **data):
        data.setdefault('image_id', self.image.id)
        data.setdefault('description', '검은색 가죽 지갑이에요. 학생증이 들어 있어요.')
        return self.client.post(URL, data, format='json')

    def answer(self, chat_id, step, answer=None, is_skipped=False):
        return self.client.post(
            f'{URL}/{chat_id}/answers', {'step': step, 'answer': answer, 'is_skipped': is_skipped}, format='json'
        )

    def test_start_skips_known_steps(self):
        res = self.start()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['known'], {'category': '지갑', 'color': '검정'})
        self.assertEqual(res.data['question'], {'step': 'size', 'text': '지갑 size 질문', 'options': ['가', '나', '다']})
        self.assertFalse(res.data['is_finished'])

        chat = FeatureChat.objects.get(id=res.data['chat_id'])
        self.assertEqual(chat.input_description, '검은색 가죽 지갑이에요. 학생증이 들어 있어요.')
        tags, description = self.ai['extract'].call_args.args
        self.assertEqual(tags['category'], '지갑')
        self.assertIn('학생증', description)
        # 이미 파악한 항목도 턴으로 남김
        self.assertEqual(
            list(chat.turns.values_list('step_category', 'answer')),
            [('category', '지갑'), ('color', '검정'), ('size', None)],
        )

    def test_full_conversation_in_fixed_order(self):
        chat_id = self.start().data['chat_id']
        answers = {'size': '손바닥만 해요', 'material': '가죽', 'shape': '반지갑', 'marks': '모서리 해짐'}
        for step, value in answers.items():
            res = self.answer(chat_id, step, value)
            self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['question']['step'], 'brand')

        res = self.answer(chat_id, 'brand', is_skipped=True)  # 잘 모르겠어요
        self.assertTrue(res.data['is_finished'])
        self.assertIsNone(res.data['question'])
        self.assertEqual(res.data['summary'], '손바닥만 한 검은색 가죽 반지갑으로, 학생증이 들어 있습니다.')
        self.assertEqual(res.data['features'], {
            'category': '지갑', 'color': '검정', 'size': '손바닥만 해요', 'material': '가죽',
            'shape': '반지갑', 'marks': '모서리 해짐', 'brand': None,
        })

        chat = FeatureChat.objects.get(id=chat_id)
        self.assertTrue(chat.is_finished)
        self.assertEqual(chat.summary, res.data['summary'])
        self.assertTrue(chat.turns.get(step_category='brand').is_skipped)
        # 요약에는 사용자 설명과 수집한 특징이 들어감
        info = self.ai['summary'].call_args.args[0]
        self.assertEqual(info['features'], ['손바닥만 해요', '가죽', '반지갑', '모서리 해짐'])
        self.assertIn('학생증', info['detail'])

        self.assertEqual(self.answer(chat_id, 'brand', 'x').status_code, status.HTTP_409_CONFLICT)

    def test_finish_early(self):
        chat_id = self.start().data['chat_id']
        self.answer(chat_id, 'size', is_skipped=True)
        self.answer(chat_id, 'material', '가죽')

        res = self.client.post(f'{URL}/{chat_id}/finish')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['is_finished'])
        self.assertNotIn('question', res.data)
        self.assertEqual(res.data['features'], {
            'category': '지갑', 'color': '검정', 'size': None, 'material': '가죽',
            'shape': None, 'marks': None, 'brand': None,
        })
        res = self.client.post(f'{URL}/{chat_id}/finish')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['detail'], '이미 종료된 대화입니다.')

    def test_wrong_step_and_missing_answer(self):
        chat_id = self.start().data['chat_id']
        res = self.answer(chat_id, 'material', '가죽')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['detail'], '현재 질문 항목(size)에 대한 답변이 아닙니다.')

        res = self.answer(chat_id, 'size', '  ')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('answer', res.data)

        res = self.answer(chat_id, 'weight', '무거움')
        self.assertIn('step', res.data)

    def test_ai_failures_fall_back_to_tags_and_templates(self):
        self.ai['extract'].side_effect = AIError('off')
        self.ai['question'].side_effect = AIError('off')
        self.ai['summary'].side_effect = AIError('off')

        res = self.start()
        self.assertEqual(res.data['known'], {'category': '지갑', 'color': '검정'})  # 사진 태그로 대체
        self.assertEqual(res.data['question']['text'], '지갑 크기는 어느 정도였나요?')
        self.assertEqual(len(res.data['question']['options']), 3)

        res = self.client.post(f"{URL}/{res.data['chat_id']}/finish")
        self.assertIn('학생증이 들어 있어요', res.data['summary'])  # 템플릿 요약에 사용자 설명 포함

    def test_start_finishes_immediately_when_everything_known(self):
        self.ai['extract'].return_value = {
            'category': '지갑', 'color': '검정', 'size': '손바닥', 'material': '가죽',
            'shape': '반지갑', 'marks': '해짐', 'brand': '닥스',
        }
        res = self.start()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data['is_finished'])
        self.assertIsNone(res.data['question'])
        self.assertEqual(res.data['features']['brand'], '닥스')
        self.ai['question'].assert_not_called()

    def test_start_validation(self):
        res = self.client.post(URL, {'description': ' '}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['detail'], '사진 또는 물건 설명 중 하나 이상을 입력해 주세요.')

        for image_id in (make_image(make_user()).id, 999999):
            res = self.start(image_id=image_id)
            self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
            self.assertEqual(res.data['detail'], '이미지를 찾을 수 없습니다.')

        res = self.client.post(URL, {'description': '파란 우산'}, format='json')  # 텍스트만으로도 시작 가능
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(self.ai['extract'].call_args.args[0])

    def test_other_users_chat_is_not_found(self):
        chat_id = self.start().data['chat_id']
        self.client.force_authenticate(make_user())
        for res in (self.answer(chat_id, 'size', '작아요'), self.client.post(f'{URL}/{chat_id}/finish')):
            self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
            self.assertEqual(res.data['detail'], '대화를 찾을 수 없습니다.')
        self.assertEqual(FeatureChatTurn.objects.get(chat_id=chat_id, step_category='size').answer, None)
