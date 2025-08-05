import os
import time
import logging
import subprocess
import requests
from security_utils import secure_audit_log, sandbox_command
from config import SecureConfig
import threading

logger = logging.getLogger(__name__)


class CircuitBreaker:
    def __init__(self, threshold=5, timeout=60):
        self.threshold = threshold
        self.timeout = timeout
        self.failures = 0
        self.last_failure = 0

    def allow_request(self):
        return time.time() - self.last_failure > self.timeout

    def record_failure(self):
        self.failures += 1
        self.last_failure = time.time()
        if self.failures >= self.threshold:
            logger.warning("Circuit breaker tripped!")


webhook_breaker = CircuitBreaker()


class SystemHealth:
    def __init__(self, admin_id):
        self.admin_id = admin_id
        self.last_check = time.time()
        self.error_count = 0
        self.max_errors = 20
        self.reset_interval = 3600

    def report_error(self, error):
        self.error_count += 1
        secure_audit_log("SYSTEM", "HEALTH_ERROR", f"Error #{self.error_count}: {str(error)}")

        if self.error_count > self.max_errors:
            logger.critical("Critical error threshold reached! Initiating restart...")
            self.send_admin_alert("🛑 Critical error threshold reached! Initiating restart...")
            self.restart_service()

    def periodic_check(self):
        if time.time() - self.last_check > self.reset_interval:
            self.error_count = 0
            self.last_check = time.time()

    def run_checks(self):
        results = {
            'db': self.check_db_connection(),
            'internet': self.check_internet(),
            'disk': self.check_disk_space(),
            'service': self.check_service_status()
        }

        if not all(results.values()):
            self.recover_system(results)

        return results

    def check_db_connection(self):
        try:
            from database import get_db_connection
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            return True
        except Exception as e:
            logger.error(f"Database check failed: {e}")
            return False

    def check_internet(self):
        try:
            result = sandbox_command("ping", ["-c", "1", "8.8.8.8"])
            return result.returncode == 0
        except:
            return False

    def check_disk_space(self):
        try:
            result = sandbox_command("df", ["-h", "/"])
            return "100%" not in result.stdout
        except:
            return False

    def check_service_status(self):
        try:
            result = sandbox_command("systemctl", ["is-active", "tg-bot.service"])
            return "active" in result.stdout
        except:
            return False

    def recover_system(self, status):
        logger.error("Critical system issue detected! Attempting recovery...")
        self.send_admin_alert("🛠️ System Recovery Initiated")
        secure_audit_log("SYSTEM", "RECOVERY_STARTED", str(status))

        if not status['db']:
            self.send_admin_alert("🔁 Restarting PostgreSQL...")
            sandbox_command("sudo", ["systemctl", "restart", "postgresql"])

        if not status['service']:
            self.send_admin_alert("🔁 Restarting Bot Service...")
            sandbox_command("sudo", ["systemctl", "restart", "tg-bot.service"])

        if not status['disk']:
            self.send_admin_alert("🧹 Cleaning temporary files...")
            sandbox_command("sudo", ["rm", "-rf", "/tmp/*"])
            sandbox_command("sudo", ["journalctl", "--vacuum-size=100M"])

        new_status = self.run_checks()
        status_report = "\n".join([f"{k}: {'OK' if v else 'FAIL'}" for k, v in new_status.items()])
        self.send_admin_alert(f"✅ Recovery Results:\n{status_report}")

    def restart_service(self):
        try:
            result = sandbox_command("sudo", ["systemctl", "restart", "tg-bot.service"])
            time.sleep(15)

            if result.returncode == 0 and self.check_service_status():
                self.send_admin_alert("✅ Service restarted successfully!")
                return True
            else:
                error_msg = f"❌ Service restart failed. Error: {result.stderr}"
                logger.error(error_msg)
                self.send_admin_alert(error_msg)
                return False
        except Exception as e:
            error_msg = f"❌ Restart failed: {str(e)}"
            logger.error(error_msg)
            self.send_admin_alert(error_msg)
            return False

    def send_admin_alert(self, message):
        admin_id = SecureConfig.get('ADMIN_ID', decrypt=True)
        if not admin_id:
            return

        try:
            bot_token = SecureConfig.get('TELEGRAM_TOKEN', decrypt=True)
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": admin_id,
                "text": f"🤖 Bot Alert:\n\n{message}",
                "parse_mode": "HTML"
            }
            response = requests.post(url, json=payload, timeout=10, verify=True)
            if response.status_code != 200:
                logger.error(f"Failed to send admin alert: {response.text}")
        except Exception as e:
            logger.error(f"Admin alert sending failed: {e}")
        finally:
            secure_erase(bot_token)