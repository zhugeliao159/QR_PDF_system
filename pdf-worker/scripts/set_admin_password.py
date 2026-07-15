from __future__ import annotations

import getpass
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.password import hash_password  # noqa: E402


def main() -> int:
    password = getpass.getpass("请输入新的管理员密码（至少 12 个字符）：")
    confirmation = getpass.getpass("请再次输入密码：")
    if password != confirmation:
        print("两次输入的密码不一致。", file=sys.stderr)
        return 1
    try:
        encoded = hash_password(password)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("请将以下内容写入 .env 的 ADMIN_PASSWORD_HASH：")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
