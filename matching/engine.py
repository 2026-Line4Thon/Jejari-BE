"""
매칭 엔진 (E-01 ~ E-08).

등록 API는 schedule_matching()만 호출하고, 실제 매칭은 커밋 후 별도 스레드에서 실행됩니다.
재매칭(E-06)은 따로 없고, 분실물·습득물이 등록될 때마다 반대 유형의 "반환되지 않은 모든 건"을 대상으로
같은 run_matching()을 실행합니다.

1. 사전 필터: 반대 유형, 반환 완료 아님, 본인 등록 건 아님, 습득 시각 >= 분실 시작 시각,
   분실 추정 끝 시각 후 MATCHING_WINDOW_DAYS 이내, 이미 후보로 묶인 쌍은 제외
2. 1차 후보: pgvector 코사인 거리로 text_embedding 상위 TOP_K
3. 최종 점수: matching.scoring (임베딩·태그·장소·시간 가중 합산)
4. 기준 점수 이상만 후보 저장 + 라벨 + 근거 문장
5. 후보가 생긴 분실물·습득물을 CANDIDATE_FOUND로 전환, 분실자에게 알림
"""

import logging
import math
import threading
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import IntegrityError, close_old_connections, transaction
from pgvector.django import CosineDistance

from items.models import FoundItem, ItemStatus, LostItem
from notifications import services as notification_services
from notifications.models import Notification

from . import reasons as match_reasons
from . import scoring
from .models import MatchCandidate

logger = logging.getLogger(__name__)

LOST = 'lost'
FOUND = 'found'

TOP_K = 20
MATCHING_WINDOW_DAYS = 14
AI_REASON_LIMIT = 3  # 한 번 실행에서 AI 근거 문장을 만드는 상위 후보 수


@dataclass
class MatchResult:
    lost: LostItem
    found: FoundItem
    scores: dict
    total: float
    label: str
    reasons: list = field(default_factory=list)
    candidate: MatchCandidate | None = None


# ---------------------------------------------------------------------------
# 1~2. 사전 필터 + 벡터 상위 후보
# ---------------------------------------------------------------------------

def _found_candidates_for(lost):
    return (
        FoundItem.objects.select_related('place')
        .exclude(status=ItemStatus.COMPLETED)
        .exclude(finder_id=lost.user_id)
        .filter(
            found_at__gte=lost.lost_from,
            found_at__lte=lost.lost_to + timedelta(days=MATCHING_WINDOW_DAYS),
        )
        .exclude(candidates__lost_item=lost)
        .annotate(distance=CosineDistance('text_embedding', lost.text_embedding))
        .order_by('distance')[:TOP_K]
    )


def _lost_candidates_for(found):
    return (
        LostItem.objects.select_related('place')
        .exclude(status=ItemStatus.COMPLETED)
        .exclude(user_id=found.finder_id)
        .filter(
            lost_from__lte=found.found_at,
            lost_to__gte=found.found_at - timedelta(days=MATCHING_WINDOW_DAYS),
        )
        .exclude(candidates__found_item=found)
        .annotate(distance=CosineDistance('text_embedding', found.text_embedding))
        .order_by('distance')[:TOP_K]
    )


# ---------------------------------------------------------------------------
# 3. 점수
# ---------------------------------------------------------------------------

def pair_facts(lost, found, distance):
    gap = (found.found_at - lost.lost_to).total_seconds() / 3600
    return scoring.PairFacts(
        embedding_similarity=1 - float(distance),
        lost_category=lost.category,
        found_category=found.category,
        lost_color=lost.color,
        found_color=found.color,
        lost_brand=lost.brand,
        found_brand=found.brand,
        same_place=lost.place_id == found.place_id,
        distance_m=scoring.haversine_m(
            lost.place.latitude, lost.place.longitude, found.place.latitude, found.place.longitude
        ),
        gap_hours=max(0.0, gap),
    )


