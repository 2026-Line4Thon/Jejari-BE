"""
알림 생성 인터페이스 (A 담당).

B의 매칭·소유권 확인 로직은 Notification 모델을 직접 만들지 않고 send()만 호출합니다.
"""

from .models import Notification

DEFAULT_MESSAGES = {
    Notification.Type.MATCH_CANDIDATE: (
        '새로운 매칭 후보가 발견되었어요!',
        '잃어버린 물건과 비슷한 습득물이 등록되었습니다.',
    ),
    Notification.Type.OWNERSHIP_RESULT: (
        '소유권 확인 결과가 나왔어요.',
        '소유권 확인 결과를 확인해 주세요.',
    ),
    Notification.Type.CHAT_STARTED: (
        '소유권 확인이 완료되었습니다.',
        '채팅방에서 물품 반환 일정을 약속해보세요.',
    ),
}


def send(user, type, target_type, target_id, title=None, message=None):
    default_title, default_message = DEFAULT_MESSAGES[type]
    return Notification.objects.create(
        user=user,
        type=type,
        target_type=target_type,
        target_id=target_id,
        title=title or default_title,
        message=message or default_message,
    )
