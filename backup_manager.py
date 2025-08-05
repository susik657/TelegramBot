import os
import subprocess
from datetime import datetime
import logging
from dotenv import load_dotenv
from security_utils import decrypt_data

load_dotenv()
logger = logging.getLogger(__name__)


class BackupManager:
    def __init__(self):
        self.backup_dir = os.getenv('BACKUP_DIR', 'backups')
        self.max_backups = int(os.getenv('MAX_BACKUPS', 7))
        os.makedirs(self.backup_dir, exist_ok=True)

    def create_backup(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.backup_dir}/backup_{timestamp}.sql"
        encrypted_url = os.getenv('DATABASE_URL')
        db_url = decrypt_data(encrypted_url) if encrypted_url else None

        if not db_url:
            logger.error("Database URL decryption failed")
            return None

        try:
            cmd = [
                "pg_dump",
                "-d", db_url,
                "-f", filename,
                "-F", "c"
            ]

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300
            )

            if result.returncode == 0:
                logger.info(f"Backup created: {filename}")
                self.rotate_backups()
                return filename
            else:
                logger.error(f"Backup failed with exit code {result.returncode}: {result.stderr}")
                return None
        except Exception as e:
            logger.error(f"Backup failed: {str(e)}")
            return None

    def rotate_backups(self):
        try:
            backups = []
            for f in os.listdir(self.backup_dir):
                if f.startswith("backup_") and f.endswith(".sql"):
                    file_path = os.path.join(self.backup_dir, f)
                    backups.append((file_path, os.path.getmtime(file_path)))

            backups.sort(key=lambda x: x[1])

            while len(backups) > self.max_backups:
                oldest = backups.pop(0)
                try:
                    os.remove(oldest[0])
                    logger.info(f"Removed old backup: {oldest[0]}")
                except Exception as e:
                    logger.error(f"Failed to remove backup {oldest[0]}: {e}")
        except Exception as e:
            logger.error(f"Backup rotation failed: {e}")

    def restore_backup(self, filepath):
        try:
            encrypted_url = os.getenv('DATABASE_URL')
            db_url = decrypt_data(encrypted_url) if encrypted_url else None

            if not db_url:
                logger.error("Database URL decryption failed")
                return False

            cmd = [
                "pg_restore",
                "-d", db_url,
                "-c",
                filepath
            ]

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=600
            )

            if result.returncode == 0:
                logger.info(f"Backup restored successfully: {filepath}")
                return True
            else:
                logger.error(f"Restore failed with exit code {result.returncode}: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Restore failed: {str(e)}")
            return False