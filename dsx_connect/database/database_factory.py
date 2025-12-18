from dsx_connect.database.scan_stats_collection import ScanStatsCollection
from dsx_connect.database.scan_stats_redis import ScanStatsRedisDB
from dsx_connect.database.scan_results_collection import ScanResultsCollection
from dsx_connect.database.scan_results_redis import ScanResultsRedisDB
from shared.dsx_logging import dsx_logging


def database_scan_results_factory(database_loc: str = 'redis://redis:6379/3',
                                  retain: int = -1,
                                  collection_name: str = 'scan_results'):
    """Create a scan results DB. Uses Redis when database_loc starts with redis://, else in-memory.
    """
    if str(database_loc).startswith("redis://"):
        dsx_logging.debug(f"Scan results Redis database initialized (loc='{database_loc}')")
        return ScanResultsRedisDB(retain=retain, collection_name=collection_name)
    dsx_logging.debug(f'Scan results collection in memory. Retention policy: {retain}')
    return ScanResultsCollection(retain=retain)


def database_scan_stats_factory(database_loc: str = 'redis://redis:6379/3',
                                collection_name: str = 'scan_stats'):
    """Create a scan stats DB. Uses Redis when database_loc starts with redis://, else in-memory."""
    if str(database_loc).startswith("redis://"):
        dsx_logging.debug(f"Scan stats Redis database initialized (loc='{database_loc}')")
        return ScanStatsRedisDB(collection_name=collection_name)
    dsx_logging.debug('Scan stats collection in memory.')
    return ScanStatsCollection()
