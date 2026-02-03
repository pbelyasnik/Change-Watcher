import logging

from apscheduler.schedulers.background import BackgroundScheduler

from config import Config

logger = logging.getLogger(__name__)

_scheduler = None


def init_scheduler(app):
    global _scheduler
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        master_tick,
        'interval',
        seconds=Config.CHECK_INTERVAL_SECONDS,
        args=[app],
        id='master_tick',
        replace_existing=True
    )
    _scheduler.add_job(
        daily_cleanup,
        'cron',
        hour=3,
        minute=0,
        args=[app],
        id='daily_cleanup',
        replace_existing=True
    )
    _scheduler.start()
    logger.info('Scheduler started')


def master_tick(app):
    with app.app_context():
        from db import get_db
        from services.checker import check_item

        try:
            db = get_db()
            items = db.execute(
                "SELECT * FROM watch_items WHERE status = 'active' "
                "AND (last_checked_at IS NULL "
                "OR datetime(last_checked_at, '+' || interval_minutes || ' minutes', '-5 seconds') <= datetime('now'))"
            ).fetchall()

            for item in items:
                try:
                    result = check_item(dict(item))
                    if result.get('error'):
                        logger.warning(
                            'Item %s (%s): %s', item['id'], item['name'], result['error']
                        )
                    elif result.get('value_changed'):
                        logger.info(
                            'Item %s (%s): value changed, notification_sent=%s',
                            item['id'], item['name'], result['notification_sent']
                        )
                except Exception as e:
                    logger.error('Error checking item %s (%s): %s', item['id'], item['name'], e)
        except Exception as e:
            logger.error('master_tick failed: %s', e)


def daily_cleanup(app):
    with app.app_context():
        from db import get_db

        db = get_db()
        try:
            db.execute(
                "DELETE FROM request_logs WHERE executed_at < datetime('now', '-30 days')"
            )
            db.execute(
                "DELETE FROM login_logs WHERE created_at < datetime('now', '-30 days')"
            )
            db.execute(
                "DELETE FROM sessions WHERE last_activity_at < datetime('now', '-7 days')"
            )
            db.commit()
            logger.info('Daily cleanup completed')
        except Exception as e:
            logger.error('Cleanup error: %s', e)
