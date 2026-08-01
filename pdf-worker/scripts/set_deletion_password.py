from __future__ import annotations

import getpass
import os
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.password import hash_password  # noqa: E402


def update_env(path: Path, encoded: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith("DELETION_PASSWORD_HASH="):
            output.append(f"DELETION_PASSWORD_HASH={encoded}")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append(f"DELETION_PASSWORD_HASH={encoded}")
    descriptor, temporary = tempfile.mkstemp(prefix=".env-deletion-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join(output) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    if len(sys.argv) != 2:
        print("用法：python scripts/set_deletion_password.py /path/to/.env", file=sys.stderr)
        return 2
    env_path = Path(sys.argv[1]).resolve()
    if not env_path.is_file():
        print("没有找到指定的 .env 文件。", file=sys.stderr)
        return 2
    password = getpass.getpass("请输入永久删除二级密码（至少 16 个字符）：")
    confirmation = getpass.getpass("请再次输入二级密码：")
    if password != confirmation:
        print("两次输入的密码不一致。", file=sys.stderr)
        return 1
    try:
        encoded = hash_password(password)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    update_env(env_path, encoded)
    print("二级密码已安全写入 .env；密码和哈希均未输出。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
