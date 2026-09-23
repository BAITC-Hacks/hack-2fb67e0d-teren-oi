"""Short-lived server snapshots keep downloads tied to the displayed analysis."""

from collections import OrderedDict
from secrets import token_urlsafe
from threading import Lock
from time import monotonic


class ReportStore:
    def __init__(self, ttl_seconds: int = 3600, max_reports: int = 32, max_chars: int = 8_000_000):
        self.ttl_seconds = ttl_seconds
        self.max_reports = max_reports
        self.max_chars = max_chars
        self._reports: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = Lock()

    def _prune(self, now: float) -> None:
        for key, (created, _) in list(self._reports.items()):
            if now - created >= self.ttl_seconds:
                del self._reports[key]

    def put(self, markdown: str) -> str:
        if len(markdown) > self.max_chars:
            raise ValueError("Report exceeds snapshot capacity")
        with self._lock:
            self._prune(monotonic())
            while self._reports and (
                len(self._reports) >= self.max_reports
                or sum(len(value[1]) for value in self._reports.values()) + len(markdown) > self.max_chars
            ):
                self._reports.popitem(last=False)
            key = token_urlsafe(24)
            self._reports[key] = (monotonic(), markdown)
            return key

    def get(self, key: str) -> str | None:
        with self._lock:
            self._prune(monotonic())
            report = self._reports.get(key)
            return report[1] if report else None
