import os
from security_utils import encrypt_data
import argparse

def main():
    parser = argparse.ArgumentParser(description='Encrypt sensitive values')
    parser.add_argument('value', help='Value to encrypt')
    args = parser.parse_args()

    if 'MASTER_ENCRYPTION_KEY' not in os.environ:
        print("Error: MASTER_ENCRYPTION_KEY not set in environment")
        return

    encrypted = encrypt_data(args.value)
    print(f"Encrypted value: {encrypted}")

if __name__ == '__main__':
    main()