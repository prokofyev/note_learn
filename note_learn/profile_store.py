from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from note_learn.curriculum import PlayerProfile


DEFAULT_STORE_ROOT = Path.home() / ".note_learn"
DEFAULT_LEGACY_PROFILE_PATH = Path.home() / ".note_learn_profile.json"
DEFAULT_USER_NAME = "Ученик"
MAX_NAME_LENGTH = 40

# Транслитерация для читаемых имён файлов профилей (кириллица -> латиница)
_TRANSLIT: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(name: str) -> str:
    """Превращает имя пользователя в безопасный для файловой системы идентификатор."""
    lowered = str(name).strip().lower()
    chunks: list[str] = []
    for char in lowered:
        if char in _TRANSLIT:
            chunks.append(_TRANSLIT[char])
        elif char.isascii() and char.isalnum():
            chunks.append(char)
        else:
            chunks.append("-")
    slug = re.sub(r"-+", "-", "".join(chunks)).strip("-")
    return slug


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class UserRecord:
    id: str
    name: str
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ProfileStore:
    """
    Хранилище нескольких профилей пользователей.

    Каталог хранилища содержит индекс `users.json` (список пользователей и активный)
    и отдельный файл прогресса `profiles/<user_id>.json` на каждого пользователя.
    Повреждённые данные не приводят к падению: индекс восстанавливается профилем
    по умолчанию, а битый файл пользователя читается как чистый прогресс.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        legacy_profile_path: str | Path | None = None,
        migrate_legacy: bool = True,
    ) -> None:
        self.root = Path(root) if root is not None else DEFAULT_STORE_ROOT
        self.legacy_profile_path = (
            Path(legacy_profile_path)
            if legacy_profile_path is not None
            else DEFAULT_LEGACY_PROFILE_PATH
        )
        self.migrate_legacy = migrate_legacy
        self.index_path = self.root / "users.json"
        self.profiles_dir = self.root / "profiles"

        self._records: list[UserRecord] = []
        self._active_id: str = ""
        self._active_profile: PlayerProfile | None = None
        self._ensure_index()

    # ------------------------------------------------------------------ paths

    def _profile_path(self, user_id: str) -> Path:
        return self.profiles_dir / f"{user_id}.json"

    # ------------------------------------------------------------------ index

    def _load_index(self) -> tuple[list[UserRecord], str | None]:
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
            items = raw.get("users") or []
            seen: set[str] = set()
            records: list[UserRecord] = []
            for item in items:
                user_id = str(item["id"])
                if not user_id or user_id in seen:
                    continue
                seen.add(user_id)
                records.append(
                    UserRecord(
                        id=user_id,
                        name=str(item.get("name") or user_id),
                        created_at=str(item.get("created_at") or ""),
                        updated_at=str(item.get("updated_at") or ""),
                    )
                )
            active_raw = raw.get("active_user_id")
            active = str(active_raw) if active_raw else None
            return records, active
        except Exception:
            return [], None

    def _ensure_index(self) -> None:
        records, active = self._load_index()
        if not records:
            now = _now_iso()
            record = UserRecord(
                id=self._unique_id("user", set()),
                name=DEFAULT_USER_NAME,
                created_at=now,
                updated_at=now,
            )
            records = [record]
            active = record.id
            if (
                self.migrate_legacy
                and self.legacy_profile_path is not None
                and self.legacy_profile_path.exists()
            ):
                # Переносим прогресс из одиночного профиля, не трогая исходный файл.
                self._write_profile(record.id, PlayerProfile.load(self.legacy_profile_path))
            elif not self._profile_path(record.id).exists():
                # Не перезаписываем уцелевший файл прогресса, если индекс был повреждён.
                self._write_profile(record.id, PlayerProfile())
            self._records = records
            self._active_id = record.id
            self._write_index()
            return

        known_ids = {r.id for r in records}
        if active not in known_ids:
            active = records[0].id
        self._records = records
        self._active_id = active

    def _write_index(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "active_user_id": self._active_id,
            "users": [record.to_dict() for record in self._records],
        }
        self.index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_profile(self, user_id: str, profile: PlayerProfile) -> None:
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        profile.save(self._profile_path(user_id))

    def _read_profile(self, user_id: str) -> PlayerProfile:
        # PlayerProfile.load устойчив к повреждённым файлам и возвращает чистый профиль.
        return PlayerProfile.load(self._profile_path(user_id))

    def _unique_id(self, base: str, existing: set[str] | None = None) -> str:
        taken = existing if existing is not None else {r.id for r in self._records}
        base = base or "user"
        candidate = base
        counter = 2
        while candidate in taken:
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    def _touch(self, user_id: str) -> None:
        now = _now_iso()
        self._records = [
            UserRecord(
                id=record.id,
                name=record.name,
                created_at=record.created_at,
                updated_at=now if record.id == user_id else record.updated_at,
            )
            for record in self._records
        ]
        self._write_index()

    def _persist_current(self) -> None:
        if self._active_profile is not None and self._active_id:
            self._write_profile(self._active_id, self._active_profile)

    # ------------------------------------------------------------------ reads

    def users(self) -> list[UserRecord]:
        return list(self._records)

    def active_user(self) -> UserRecord:
        for record in self._records:
            if record.id == self._active_id:
                return record
        return self._records[0]

    def active_profile(self) -> PlayerProfile:
        if self._active_profile is None:
            self._active_profile = self._read_profile(self.active_user().id)
        return self._active_profile

    def can_delete_user(self, user_id: str) -> bool:
        ids = {r.id for r in self._records}
        return user_id in ids and len(self._records) > 1

    # ------------------------------------------------------------- mutations

    def create_user(self, name: str) -> UserRecord:
        clean = " ".join(str(name).split())[:MAX_NAME_LENGTH]
        if not clean:
            raise ValueError("Имя пользователя не может быть пустым")

        self._persist_current()
        now = _now_iso()
        record = UserRecord(
            id=self._unique_id(slugify(clean)),
            name=clean,
            created_at=now,
            updated_at=now,
        )
        self._records.append(record)
        self._active_id = record.id
        # Новый пользователь всегда начинает обучение с чистого прогресса.
        self._active_profile = PlayerProfile()
        self._write_index()
        self._write_profile(record.id, self._active_profile)
        return record

    def switch_user(self, user_id: str) -> bool:
        if user_id not in {r.id for r in self._records}:
            return False
        if user_id == self._active_id:
            return True
        self._persist_current()
        self._active_id = user_id
        self._active_profile = self._read_profile(user_id)
        self._write_index()
        return True

    def delete_user(self, user_id: str) -> bool:
        if not self.can_delete_user(user_id):
            return False

        was_active = user_id == self._active_id
        self._records = [r for r in self._records if r.id != user_id]
        try:
            self._profile_path(user_id).unlink()
        except OSError:
            pass

        if was_active:
            self._active_id = self._records[0].id
            self._active_profile = None
        self._write_index()
        return True

    def save_active(self, profile: PlayerProfile) -> None:
        record = self.active_user()
        self._write_profile(record.id, profile)
        self._touch(record.id)
        self._active_profile = profile
