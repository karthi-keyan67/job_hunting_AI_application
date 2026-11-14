import os
import re
import uuid
from pathlib import Path


class LocalResumeStorage:
    _key_pattern = re.compile(r"^[0-9a-f]{32}\.(pdf|docx)$")

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    def save(self, content: bytes, extension: str) -> str:
        key = f"{uuid.uuid4().hex}.{extension}"
        target = self.root / key
        temporary = self.root / f".{key}.tmp"
        with temporary.open("xb") as handle:
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return key

    def path_for(self, key: str) -> Path:
        if not self._key_pattern.fullmatch(key):
            raise ValueError("Invalid storage key")
        path = (self.root / key).resolve()
        if path.parent != self.root:
            raise ValueError("Invalid storage path")
        return path

    def delete(self, key: str) -> None:
        self.path_for(key).unlink(missing_ok=True)
