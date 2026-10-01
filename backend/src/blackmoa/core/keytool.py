"""Small operator helper for Fernet key migration/rotation."""
from __future__ import annotations

import argparse

from cryptography.fernet import Fernet

from blackmoa.core.security import legacy_fernet_key


def main() -> int:
    parser = argparse.ArgumentParser(description="black-moa encryption key helper")
    parser.add_argument("command", choices=("generate", "legacy"))
    args = parser.parse_args()
    if args.command == "generate":
        print(Fernet.generate_key().decode())
    else:
        # Reads BLACKMOA_SECRET_KEY from the environment; never pass secrets on argv.
        print(legacy_fernet_key())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