def _score_pairs(item_type, item):
    if item_type == LOST:
        pairs = [(item, other) for other in _found_candidates_for(item)]
    else:
        pairs = [(other, item) for other in _lost_candidates_for(item)]

    results = []
    for lost, found in pairs:
        other = found if item_type == LOST else lost
        if other.distance is None or math.isnan(other.distance):
            continue  # 영벡터 등으로 거리를 계산할 수 없는 경우
        facts = pair_facts(lost, found, other.distance)
        scores, total = scoring.score(facts)
        if total < scoring.MIN_TOTAL_SCORE:
            continue
        result = MatchResult(lost, found, scores, total, scoring.label_for(total))
        result.reasons = match_reasons.rule_reasons(lost, found, facts, scores)
        results.append(result)
    return sorted(results, key=lambda r: r.total, reverse=True)


# ---------------------------------------------------------------------------
# 4~5. 저장 + 상태 전환 + 알림
# ---------------------------------------------------------------------------

def _save(results):
    created = []
    for result in results:
        try:
            with transaction.atomic():
                result.candidate = MatchCandidate.objects.create(
                    lost_item=result.lost,
                    found_item=result.found,
                    total_score=result.total,
                    similarity_label=result.label,
                    match_reasons=result.reasons,
                )
        except IntegrityError:
            continue  # 동시에 실행된 다른 매칭이 같은 쌍을 먼저 저장함
        created.append(result)
    return created


def _mark_candidate_found(items):
    for item in items:
        if item.status == ItemStatus.WAITING:
            item.status = ItemStatus.CANDIDATE_FOUND
            item.save(update_fields=['status', 'updated_at'])


def _notify_lost_owners(created):
    """분실물마다 이번 실행에서 가장 점수가 높은 새 후보 하나로 알림."""
    best_by_lost = {}
    for result in created:  # 점수 높은 순
        best_by_lost.setdefault(result.lost.id, result)
    for result in best_by_lost.values():
        notification_services.send(
            user=result.lost.user,
            type=Notification.Type.MATCH_CANDIDATE,
            target_type=Notification.TargetType.CANDIDATE,
            target_id=result.candidate.id,
        )


def _write_ai_reasons(created):
    for result in created[:AI_REASON_LIMIT]:
        written = match_reasons.ai_reasons(result.lost, result.found, result.reasons)
        if written != result.reasons:
            result.reasons = written
            result.candidate.match_reasons = written
            result.candidate.save(update_fields=['match_reasons', 'updated_at'])


def run_matching(item_type, item_id):
    """item_type('lost'|'found') 건을 반대 유형 전체와 매칭하고, 새로 만든 후보 결과 목록을 반환."""
    model = LostItem if item_type == LOST else FoundItem
    item = model.objects.select_related('place').filter(id=item_id).first()
    if item is None or item.status == ItemStatus.COMPLETED:
        return []

    created = _save(_score_pairs(item_type, item))
    if not created:
        return []

    _mark_candidate_found({r.lost.id: r.lost for r in created}.values())
    _mark_candidate_found({r.found.id: r.found for r in created}.values())
    _notify_lost_owners(created)
    _write_ai_reasons(created)  # AI 호출이 느리므로 저장·알림 뒤에 실행
    logger.info('매칭 완료: %s #%s → 후보 %d건', item_type, item_id, len(created))
    return created


# ---------------------------------------------------------------------------
# 등록 API에서 호출
# ---------------------------------------------------------------------------

def _run_in_thread(item_type, item_id):
    try:
        run_matching(item_type, item_id)
    except Exception:
        logger.exception('매칭 실행 실패: %s #%s', item_type, item_id)
    finally:
        close_old_connections()  # 스레드가 연 DB 연결 정리


def schedule_matching(item_type, item_id):
    """등록 트랜잭션이 커밋된 뒤 백그라운드 스레드에서 매칭 실행."""
    transaction.on_commit(
        lambda: threading.Thread(
            target=_run_in_thread, args=(item_type, item_id), daemon=True
        ).start()
    )
