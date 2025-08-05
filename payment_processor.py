import logging
import time
import threading
from binance.client import Client as BinanceClient
from database import record_payment, get_pending_payments
from security_utils import generate_ephemeral_wallet, secure_audit_log, secure_erase
from config import SecureConfig
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class PaymentProcessor:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_processor()
            return cls._instance

    def _init_processor(self):
        self._api_key = SecureConfig.get('BINANCE_API_KEY')
        self._api_secret = SecureConfig.get('BINANCE_API_SECRET')
        self.client = None
        self.wallets = {}
        self.running = True
        self.thread = threading.Thread(target=self._monitor_payments)
        self.thread.daemon = True
        self.init_client()
        self.thread.start()

    def init_client(self):
        if self._api_key and self._api_secret:
            self.client = BinanceClient(
                self._api_key,
                self._api_secret,
                requests_params={'timeout': 5}
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def _monitor_payments(self):
        while self.running:
            try:
                pending = get_pending_payments()
                for payment in pending:
                    self._check_payment_confirmation(payment)
                time.sleep(60)
            except Exception as e:
                logger.error(f"Payment monitoring error: {e}")
                time.sleep(300)

    def _check_payment_confirmation(self, payment):
        tx_id = payment['tx_id']
        try:
            tx_info = self.client.get_deposit_history(coin='USDT', txid=tx_id)
            if tx_info and tx_info['confirmations'] >= 1:
                self._confirm_payment(payment['user_id'], tx_id)
        except Exception as e:
            logger.error(f"Failed to check transaction {tx_id}: {e}")

    def _confirm_payment(self, user_id, tx_id):
        secure_audit_log(user_id, "PAYMENT_CONFIRMED", f"TX: {tx_id}")
        # Логика активации подписки

    def generate_payment_address(self, user_id, amount):
        wallet = generate_ephemeral_wallet()
        self.wallets[user_id] = {
            'address': wallet['address'],
            'amount': amount,
            'expires': wallet['expires']
        }
        secure_audit_log(user_id, "WALLET_GENERATED", wallet['address'])
        return wallet['address']

    def verify_payment(self, user_id, tx_id, amount):
        if tx_id in SecureConfig.get('DOUBLE_SPEND_DB'):
            return False

        try:
            tx_info = self.client.get_deposit_history(coin='USDT', txid=tx_id)
            if (tx_info and
                    tx_info['amount'] == amount and
                    tx_info['address'] == self.wallets.get(user_id, {}).get('address')):
                SecureConfig.get('DOUBLE_SPEND_DB')[tx_id] = True
                return True
        except Exception as e:
            logger.error(f"Payment verification failed: {e}")

        return False

    def shutdown(self):
        self.running = False
        self.thread.join(timeout=10)
        secure_erase(self._api_key)
        secure_erase(self._api_secret)
        self.client = None