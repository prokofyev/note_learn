import json
from pathlib import Path

import pytest

from note_learn.curriculum import ExerciseType, PlayerProfile
from note_learn.profile_store import ProfileStore, slugify


def _make_store(tmp_path: Path, *, with_legacy: bool = False) -> ProfileStore:
    legacy = tmp_path / "legacy_profile.json"
    if with_legacy:
        legacy_profile = PlayerProfile(
            stars=16,
            xp=229,
            current_streak=7,
            best_streak=7,
            max_unlocked_stage_idx=2,
        )
        legacy_profile.record_answer("C4", True, ExerciseType.INTRO)
        legacy_profile.save(legacy)
    return ProfileStore(root=tmp_path / "store", legacy_profile_path=legacy)


def test_creates_default_user_with_clean_progress(tmp_path: Path):
    store = _make_store(tmp_path)
    users = store.users()
    assert len(users) == 1
    assert store.active_user().id == users[0].id
    assert store.active_profile().stars == 0
    assert (store.root / "users.json").exists()
    assert (store.profiles_dir / f"{users[0].id}.json").exists()


def test_store_index_structure_matches_design(tmp_path: Path):
    store = _make_store(tmp_path)
    raw = json.loads((store.root / "users.json").read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert raw["active_user_id"] == store.active_user().id
    assert {"id", "name", "created_at", "updated_at"} <= set(raw["users"][0])


def test_duplicate_names_get_distinct_ids_and_independent_progress(tmp_path: Path):
    store = _make_store(tmp_path)

    first = store.create_user("Маша")
    first_profile = store.active_profile()
    first_profile.record_answer("C4", True, ExerciseType.INTRO)
    first_profile.record_answer("C4", True, ExerciseType.STAFF_TO_VALVES)
    store.save_active(first_profile)
    first_stars = store.active_profile().stars

    second = store.create_user("Маша")
    assert second.id != first.id
    assert store.active_user().id == second.id
    # Новый пользователь начинает с чистого прогресса, несмотря на совпадение имени.
    assert store.active_profile().stars == 0
    assert store.active_profile().xp == 0

    assert {u.name for u in store.users()} == {"Ученик", "Маша"}
    assert len({u.id for u in store.users()}) == len(store.users())

    store.switch_user(first.id)
    assert store.active_profile().stars == first_stars


def test_switch_user_preserves_both_progresses(tmp_path: Path):
    store = _make_store(tmp_path)
    a = store.active_user().id

    profile_a = store.active_profile()
    for _ in range(4):
        profile_a.record_answer("C4", True, ExerciseType.STAFF_TO_VALVES)
    store.save_active(profile_a)
    a_stars, a_mastery = profile_a.stars, profile_a.note_progress["C4"].mastery

    b = store.create_user("Борис")
    profile_b = store.active_profile()
    for _ in range(2):
        profile_b.record_answer("D4", True, ExerciseType.INTRO)
    store.save_active(profile_b)
    b_stars = profile_b.stars

    assert store.switch_user(a)
    restored_a = store.active_profile()
    assert restored_a.stars == a_stars
    assert restored_a.note_progress["C4"].mastery == pytest.approx(a_mastery)
    assert restored_a.note_progress["D4"].mastery == 0.0

    assert store.switch_user(b.id)
    restored_b = store.active_profile()
    assert restored_b.stars == b_stars
    assert restored_b.note_progress["C4"].mastery == 0.0


def test_active_user_persists_across_reopen(tmp_path: Path):
    store = _make_store(tmp_path)
    default_id = store.active_user().id
    other = store.create_user("Петя")

    reopened = ProfileStore(root=store.root, legacy_profile_path=tmp_path / "legacy_profile.json")
    assert reopened.active_user().id == other.id

    reopened.switch_user(default_id)
    reopened_again = ProfileStore(
        root=store.root, legacy_profile_path=tmp_path / "legacy_profile.json"
    )
    assert reopened_again.active_user().id == default_id


def test_delete_user_removes_only_that_profile(tmp_path: Path):
    store = _make_store(tmp_path)
    keep_id = store.active_user().id
    keep_profile = store.active_profile()
    keep_profile.record_answer("C4", True, ExerciseType.INTRO)
    store.save_active(keep_profile)
    keep_stars = keep_profile.stars

    doomed = store.create_user("Временный")
    doomed_file = store.profiles_dir / f"{doomed.id}.json"
    assert doomed_file.exists()

    assert store.delete_user(doomed.id)
    assert doomed.id not in {u.id for u in store.users()}
    assert not doomed_file.exists()

    store.switch_user(keep_id)
    assert store.active_profile().stars == keep_stars


def test_delete_active_user_switches_to_remaining(tmp_path: Path):
    store = _make_store(tmp_path)
    first_id = store.active_user().id
    second = store.create_user("Второй")

    assert store.delete_user(second.id)
    assert store.active_user().id == first_id


def test_cannot_delete_last_user(tmp_path: Path):
    store = _make_store(tmp_path)
    last_id = store.active_user().id
    assert store.can_delete_user(last_id) is False
    assert store.delete_user(last_id) is False
    assert [u.id for u in store.users()] == [last_id]


def test_create_user_rejects_empty_name(tmp_path: Path):
    store = _make_store(tmp_path)
    before = {u.id for u in store.users()}
    with pytest.raises(ValueError):
        store.create_user("   ")
    assert {u.id for u in store.users()} == before


def test_legacy_profile_migration_keeps_original_file(tmp_path: Path):
    legacy = tmp_path / "legacy_profile.json"
    source = PlayerProfile(stars=16, xp=229, current_streak=7, max_unlocked_stage_idx=2)
    for _ in range(3):
        source.record_answer("C4", True, ExerciseType.STAFF_TO_VALVES)
    source.save(legacy)
    legacy_text = legacy.read_text(encoding="utf-8")

    store = ProfileStore(root=tmp_path / "store", legacy_profile_path=legacy)
    migrated = store.active_profile()

    assert migrated.stars == source.stars
    assert migrated.xp == source.xp
    assert migrated.current_streak == source.current_streak
    assert migrated.max_unlocked_stage_idx == source.max_unlocked_stage_idx
    assert migrated.note_progress["C4"].mastery == pytest.approx(
        source.note_progress["C4"].mastery
    )
    # Исходный одиночный файл не изменяется и не удаляется.
    assert legacy.exists()
    assert legacy.read_text(encoding="utf-8") == legacy_text


def test_first_run_without_legacy_creates_single_default_user(tmp_path: Path):
    store = ProfileStore(root=tmp_path / "store", legacy_profile_path=tmp_path / "missing.json")
    assert len(store.users()) == 1
    assert store.active_profile().stars == 0


def test_damaged_index_falls_back_to_default_user(tmp_path: Path):
    root = tmp_path / "store"
    root.mkdir(parents=True)
    (root / "users.json").write_text("{ this is not json", encoding="utf-8")

    store = ProfileStore(root=root, legacy_profile_path=tmp_path / "missing.json")
    assert len(store.users()) == 1
    assert store.active_profile().stars == 0


def test_damaged_user_file_keeps_other_users_available(tmp_path: Path):
    store = _make_store(tmp_path)
    keep_id = store.active_user().id

    broken = store.create_user("Сломанный")
    (store.profiles_dir / f"{broken.id}.json").write_text("{{{ corrupted", encoding="utf-8")

    assert store.switch_user(broken.id)
    assert store.active_profile().stars == 0
    assert {u.id for u in store.users()} == {keep_id, broken.id}

    assert store.switch_user(keep_id)
    assert store.active_profile() is not None


def test_slugify_transliterates_and_sanitizes():
    assert slugify("Маша") == "masha"
    assert slugify("Пётр") == "petr"
    assert slugify("Alex 2") == "alex-2"
    assert slugify("!!!") == ""
