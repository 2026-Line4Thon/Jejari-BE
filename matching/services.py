from django.db import transaction
from django.db.models import Q

from items.models import ItemStatus

from .models import MatchCandidate


@transaction.atomic
def complete_return(candidate):
    """
    반환 완료 처리(chats)에서 호출하는 상태 전환 함수.

    - 분실물·습득물을 COMPLETED로 전환
    - 같은 물건에 걸려 있던 다른 진행 중 후보는 EXCLUDED로 종료
    - 반환된 후보 자체는 MATCHED 상태 유지 (완료 여부는 ChatRoom.status로 판단)
    """
    lost_item = candidate.lost_item
    found_item = candidate.found_item

    lost_item.status = ItemStatus.COMPLETED
    lost_item.save(update_fields=['status', 'updated_at'])
    found_item.status = ItemStatus.COMPLETED
    found_item.save(update_fields=['status', 'updated_at'])

    MatchCandidate.objects.filter(
        Q(lost_item=lost_item) | Q(found_item=found_item),
        status__in=[MatchCandidate.Status.CANDIDATE, MatchCandidate.Status.VERIFYING],
    ).exclude(id=candidate.id).update(status=MatchCandidate.Status.EXCLUDED)

    return lost_item, found_item
