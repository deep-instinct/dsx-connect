import asyncio
import sys
import platform
import logging

def run_async(task):
    """
    Utility function that awaits an async call, which has the affect of syncing the execution of one or more tasks.
    Equivalent of asyncio.run or run_until_complete.  There a few checks
    for platform (Win/Linux/Mac) and python version, as there are some differences in working with
    asyncio event loops between platforms/python versions.
    Args:
      task: coroutine/future 'task' (or a task of tasks)

    Returns:
    the results of running the task
    """
    if sys.version_info[0] == 3 and sys.version_info[1] >= 8 and sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    if platform.system() == 'Linux' and sys.version_info[1] == 6:
        logging.warning('Using python version 3.6 - using deprecated asyncio calls.')
        results = asyncio.get_event_loop().run_until_complete(task)
    else:
        results = asyncio.run(task)

    return results
