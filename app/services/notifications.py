"""Optional notifications after a collection run.

Only a console notifier ships with the MVP. Email / Slack / Telegram can be
added by implementing :class:`NotificationProvider`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.core.config import NotificationName, Settings

if TYPE_CHECKING:
    from app.services.collection import CollectionRunResult

logger = logging.getLogger(__name__)


class NotificationProvider(ABC):
    @abstractmethod
    def notify_run_completed(self, result: CollectionRunResult) -> None: ...


class NullNotificationProvider(NotificationProvider):
    def notify_run_completed(self, result: CollectionRunResult) -> None:
        return None


class ConsoleNotificationProvider(NotificationProvider):
    def notify_run_completed(self, result: CollectionRunResult) -> None:
        logger.info(
            "Collection run %s finished with status %s: %d new posts from %d sources (%d errors)",
            result.run_id,
            result.status,
            result.posts_saved,
            result.sources_processed,
            result.error_count,
            extra={"event": "notification", "run_id": result.run_id},
        )


def build_notifier(settings: Settings) -> NotificationProvider:
    if settings.notification_provider is NotificationName.CONSOLE:
        return ConsoleNotificationProvider()
    return NullNotificationProvider()
