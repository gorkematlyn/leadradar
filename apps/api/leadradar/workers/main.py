"""Worker process entry point.

* ``discovery`` queue: Geofabrik/CSV/Apify imports, campaigns, retention, score
  recalculation; also runs the database-locked scheduler.
* ``analysis`` queue: website audits (Playwright/Lighthouse), ad research, PDF rendering,
  monitoring. Heavy tasks share the global heavy-task concurrency limit.
"""

from __future__ import annotations

import logging
import threading

from leadradar.jobs.runtime import HANDLERS, Worker

log = logging.getLogger(__name__)


def register_handlers() -> None:
    # Importing modules registers their @handler functions.
    import leadradar.modules.advertising.apify  # noqa: F401
    import leadradar.modules.advertising.service  # noqa: F401
    import leadradar.modules.crm.maintenance  # noqa: F401
    import leadradar.modules.crm.monitoring  # noqa: F401
    import leadradar.modules.discovery.handlers  # noqa: F401
    import leadradar.modules.reporting.service  # noqa: F401
    import leadradar.modules.website_audit.service  # noqa: F401


def run_worker(queues: list[str], concurrency: int) -> None:
    register_handlers()
    queues = [q.strip() for q in queues if q.strip()]
    log.info("starting worker", extra={"data": {"queues": queues, "concurrency": concurrency,
                                                 "handlers": sorted(HANDLERS)}})
    worker = Worker(queues, concurrency)
    if "discovery" in queues:
        from leadradar.jobs.scheduler import scheduler_loop

        stop = threading.Event()
        worker.extra_loops.append(lambda: scheduler_loop(stop))
    if "analysis" in queues:
        # Start the egress proxy eagerly so failures surface at boot.
        from leadradar.modules.netsafe.proxy import get_egress_proxy

        get_egress_proxy()
    worker.run()
