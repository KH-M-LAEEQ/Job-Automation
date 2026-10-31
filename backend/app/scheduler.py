"""Background schedule shared by the API (single-process dev) and the standalone worker."""
import logging
import time
from datetime import datetime, timezone

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import get_settings
from app.services.crawl_service import process_search_queue, run_all_crawls
from app.services.discovery_backlog import process_backlogs
from app.services.followup_service import run_all_followups
from app.services.opportunity_service import run_opportunity_notifications

log = logging.getLogger("app.scheduler")

# Last outcome per scheduled task, exposed on /health so a silent stall is visible.
status: dict[str, dict] = {}


def _record(event) -> None:
    entry = status.setdefault(event.job_id, {})
    entry["last_run_at"] = datetime.now(timezone.utc).isoformat()
    if event.code == EVENT_JOB_ERROR:
        entry["last_error_at"] = entry["last_run_at"]
        entry["errors"] = entry.get("errors", 0) + 1
        log.error("Scheduled task %s failed", event.job_id, exc_info=event.exception)
    elif event.code == EVENT_JOB_MISSED:
        entry["missed"] = entry.get("missed", 0) + 1
        log.warning("Scheduled task %s missed its run time", event.job_id)
    else:
        entry["last_ok_at"] = entry["last_run_at"]


def build_scheduler() -> BackgroundScheduler:
    settings = get_settings()
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_all_crawls, "interval", hours=settings.crawl_interval_hours, id="crawl_all_users",
                      replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(run_all_followups, "interval", hours=settings.followup_interval_hours, id="followups_all_users",
                      replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(process_search_queue, "interval", seconds=15, id="search_queue",
                      replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(process_backlogs, "interval", minutes=1, id="discovery_backlog",
                      replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(run_opportunity_notifications, "interval", minutes=15, id="opportunity_notifications",
                      replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_listener(_record, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED)
    return scheduler


def shutdown_pools() -> None:
    from app.services import crawl_service, discovery_backlog
    for pool in (crawl_service._search_pool, discovery_backlog._backlog_pool):
        if pool is not None:
            pool.shutdown()


def run_forever() -> None:
    scheduler = build_scheduler()
    scheduler.start()
    log.info("Worker started")
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        scheduler.shutdown(wait=False)
        shutdown_pools()
