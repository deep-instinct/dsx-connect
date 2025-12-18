from dsx_connect.database.scan_stats_base_db import ScanStatsBaseDB
from dsx_connect.models.scan_result import ScanResultModel, ScanStatsModel
from dsx_connect.dsxa_client.verdict_models import DPAVerdictEnum

import heapq


class MedianTracker:
    def __init__(self):
        self.min_heap = []  # Min-heap for the larger half
        self.max_heap = []  # Max-heap for the smaller half

    def add_value(self, value: int):
        # Add value to max-heap (negative for max-heap behavior with heapq)
        if not self.max_heap or value <= -self.max_heap[0]:
            heapq.heappush(self.max_heap, -value)
        else:
            heapq.heappush(self.min_heap, value)

        # Balance the heaps
        if len(self.max_heap) > len(self.min_heap) + 1:
            heapq.heappush(self.min_heap, -heapq.heappop(self.max_heap))
        elif len(self.min_heap) > len(self.max_heap):
            heapq.heappush(self.max_heap, -heapq.heappop(self.min_heap))

    def get_median(self) -> int:
        if len(self.max_heap) > len(self.min_heap):
            return -self.max_heap[0]
        else:
            return int((-self.max_heap[0] + self.min_heap[0]) / 2)


class ScanStatsWorker:
    def __init__(self, scan_stats_db: ScanStatsBaseDB = None):
        self._scan_stats_db = scan_stats_db
        self.scan_time_median_tracker = MedianTracker()
        self.file_size_median_tracker = MedianTracker()

    def insert(self, scan_result: ScanResultModel):
        self._update_stats(scan_result)

    def _update_stats(self, scan_result: ScanResultModel):
        # Update and persist global stats
        total_stats = self._scan_stats_db.get()
        self._calculate_stats(total_stats, scan_result)
        self._scan_stats_db.upsert(total_stats)

    def _calculate_stats(self, stats: ScanStatsModel, scan_result: ScanResultModel):
        # Update cumulative stats
        stats.files_scanned += 1
        # Increment verdict counters
        try:
            v = scan_result.verdict.verdict if scan_result.verdict else None
            if v == DPAVerdictEnum.BENIGN:
                stats.benign_count += 1
            elif v == DPAVerdictEnum.MALICIOUS:
                stats.malicious_count += 1
            elif v == DPAVerdictEnum.UNKNOWN:
                stats.unknown_count += 1
            elif v == DPAVerdictEnum.UNSUPPORTED:
                stats.unsupported_count += 1
            elif v == DPAVerdictEnum.NOT_SCANNED:
                stats.not_scanned_count += 1
                try:
                    reason = (
                        scan_result.verdict.verdict_details.reason
                        if (scan_result.verdict and scan_result.verdict.verdict_details)
                        else None
                    )
                    if reason and reason.strip().lower() == "encrypted file":
                        stats.encrypted_count += 1
                except Exception:
                    pass
        except Exception:
            # best-effort; ignore if structure not present
            pass
        stats.total_scan_time_in_microseconds += scan_result.verdict.scan_duration_in_microseconds
        stats.total_scan_time_in_seconds = stats.total_scan_time_in_microseconds / 1000000
        stats.total_file_size += scan_result.verdict.file_info.file_size_in_bytes

        # Calculate averages
        stats.avg_file_size = int(stats.total_file_size / stats.files_scanned)
        stats.avg_scan_time_in_microseconds = int(stats.total_scan_time_in_microseconds / stats.files_scanned)
        stats.avg_scan_time_in_milliseconds = stats.avg_scan_time_in_microseconds / 1000
        stats.avg_scan_time_in_seconds = stats.avg_scan_time_in_milliseconds / 1000

        # Update longest scan time if applicable
        if scan_result.verdict.scan_duration_in_microseconds > stats.longest_scan_time_in_microseconds:
            stats.longest_scan_time_in_microseconds = scan_result.verdict.scan_duration_in_microseconds
            stats.longest_scan_time_in_milliseconds = stats.longest_scan_time_in_microseconds / 1000
            stats.longest_scan_time_in_seconds = stats.longest_scan_time_in_milliseconds / 1000
            # Ensure a string is stored; fallback when metadata_tag is None
            stats.longest_scan_time_file = (
                scan_result.metadata_tag
                or (scan_result.scan_request.location if scan_result.scan_request else "")
            )
            stats.longest_scan_time_file_size_in_bytes = scan_result.verdict.file_info.file_size_in_bytes

        # Add scan time to the median tracker and update the median
        self.scan_time_median_tracker.add_value(scan_result.verdict.scan_duration_in_microseconds)
        stats.median_scan_time_in_microseconds = self.scan_time_median_tracker.get_median()

        self.file_size_median_tracker.add_value(scan_result.verdict.file_info.file_size_in_bytes)
        stats.median_file_size_in_bytes = self.file_size_median_tracker.get_median()

    def get_scan_stats(self) -> ScanStatsModel:
        return self._scan_stats_db.get()
