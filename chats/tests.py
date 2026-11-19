from django.db.models import Q, Max
from django.db.models.functions import Coalesce

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from common.testing import make_candidate, make_found_item, make_image, make_lost_item
from matching.models import MatchCandidate
from notifications.models import Notification
from chats.models import ChatRoom, ChatMessage

User = get_user_model()


class ChatAndReturnAPITestCase(APITestCase):
    def setUp(self):
        # 1. 테스트용 사용자 3명 생성 (분실자, 습득자, 제3자)
        self.owner = User.objects.create_user(
            email='owner@university.ac.kr',
            nickname='익명학우1',
            password='password123!'
        )
        self.finder = User.objects.create_user(
            email='finder@university.ac.kr',
            nickname='익명학우2',
            password='password123!'
        )
        self.stranger = User.objects.create_user(
            email='stranger@university.ac.kr',
            nickname='익명학우3',
            password='password123!'
        )

        # 2. 습득물 & 분실물 등록
        self.found_item = make_found_item(
            self.finder,
            image=make_image(self.finder, image_url='https://s3.example.com/found/15_blurred.jpg'),
            category='전자기기',
            item_name='무선 이어폰 케이스',
            color='검정색',
            brand='Apple',
            private_features='내부에 스티커 부착됨'
        )
        # 같은 분실물에 걸린 두 번째 습득물 (lost-found 쌍은 복합 UNIQUE라 별도 습득물 필요)
        self.other_found_item = make_found_item(self.finder, item_name='다른 이어폰 케이스')
        self.lost_item = make_lost_item(
            self.owner,
            item_name='검정색 무선 이어폰 케이스'
        )

        # 3. 매칭 후보 2건 생성 (소유권 검증 완료 건 vs 검증 미완료 건)
        self.verified_candidate = make_candidate(
            self.lost_item, self.found_item, status=MatchCandidate.Status.MATCHED
        )
        self.pending_candidate = make_candidate(
            self.lost_item, self.other_found_item, status=MatchCandidate.Status.CANDIDATE
        )

    def test_chat_room_creation_validation_and_success(self):
        """1. 비공개 채팅방 생성 API 테스트 (POST /chats)"""
        self.client.force_authenticate(user=self.owner)

        # (예외) candidate_id 누락 -> 400
        res_missing = self.client.post('/chats', {}, format='json')
        self.assertEqual(res_missing.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('candidate_id', res_missing.data)

        # (예외) 존재하지 않는 매칭 후보 -> 404
        res_not_found = self.client.post('/chats', {'candidate_id': 99999}, format='json')
        self.assertEqual(res_not_found.status_code, status.HTTP_404_NOT_FOUND)

        # (예외) 소유권 검증 미완료(PENDING) 상태에서 생성 시도 -> 403
        res_unverified = self.client.post('/chats', {'candidate_id': self.pending_candidate.id}, format='json')
        self.assertEqual(res_unverified.status_code, status.HTTP_403_FORBIDDEN)

        # (예외) 거래 당사자가 아닌 제3자 생성 시도 -> 403
        self.client.force_authenticate(user=self.stranger)
        res_stranger = self.client.post('/chats', {'candidate_id': self.verified_candidate.id}, format='json')
        self.assertEqual(res_stranger.status_code, status.HTTP_403_FORBIDDEN)

        # (성공) 소유권 검증 완료(VERIFIED) 상태로 분실자가 채팅방 생성 -> 200
        self.client.force_authenticate(user=self.owner)
        res_ok = self.client.post('/chats', {'candidate_id': self.verified_candidate.id}, format='json')
        self.assertEqual(res_ok.status_code, status.HTTP_200_OK)
        self.assertEqual(res_ok.data['status'], 'ACTIVE')
        self.assertEqual(res_ok.data['partner']['role'], 'FINDER')
        self.assertEqual(res_ok.data['item_summary']['item_name'], '검정색 무선 이어폰 케이스')

        # DB 상태 연동 확인: 분실물 상태가 CHATTING으로 바뀌고 양측에 CHAT_STARTED 알림이 생성되어야 함
        self.lost_item.refresh_from_db()
        self.found_item.refresh_from_db()
        self.assertEqual(self.lost_item.status, 'CHATTING')
        self.assertEqual(self.found_item.status, 'CHATTING')
        self.assertEqual(
            Notification.objects.filter(type='CHAT_STARTED', target_type='CHAT_ROOM').count(), 2
        )

    def test_chat_messages_send_and_list(self):
        """2 & 3. 채팅 메시지 전송 및 목록 조회 테스트 (POST/GET /chats/<id>/messages)"""
        chat_room = ChatRoom.objects.create(
            candidate=self.verified_candidate,
            owner=self.owner,
            finder=self.finder,
            status='ACTIVE'
        )
        msg_url = f'/chats/{chat_room.id}/messages'

        # (예외) 제3자 메시지 조회/전송 시도 -> 403
        self.client.force_authenticate(user=self.stranger)
        self.assertEqual(self.client.get(msg_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.post(msg_url, {'content': '안녕하세요'}, format='json').status_code,
            status.HTTP_403_FORBIDDEN
        )

        # (예외) 빈 메시지 전송 시도 -> 400
        self.client.force_authenticate(user=self.owner)
        res_empty = self.client.post(msg_url, {'content': '   '}, format='json')
        self.assertEqual(res_empty.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('content', res_empty.data)

        # (성공) 분실자 메시지 전송 -> 200
        res_send1 = self.client.post(msg_url, {'content': '오늘 3시에 중앙도서관에서 받을 수 있을까요?'}, format='json')
        self.assertEqual(res_send1.status_code, status.HTTP_200_OK)
        self.assertEqual(res_send1.data['sender_id'], self.owner.id)

        # (성공) 습득자 메시지 전송 -> 200
        self.client.force_authenticate(user=self.finder)
        res_send2 = self.client.post(msg_url, {'content': '네, 로비 안내데스크 앞에서 뵙겠습니다.'}, format='json')
        self.assertEqual(res_send2.status_code, status.HTTP_200_OK)

        # (성공) 분실자 시점에서 메시지 목록 조회 (is_mine 판별 및 상대방 메시지 읽음 처리 확인)
        self.client.force_authenticate(user=self.owner)
        res_list = self.client.get(f'{msg_url}?page=1&size=30')
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_list.data['messages']), 2)
        self.assertTrue(res_list.data['messages'][0]['is_mine'])
        self.assertFalse(res_list.data['messages'][1]['is_mine'])
        self.assertTrue(ChatMessage.objects.get(id=res_send2.data['message_id']).is_read)

    def test_chat_complete_and_block_further_messages(self):
        """4. 반환 완료 처리 및 종료 후 메시지 차단 테스트 (POST /chats/<id>/complete)"""
        chat_room = ChatRoom.objects.create(
            candidate=self.verified_candidate,
            owner=self.owner,
            finder=self.finder,
            status='ACTIVE'
        )
        complete_url = f'/chats/{chat_room.id}/complete'

        # (예외) 존재하지 않는 채팅방 -> 404
        self.client.force_authenticate(user=self.owner)
        self.assertEqual(self.client.post('/chats/99999/complete').status_code, status.HTTP_404_NOT_FOUND)

        # (예외) 제3자가 완료 처리 시도 -> 403
        self.client.force_authenticate(user=self.stranger)
        self.assertEqual(self.client.post(complete_url).status_code, status.HTTP_403_FORBIDDEN)

        # (성공) 참여자가 반환 완료 처리 -> 200
        self.client.force_authenticate(user=self.owner)
        res_complete = self.client.post(complete_url)
        self.assertEqual(res_complete.status_code, status.HTTP_200_OK)
        self.assertEqual(res_complete.data['status'], 'COMPLETED')
        self.assertEqual(res_complete.data['lost_item_status'], 'COMPLETED')
        self.assertEqual(res_complete.data['found_item_status'], 'COMPLETED')

        # DB 일괄 동기화 확인
        self.lost_item.refresh_from_db()
        self.found_item.refresh_from_db()
        self.verified_candidate.refresh_from_db()
        self.pending_candidate.refresh_from_db()
        self.assertEqual(self.lost_item.status, 'COMPLETED')
        self.assertEqual(self.found_item.status, 'COMPLETED')
        # 반환된 후보는 MATCHED 유지, 같은 분실물에 걸린 다른 후보는 EXCLUDED로 종료
        self.assertEqual(self.verified_candidate.status, 'MATCHED')
        self.assertEqual(self.pending_candidate.status, 'EXCLUDED')

        # (예외) 이미 완료된 건 중복 완료 요청 -> 400
        res_duplicate = self.client.post(complete_url)
        self.assertEqual(res_duplicate.status_code, status.HTTP_400_BAD_REQUEST)

        # (예외) 반환 완료된 채팅방에 추가 메시지 전송 시도 -> 400
        res_msg_after = self.client.post(
            f'/chats/{chat_room.id}/messages',
            {'content': '감사합니다!'},
            format='json'
        )
        self.assertEqual(res_msg_after.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_chat_room_list(self):
        """5. 내 채팅방 목록 조회 API 테스트 (GET /chats)"""
        # 활성 채팅방 1개 + 완료된 채팅방 1개 준비
        active_room = ChatRoom.objects.create(
            candidate=self.verified_candidate,
            owner=self.owner,
            finder=self.finder,
            status='ACTIVE'
        )
        ChatMessage.objects.create(
            chat_room=active_room,
            sender=self.finder,
            content='로비에서 뵙겠습니다.',
            is_read=False
        )

        self.pending_candidate.status = MatchCandidate.Status.MATCHED
        self.pending_candidate.save(update_fields=['status'])

        ChatRoom.objects.create(
            candidate=self.pending_candidate,
            owner=self.owner,
            finder=self.finder,
            status='COMPLETED'
        )

        # (성공) 분실자 기준 전체 목록 조회 -> 2건, 안 읽은 메시지 1건, 마지막 메시지 내용 확인
        self.client.force_authenticate(user=self.owner)
        res_all = self.client.get('/chats')
        self.assertEqual(res_all.status_code, status.HTTP_200_OK)
        self.assertEqual(res_all.data['total_count'], 2)

        active_data = next(c for c in res_all.data['chats'] if c['chat_room_id'] == active_room.id)
        self.assertEqual(active_data['unread_count'], 1)
        self.assertEqual(active_data['last_message']['content'], '로비에서 뵙겠습니다.')
        self.assertEqual(active_data['partner']['role'], 'FINDER')

        # (성공) ?status=ACTIVE 쿼리 필터링 조회 -> 1건만 반환
        res_active_only = self.client.get('/chats?status=ACTIVE')
        self.assertEqual(res_active_only.status_code, status.HTTP_200_OK)
        self.assertEqual(res_active_only.data['total_count'], 1)
        self.assertEqual(res_active_only.data['chats'][0]['status'], 'ACTIVE')

        # (성공) 제3자 기준 조회 -> 참여한 채팅방이 없으므로 0건 반환
        self.client.force_authenticate(user=self.stranger)
        res_stranger = self.client.get('/chats')
        self.assertEqual(res_stranger.status_code, status.HTTP_200_OK)
        self.assertEqual(res_stranger.data['total_count'], 0)