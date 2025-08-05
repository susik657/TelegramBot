import os
import json
import logging
import threading
import sqlite3
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from security_utils import encrypt_data, decrypt_data, validate_phone, validate_email
import requests
import time
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class AccountManager:
    __slots__ = ['db_path', 'active_accounts', 'lock']

    def __init__(self):
        self.db_path = "admin_config.db"
        self.active_accounts = {}
        self.lock = threading.RLock()
        self._init_db()
        self.load_accounts()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS accounts
                         (
                             id
                             INTEGER
                             PRIMARY
                             KEY,
                             identifier
                             TEXT
                             NOT
                             NULL
                             UNIQUE,
                             auth_method
                             TEXT
                             NOT
                             NULL,
                             proxy
                             TEXT,
                             is_active
                             INTEGER
                             DEFAULT
                             0,
                             session_data
                             TEXT
                         )''')

            c.execute('''CREATE TABLE IF NOT EXISTS comment_templates
                         (
                             id
                             INTEGER
                             PRIMARY
                             KEY,
                             name
                             TEXT
                             NOT
                             NULL,
                             content_type
                             TEXT
                             NOT
                             NULL,
                             text_content
                             TEXT,
                             media_path
                             TEXT
                         )''')

            c.execute('''CREATE TABLE IF NOT EXISTS subscriptions
            (
                id
                INTEGER
                PRIMARY
                KEY,
                account_id
                INTEGER,
                channel_id
                TEXT
                NOT
                NULL,
                FOREIGN
                KEY
                         (
                account_id
                         ) REFERENCES accounts
                         (
                             id
                         )
                )''')
            conn.commit()

    def load_accounts(self):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM accounts")
            for row in c.fetchall():
                account_id, identifier, auth_method, proxy, is_active, session_data = row
                self.active_accounts[account_id] = {
                    'identifier': decrypt_data(identifier),
                    'auth_method': auth_method,
                    'proxy': decrypt_data(proxy) if proxy else None,
                    'is_active': bool(is_active),
                    'session_data': decrypt_data(session_data) if session_data else None
                }

    def add_account(self, identifier, auth_method, proxy=None):
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                if auth_method == 'phone' and not validate_phone(identifier):
                    raise ValueError("Invalid phone number")
                elif auth_method == 'email' and not validate_email(identifier):
                    raise ValueError("Invalid email")

                encrypted_id = encrypt_data(identifier)
                encrypted_proxy = encrypt_data(proxy) if proxy else None

                c.execute('''INSERT INTO accounts (identifier, auth_method, proxy)
                             VALUES (?, ?, ?)''',
                          (encrypted_id, auth_method, encrypted_proxy))
                conn.commit()
                return c.lastrowid

    def remove_account(self, account_id):
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
                c.execute("DELETE FROM subscriptions WHERE account_id = ?", (account_id,))
                conn.commit()
                if account_id in self.active_accounts:
                    del self.active_accounts[account_id]

    def toggle_account(self, account_id, status):
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute("UPDATE accounts SET is_active = ? WHERE id = ?", (int(status), account_id))
                conn.commit()
                if account_id in self.active_accounts:
                    self.active_accounts[account_id]['is_active'] = status

    def update_proxy(self, account_id, proxy):
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                encrypted_proxy = encrypt_data(proxy)
                c = conn.cursor()
                c.execute("UPDATE accounts SET proxy = ? WHERE id = ?", (encrypted_proxy, account_id))
                conn.commit()
                if account_id in self.active_accounts:
                    self.active_accounts[account_id]['proxy'] = proxy

    def save_session(self, account_id, session_data):
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                encrypted_session = encrypt_data(session_data)
                c = conn.cursor()
                c.execute("UPDATE accounts SET session_data = ? WHERE id = ?", (encrypted_session, account_id))
                conn.commit()
                if account_id in self.active_accounts:
                    self.active_accounts[account_id]['session_data'] = session_data

    def add_template(self, name, content_type, text=None, media_path=None):
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute('''INSERT INTO comment_templates (name, content_type, text_content, media_path)
                             VALUES (?, ?, ?, ?)''',
                          (name, content_type, text, media_path))
                conn.commit()
                return c.lastrowid

    def remove_template(self, template_id):
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute("DELETE FROM comment_templates WHERE id = ?", (template_id,))
                conn.commit()

    def subscribe_to_channel(self, account_id, channel_id):
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute('''INSERT INTO subscriptions (account_id, channel_id)
                             VALUES (?, ?)''', (account_id, channel_id))
                conn.commit()


class AutoCommenter:
    def __init__(self, account_manager):
        self.account_manager = account_manager
        self.running = False
        self.threads = {}
        self.queue = []
        self.queue_lock = threading.Lock()
        self.queue_processor = threading.Thread(target=self._process_queue)
        self.queue_processor.daemon = True

    def start(self):
        self.running = True
        self.queue_processor.start()
        for account_id, data in self.account_manager.active_accounts.items():
            if data['is_active'] and data['session_data']:
                self._start_account_thread(account_id)

    def stop(self):
        self.running = False
        for thread in self.threads.values():
            thread.join(timeout=5)

    def _start_account_thread(self, account_id):
        if account_id in self.threads:
            return

        thread = threading.Thread(target=self._monitor_channels, args=(account_id,))
        thread.daemon = True
        thread.start()
        self.threads[account_id] = thread

    def _monitor_channels(self, account_id):
        account_data = self.account_manager.active_accounts[account_id]

        client = TelegramClient(
            StringSession(account_data['session_data']),
            api_id=os.getenv('TELEGRAM_API_ID'),
            api_hash=os.getenv('TELEGRAM_API_HASH'),
            proxy=self._parse_proxy(account_data['proxy'])
        )

        @client.on(events.NewMessage)
        async def handler(event):
            if event.is_group or event.is_channel:
                with self.queue_lock:
                    self.queue.append((account_id, event))

        with client:
            client.run_until_disconnected()

    def _parse_proxy(self, proxy_str):
        if not proxy_str:
            return None

        try:
            parsed = urlparse(proxy_str)
            return {
                'scheme': parsed.scheme,
                'host': parsed.hostname,
                'port': parsed.port,
                'username': parsed.username,
                'password': parsed.password
            }
        except Exception as e:
            logger.error(f"Proxy parsing failed: {e}")
            return None

    def _process_queue(self):
        while self.running:
            with self.queue_lock:
                if not self.queue:
                    continue
                account_id, event = self.queue.pop(0)

            self._post_comment(account_id, event)
            time.sleep(5)

    def _post_comment(self, account_id, event):
        try:
            account_data = self.account_manager.active_accounts[account_id]
            client = TelegramClient(
                StringSession(account_data['session_data']),
                api_id=os.getenv('TELEGRAM_API_ID'),
                api_hash=os.getenv('TELEGRAM_API_HASH'),
                proxy=self._parse_proxy(account_data['proxy'])
            )

            with client:
                client.loop.run_until_complete(
                    client.send_message(
                        event.chat_id,
                        "Автоматический комментарий",
                        comment_to=event.id
                    )
                )
        except Exception as e:
            logger.error(f"Comment failed: {str(e)}")


class AdminPanel:
    def __init__(self, owner_id):
        self.owner_id = owner_id
        self.account_manager = AccountManager()
        self.commenter = AutoCommenter(self.account_manager)
        self.commenter.start()

    def is_admin(self, user_id):
        return user_id == self.owner_id

    def generate_deep_link(self, account_id):
        return f"https://t.me/your_bot?start=admin_auth_{account_id}"

    def check_proxy(self, proxy):
        try:
            test_url = "http://google.com"
            proxies = {"http": proxy, "https": proxy}
            response = requests.get(test_url, proxies=proxies, timeout=10)
            return response.status_code == 200
        except:
            return False