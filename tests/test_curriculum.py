import random
from pathlib import Path

from note_learn.curriculum import (
    CURRICULUM_STAGES,
    CurriculumEngine,
    ExerciseType,
    PlayerProfile,
)


def test_initial_profile_and_intro_cards():
    profile = PlayerProfile()
    engine = CurriculumEngine(profile, rng=random.Random(42))

    unlocked = profile.unlocked_notes_for_stage(0)
    assert [n.id for n in unlocked] == ["C4", "D4", "E4"]

    # Первое задание для новой ноты должно быть карточкой знакомства (INTRO)
    ex1 = engine.next_exercise()
    assert ex1.exercise_type is ExerciseType.INTRO
    assert ex1.target_note.id == "C4"

    profile.record_answer("C4", is_correct=True, exercise_type=ExerciseType.INTRO)
    ex2 = engine.next_exercise()
    assert ex2.exercise_type is ExerciseType.INTRO
    assert ex2.target_note.id == "D4"


def test_progression_unlocks_new_note_and_stage():
    profile = PlayerProfile()
    # Отмечаем карточки знакомства
    for nid in ("C4", "D4", "E4"):
        profile.record_answer(nid, True, ExerciseType.INTRO)

    # Повышаем мастерство по открытым нотам C4, D4, E4
    for _ in range(3):
        for nid in ("C4", "D4", "E4"):
            profile.record_answer(nid, True, ExerciseType.STAFF_TO_VALVES)

    # Должна открыться следующая нота этапа 1 — F4 (Фа первой октавы)
    assert profile.note_progress["F4"].unlocked is True

    # Осваиваем оставшиеся ноты первого этапа (F4 и G4)
    for _ in range(4):
        for nid in CURRICULUM_STAGES[0].note_ids:
            profile.record_answer(nid, True, ExerciseType.STAFF_TO_NAME)

    assert profile.max_unlocked_stage_idx >= 1


def test_with_and_without_trumpet_modes():
    profile = PlayerProfile(with_trumpet=False)
    for nid in ("C4", "D4", "E4"):
        profile.record_answer(nid, True, ExerciseType.INTRO)

    engine = CurriculumEngine(profile, rng=random.Random(7))
    exercises_no_mic = [engine.next_exercise() for _ in range(30)]
    assert all(ex.exercise_type is not ExerciseType.PLAY_TRUMPET for ex in exercises_no_mic)

    profile.with_trumpet = True
    exercises_with_mic = [engine.next_exercise() for _ in range(40)]
    assert any(ex.exercise_type is ExerciseType.PLAY_TRUMPET for ex in exercises_with_mic)


def test_spaced_repetition_mixes_review_notes():
    profile = PlayerProfile()
    profile.unlock_stage_manually(1)  # Переходим на Этап 2 (A4, B4, C5)
    # Отмечаем все открытые ноты этапов 0 и 1 как просмотренные в INTRO
    for stage_idx in (0, 1):
        for note in profile.unlocked_notes_for_stage(stage_idx):
            profile.record_answer(note.id, True, ExerciseType.INTRO)

    # Добавим ошибки на простой ноте D4 из первого этапа
    profile.record_answer("D4", False, ExerciseType.STAFF_TO_VALVES)
    profile.record_answer("D4", False, ExerciseType.STAFF_TO_VALVES)

    engine = CurriculumEngine(profile, rng=random.Random(123))
    samples = [engine.next_exercise(stage_idx=1) for _ in range(100)]
    review_count = sum(1 for ex in samples if ex.is_review)
    assert 15 <= review_count <= 45
    assert any(ex.target_note.id in ("C4", "D4", "E4") for ex in samples)


def test_profile_save_and_load(tmp_path: Path):
    save_file = tmp_path / "profile.json"
    profile = PlayerProfile(stars=25, xp=340, current_streak=4, best_streak=7, with_trumpet=True)
    profile.record_answer("C4", True, ExerciseType.STAFF_TO_VALVES)
    profile.save(save_file)

    loaded = PlayerProfile.load(save_file)
    assert loaded.stars == profile.stars
    assert loaded.xp == profile.xp
    assert loaded.best_streak == 7
    assert loaded.with_trumpet is True
    assert loaded.note_progress["C4"].mastery == profile.note_progress["C4"].mastery


def test_player_profile_load_is_resilient_and_path_signature_unchanged(tmp_path: Path):
    # Отсутствующий файл возвращает чистый профиль (контракт, на который опирается ProfileStore).
    missing = PlayerProfile.load(tmp_path / "nope.json")
    assert isinstance(missing, PlayerProfile)
    assert missing.stars == 0

    # Повреждённый файл не приводит к исключению.
    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    assert PlayerProfile.load(broken).stars == 0

    # save принимает str и Path и создаёт родительские каталоги.
    for target in (tmp_path / "a" / "b" / "p.json", str(tmp_path / "c" / "p.json")):
        profile = PlayerProfile(stars=3)
        profile.save(target)
        assert Path(target).exists()
        assert PlayerProfile.load(target).stars == 3
