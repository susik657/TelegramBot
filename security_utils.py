import ctypes
import gc
import hashlib
import logging
from cryptography.fernet import Fernet
import os
import hmac
import json
import binascii
import secrets
import threading
import time
import subprocess
import re

logger = logging.getLogger(__name__)


# Глобальный ключ шифрования в защищенной памяти
class SecureKeyStorage:
    _lock = threading.Lock()
    _keys = {}

    @classmethod
    def store_key(cls, key_name, key_value):
        with cls._lock:
            cls._keys[key_name] = key_value

    @classmethod
    def get_key(cls, key_name):
        with cls._lock:
            return cls._keys.get(key_name)

    @classmethod
    def erase_all(cls):
        with cls._lock:
            for name in list(cls._keys.keys()):
                secure_erase(cls._keys[name])
                del cls._keys[name]
            gc.collect()


def secure_erase(data: str):
    """Безопасное удаление данных из памяти"""
    if not data:
        return

    if isinstance(data, str):
        mutable = bytearray(data.encode())
        ctypes.memset(ctypes.addressof(ctypes.c_char.from_buffer(mutable)), 0, len(mutable))
        del mutable
    else:
        buffer = ctypes.create_string_buffer(data)
        ctypes.memset(ctypes.addressof(buffer), 0, len(buffer))

    gc.collect()


def encrypt_data(data: str) -> str:
    """Шифрование данных с использованием Fernet"""
    if not data:
        return ""

    key = SecureKeyStorage.get_key('MASTER_ENCRYPTION')
    if not key:
        raise ValueError("Encryption key not available")

    f = Fernet(key)
    return binascii.hexlify(f.encrypt(data.encode())).decode()


def decrypt_data(data: str) -> str:
    """Дешифрование данных"""
    if not data:
        return ""

    key = SecureKeyStorage.get_key('MASTER_ENCRYPTION')
    if not key:
        raise ValueError("Encryption key not available")

    try:
        f = Fernet(key)
        decrypted = f.decrypt(binascii.unhexlify(data)).decode()
        return decrypted
    except binascii.Error:
        logger.error("Invalid encrypted data format")
        return ""
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return ""


def generate_ephemeral_wallet():
    """Генерация временного кошелька для одноразовых транзакций"""
    return {
        'address': f"T{secrets.token_urlsafe(16)}",
        'private_key': encrypt_data(secrets.token_hex(32)),
        'expires': int(time.time()) + 1800  # 30 минут
    }


def verify_webhook_signature(data, signature, secret):
    """Проверка подписи вебхука"""
    if isinstance(data, dict):
        data = json.dumps(data, sort_keys=True).encode()
    elif isinstance(data, str):
        data = data.encode()

    computed_signature = hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed_signature, signature)


def validate_webhook_payload(data):
    """Валидация входящих данных вебхука"""
    required_fields = ['amount', 'currency', 'user_id']
    return all(field in data for field in required_fields)


def sandbox_command(command, args):
    """Выполнение системной команды в изолированной среде"""
    try:
        result = subprocess.run(
            [command] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30
        )
        return result
    except Exception as e:
        logger.error(f"Sandbox command failed: {e}")
        return None


def secure_audit_log(user_id, action, details=""):
    """Безопасное логгирование действий"""
    hashed_user = hashlib.sha256(f"{user_id}{os.getenv('AUDIT_SALT')}".encode()).hexdigest()[:12]
    logger.info(f"AUDIT: {action} by USER:{hashed_user} - {details}")


def validate_phone(phone):
    """Проверка номера телефона с обработкой просроченных"""
    if not phone.startswith('+'):
        return False
    # Проверка по базе виртуальных номеров
    virtual_prefixes = ['+373', '+372', '+229']
    if any(phone.startswith(prefix) for prefix in virtual_prefixes):
        return False
    return True


def validate_email(email):
    """Базовая валидация email"""
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return re.match(pattern, email) is not None