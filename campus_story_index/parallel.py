"""Run file jobs without retaining a Future for every resource in a release."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from itertools import islice


def map_bounded(function, items, workers):
    """Yield completed results, with at most two queued/running jobs per worker."""
    if workers < 1:
        raise ValueError('workers must be positive')
    items = iter(items)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(function, item) for item in islice(items, workers * 2)}
        try:
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    yield future.result()
                pending.update(pool.submit(function, item) for item in islice(items, len(done)))
        finally:
            for future in pending:
                future.cancel()
