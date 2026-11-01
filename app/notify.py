"""Notifications to dataset owners. In this exercise they are only logged."""

import logging
from dataclasses import dataclass
from datetime import date

log = logging.getLogger("notify")


@dataclass(frozen=True)
class Failure:
    dataset: str
    check: str
    record_key: str
    detail: str


class Notifier:
    def send_failure(self, owner: str, failure: Failure) -> None:
        """Tells an owner about one failure."""
        log.info(
            "to=%s dataset=%s check=%s record=%s: %s",
            owner, failure.dataset, failure.check, failure.record_key, failure.detail,
        )

    def send_digest(self, owner: str, run_date: date, failures: list[Failure]) -> None:
        """Tells an owner about every failure from one run, in one message."""
        log.info("to=%s digest for %s: %d failures", owner, run_date, len(failures))
        for failure in failures:
            log.info(
                "  %s / %s / %s: %s",
                failure.dataset, failure.check, failure.record_key, failure.detail,
            )
