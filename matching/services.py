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


class CandidateLocked(Exception):
    """소유권 확인이 이미 진행된 후보 (→ 409)."""


def refresh_waiting_status(item):
    """
    후보가 제외되어 진행 중인 후보가 하나도 남지 않으면 CANDIDATE_FOUND → WAITING으로 되돌림.
    소유권 확인·채팅·반환 단계(VERIFYING 이후)는 건드리지 않음.
    """
    if item.status != ItemStatus.CANDIDATE_FOUND:
        return
    if not item.candidates.filter(status__in=MatchCandidate.ACTIVE_STATUSES).exists():
        item.status = ItemStatus.WAITING
        item.save(update_fields=['status', 'updated_at'])


@transaction.atomic
def reject_candidate(candidate):
    """「다른 물건이에요」: 후보를 EXCLUDED로 바꾸고 분실물·습득물 상태를 다시 계산."""
    candidate = MatchCandidate.objects.select_for_update().get(id=candidate.id)
    if candidate.status == MatchCandidate.Status.EXCLUDED:
        return candidate  # 이미 제외됨 (중복 요청)
    if candidate.status != MatchCandidate.Status.CANDIDATE or candidate.ownership_checks.exists():
        raise CandidateLocked

    candidate.status = MatchCandidate.Status.EXCLUDED
    candidate.save(update_fields=['status', 'updated_at'])
    refresh_waiting_status(candidate.lost_item)
    refresh_waiting_status(candidate.found_item)
    return candidate
