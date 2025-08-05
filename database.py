import psycopg2
import os
import logging
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
from dotenv import load_dotenv
import threading
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, after_log
from contextlib import contextmanager
from alembic.config import Config
from alembic import command
from security_utils import decrypt_data

load_dotenv()

logger = logging.getLogger(__name__)
db_lock = threading.Lock()

# Пул соединений PostgreSQL
connection_pool = pool.ThreadedConnectionPool(
    minconn=1,
    maxconn=5,
    dsn=os.getenv('DATABASE_URL')
)

def get_db_connection():
    return connection_pool.getconn()

def put_db_connection(conn):
    connection_pool.putconn(conn)

def close_all_connections():
    connection_pool.closeall()

def apply_migrations():
    try:
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations applied successfully")
    except Exception as e:
        logger.error(f"Alembic migration failed: {e}")

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=(retry_if_exception_type(psycopg2.OperationalError) |
           retry_if_exception_type(psycopg2.InterfaceError)),
    after=after_log(logger, logging.WARNING)
def recover_db_connection():
    try:
        connection_pool.closeall()
    except:
        pass
    return get_db_connection()

@contextmanager
def transaction_context():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
        logger.error(f"DB connection error: {e}")
        conn.rollback()
        conn = recover_db_connection()
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        cursor.close()
        put_db_connection(conn)

def execute_with_rollback(func):
    def wrapper(*args, **kwargs):
        conn = get_db_connection()
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Database error: {e}", exc_info=True)
            conn.rollback()
            raise
        finally:
            put_db_connection(conn)
    return wrapper

@execute_with_rollback
def init_db():
    with transaction_context() as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(32) NOT NULL PRIMARY KEY
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                language VARCHAR(2) DEFAULT 'ru',
                state VARCHAR(50),
                discount_balance FLOAT DEFAULT 0,
                payment_attempts INT DEFAULT 0,
                last_payment_attempt TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id BIGINT PRIMARY KEY,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                plan_months INTEGER,
                payment_method VARCHAR(10),
                join_date TIMESTAMP,
                invite_sent BOOLEAN DEFAULT FALSE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                referrer_id BIGINT NOT NULL,
                referred_id BIGINT PRIMARY KEY,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                has_purchased BOOLEAN DEFAULT FALSE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS kofi_payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                amount FLOAT,
                payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS binance_payments (
                tx_id TEXT PRIMARY KEY,
                user_id BIGINT,
                asset TEXT,
                amount FLOAT,
                address TEXT,
                memo TEXT,
                status TEXT,
                confirmations INT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        apply_migrations()

@execute_with_rollback
def set_user_language(user_id, language):
    with transaction_context() as cursor:
        cursor.execute(
            'INSERT INTO users (user_id, language) VALUES (%s, %s) '
            'ON CONFLICT (user_id) DO UPDATE SET language = %s',
            (user_id, language, language)
        )

@execute_with_rollback
def get_user_language(user_id):
    with transaction_context() as cursor:
        cursor.execute(
            'SELECT language FROM users WHERE user_id = %s',
            (user_id,)
        )
        result = cursor.fetchone()
        return result['language'] if result else 'ru'

@execute_with_rollback
def add_subscription(user_id, start_date, end_date, plan_months, payment_method):
    with transaction_context() as cursor:
        cursor.execute(
            'INSERT INTO subscriptions (user_id, start_date, end_date, plan_months, payment_method) '
            'VALUES (%s, %s, %s, %s, %s) '
            'ON CONFLICT (user_id) DO UPDATE SET '
            'start_date = EXCLUDED.start_date, '
            'end_date = EXCLUDED.end_date, '
            'plan_months = EXCLUDED.plan_months, '
            'payment_method = EXCLUDED.payment_method',
            (user_id, start_date, end_date, plan_months, payment_method)
        )

@execute_with_rollback
def get_subscription(user_id):
    with transaction_context() as cursor:
        cursor.execute(
            'SELECT * FROM subscriptions WHERE user_id = %s',
            (user_id,)
        )
        return cursor.fetchone()

@execute_with_rollback
def get_expiring_subscriptions(days=7):
    with transaction_context() as cursor:
        cursor.execute('''
            SELECT user_id, end_date
            FROM subscriptions
            WHERE end_date BETWEEN NOW() AND NOW() + INTERVAL '%s days'
        ''', (days,))
        return cursor.fetchall()

@execute_with_rollback
def get_active_subscribers():
    with transaction_context() as cursor:
        cursor.execute('''
            SELECT user_id
            FROM subscriptions
            WHERE end_date > NOW()
        ''')
        return [row['user_id'] for row in cursor.fetchall()]

@execute_with_rollback
def cleanup_expired_subscriptions():
    with transaction_context() as cursor:
        cursor.execute('''
            DELETE
            FROM subscriptions
            WHERE end_date < NOW()
        ''')
        logger.info(f"Cleaned up {cursor.rowcount} expired subscriptions")