# backend/auth/middleware.py
"""
招待トークン参加エンドポイントへの総当たり攻撃を抑制する簡易レート制限。

NOTE: プロセス内メモリでの実装のため、複数プロセス/複数インスタンス構成では
      機能しない（インスタンスごとに別カウントになる）。将来的に水平スケールする場合は
      Redis等の共有ストアに置き換える必要がある。現状（単一インスタンスのコンペ本番運用）では十分。
"""

import time
from collections import defaultdict

from fastapi import HTTPException, Request

WINDOW_SECONDS = 60
MAX_ATTEMPTS_PER_WINDOW = 10

_attempts: dict[str, list[float]] = defaultdict(list)


def rate_limit_invitation_join(request: Request) -> None:
    """IPアドレスごとに単位時間あたりの参加試行回数を制限する"""
    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()

    attempts = _attempts[client_ip]
    while attempts and attempts[0] < now - WINDOW_SECONDS:
        attempts.pop(0)

    if len(attempts) >= MAX_ATTEMPTS_PER_WINDOW:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "RATE_LIMITED",
                "message": "試行回数が多すぎます。しばらく待ってから再試行してください。",
            },
        )

    attempts.append(now)
