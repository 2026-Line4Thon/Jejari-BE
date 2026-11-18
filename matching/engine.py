"""
매칭 엔진 진입점 (E-01 ~ E-08).

등록 API는 schedule_matching()만 호출하고, 실제 매칭은 커밋 후 별도 스레드에서 실행됩니다.
매칭 점수 계산·후보 저장은 다음 단계에서 run_matching()에 구현합니다.
"""

import logging
import threading

from django.db import close_old_connections, transaction

logger = logging.getLogger(__name__)

LOST = 'lost'
FOUND = 'found'


def run_matching(item_type, item_id):
    """item_type('lost'|'found') 건에 대해 반대 유형 전체와 매칭. 생성된 후보 목록 반환."""
    logger.info('매칭 엔진 미구현: %s #%s', item_type, item_id)
    return []


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
