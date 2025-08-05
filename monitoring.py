import sentry_sdk
import os
import logging
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from prometheus_client import start_http_server, Counter, Gauge, generate_latest
from flask import Response

logger = logging.getLogger(__name__)

METRIC_ERRORS = Counter('bot_errors', 'Application errors')
METRIC_DB_CONNECTIONS = Gauge('db_connections', 'Active DB connections')
METRIC_PAYMENTS = Counter('payments_total', 'Total payments', ['method'])

def init_monitoring(app):
    sentry_dsn = os.getenv('SENTRY_DSN')
    if sentry_dsn:
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[
                FlaskIntegration(),
                SqlalchemyIntegration(),
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)
            ],
            traces_sample_rate=1.0,
            release="bot@" + os.getenv("VERSION", "1.0.0"),
            environment=os.getenv("ENVIRONMENT", "production")
        )
        logger.info("Sentry monitoring initialized")
    else:
        logger.warning("SENTRY_DSN not set. Sentry monitoring disabled.")

    try:
        start_http_server(8000)
        logger.info("Prometheus metrics server started on port 8000")
    except Exception as e:
        logger.error(f"Failed to start Prometheus server: {e}")

    @app.route('/health')
    def health_check():
        try:
            from database import get_db_connection
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            return {
                'status': 'ok',
                'database': 'connected',
                'version': os.getenv("VERSION", "1.0.0")
            }, 200
        except Exception as e:
            return {'status': 'error', 'message': str(e)}, 500

    @app.route('/metrics')
    def metrics():
        return Response(generate_latest(), mimetype="text/plain")