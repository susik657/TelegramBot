import os
from security_utils import encrypt_data, decrypt_data

class SecureConfig:
    _config = {}
    _encrypted_fields = [
        'TELEGRAM_TOKEN', 'BINANCE_API_KEY', 'BINANCE_API_SECRET',
        'BINANCE_USDT_ADDRESS', 'KOFI_WEBHOOK_TOKEN', 'ADMIN_ID',
        'DATABASE_URL', 'SENTRY_DSN'
    ]

    @classmethod
    def load(cls):
        cls._config = {
            'PLANS': {
                '1_month': {'price': 105, 'duration': 30},
                '2_months': {'price': 165, 'duration': 60},
                '3_months': {'price': 280, 'duration': 90},
                '4_months': {'price': 450, 'duration': 120}
            },
            'REFERRAL_DISCOUNT': 0.05,
            'MAX_USDT_ATTEMPTS': 3,
            'BLOCK_TIME_HOURS': 24,
            'KOFI_DELAY_DAYS': 8,
            'ALLOWED_VPN_IPS': ['192.168.1.1', '10.0.0.1'],
            'AUDIT_SALT': os.getenv('AUDIT_SALT', 'default-salt-value'),
            'DOUBLE_SPEND_DB': {}
        }

        for field in cls._encrypted_fields:
            value = os.getenv(field)
            if value:
                cls._config[field] = encrypt_data(value)

    @classmethod
    def get(cls, key, decrypt=False):
        value = cls._config.get(key)
        if decrypt and value and key in cls._encrypted_fields:
            return decrypt_data(value)
        return value

SecureConfig.load()