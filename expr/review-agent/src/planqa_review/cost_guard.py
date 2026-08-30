from __future__ import annotations

from dataclasses import dataclass, field

# 이번 세션에서 실제 서비스 관측치(문서당 $0.3–0.4, bundled_screen_hybrid의 confirm+context
# 토큰 8,792/문서 평균 기준)로 역산한 단가 — docs/progress.md 2026-08-12 참고. $7 상한은
# 사용자가 확정한 절대치(여유 없음).
DEFAULT_RATE_PER_MILLION_TOKENS = 40.0
DEFAULT_COST_CAP_USD = 7.0


class CostCapExceeded(RuntimeError):
    pass


@dataclass
class CostGuard:
    """모든 유료 제출/호출 전에 반드시 거쳐야 하는 사전 추정 게이트 — 배치는 제출 후엔
    처리된 만큼 과금되므로, 사후 감시가 아니라 제출 전 추정으로 막아야 한다는 게 이
    프로젝트의 명시적 요구사항. check_or_raise를 통과하지 못하면 그 단계를 제출/호출하지
    않고 그 자리에서 멈춘다(예외를 던져서 호출부가 "이미 완료된 부분은 보존, 이 단계는
    건너뜀"을 강제로 처리하게 함)."""

    cap_usd: float = DEFAULT_COST_CAP_USD
    spent_usd: float = 0.0
    log: list[str] = field(default_factory=list)

    def record_actual_tokens(self, tokens: int | None, *, rate_per_million: float = DEFAULT_RATE_PER_MILLION_TOKENS) -> None:
        if tokens:
            self.spent_usd += tokens / 1_000_000 * rate_per_million

    def record_actual_usd(self, usd: float) -> None:
        self.spent_usd += usd

    def can_afford(self, estimated_additional_usd: float) -> bool:
        return self.spent_usd + estimated_additional_usd <= self.cap_usd

    def check_or_raise(self, estimated_additional_usd: float, *, stage: str) -> None:
        if self.can_afford(estimated_additional_usd):
            return
        message = (
            f"[$7 cost guard] '{stage}' 단계 제출 중단 — 지금까지 사용량 ${self.spent_usd:.2f} + "
            f"이번 단계 예상 ${estimated_additional_usd:.2f} > 상한 ${self.cap_usd:.2f}"
        )
        self.log.append(message)
        raise CostCapExceeded(message)
