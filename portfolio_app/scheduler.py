"""Background jobs: the BSE end-of-day import.

* 6:15 PM and 7:15 PM IST, Monday to Friday.
* 15 seconds after start-up, then every 24 hours (catch-up and company-name backfill).

Set PORTFOLIO_SCHEDULER_ENABLED=false to switch the jobs off, for example while the
Java version is also running against the same database.
"""
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import bool_env
from .services import bse_importer

logger = logging.getLogger(__name__)


def start():
    if not bool_env("PORTFOLIO_SCHEDULER_ENABLED", True):
        logger.info("BSE import scheduler is switched off (PORTFOLIO_SCHEDULER_ENABLED=false)")
        return None
    scheduler = BackgroundScheduler(timezone=bse_importer.INDIA)
    scheduler.add_job(bse_importer.import_after_market_close,
                      CronTrigger(day_of_week="mon-fri", hour="18,19", minute=15, timezone=bse_importer.INDIA),
                      id="bse-after-market-close", max_instances=1, coalesce=True, misfire_grace_time=3600)
    scheduler.add_job(bse_importer.catch_up_after_startup,
                      IntervalTrigger(hours=24, timezone=bse_importer.INDIA),
                      next_run_time=datetime.now(bse_importer.INDIA) + timedelta(seconds=15),
                      id="bse-catch-up", max_instances=1, coalesce=True)
    scheduler.start()
    logger.info("BSE import scheduled at 6:15 PM and 7:15 PM IST, Monday to Friday")
    return scheduler
