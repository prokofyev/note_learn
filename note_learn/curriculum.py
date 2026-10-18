from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import random
from typing import Any

from note_learn.model import (
    NOTES_BY_ID,
    NoteDuration,
    TrumpetNote,
    get_note,
)


class ExerciseType(str, Enum):
    INTRO = "intro"
    STAFF_TO_NAME = "staff_to_name"
    STAFF_TO_VALVES = "staff_to_valves"
    EAR_TO_NOTE = "ear_to_note"
    PLAY_TRUMPET = "play_trumpet"

    @property
    def title_ru(self) -> str:
        titles = {
            ExerciseType.INTRO: "Знакомство с новой нотой",
            ExerciseType.STAFF_TO_NAME: "Угадай ноту на нотном стане",
            ExerciseType.STAFF_TO_VALVES: "Зажми правильные помпы",
            ExerciseType.EAR_TO_NOTE: "Угадай ноту на слух",
            ExerciseType.PLAY_TRUMPET: "Сыграй на своей трубе!",
        }
        return titles[self]


@dataclass(frozen=True)
class CurriculumStage:
    index: int
    title: str
    subtitle: str
    note_ids: tuple[str, ...]
    durations: tuple[NoteDuration, ...]
    initial_unlocked_count: int = 2


CURRICULUM_STAGES: tuple[CurriculumStage, ...] = (
    CurriculumStage(
        index=0,
        title="Этап 1. Первые шаги",
        subtitle="До, Ре, Ми, Фа, Соль первой октавы",
        note_ids=("C4", "D4", "E4", "F4", "G4"),
        durations=(NoteDuration.WHOLE, NoteDuration.HALF),
        initial_unlocked_count=3,
    ),
    CurriculumStage(
        index=1,
        title="Этап 2. Вся первая октава",
        subtitle="Добавляем Ля, Си и До второй октавы + четверти",
        note_ids=("A4", "B4", "C5"),
        durations=(NoteDuration.WHOLE, NoteDuration.HALF, NoteDuration.QUARTER),
        initial_unlocked_count=2,
    ),
    CurriculumStage(
        index=2,
        title="Этап 3. Первые знаки: диез, бемоль, бекар",
        subtitle="Си-бемоль, Фа-диез, Ми-бемоль, До-диез и Си-бекар",
        note_ids=("Bb4", "Fs4", "Eb4", "Cs4", "B4_nat"),
        durations=(NoteDuration.HALF, NoteDuration.QUARTER),
        initial_unlocked_count=2,
    ),
    CurriculumStage(
        index=3,
        title="Этап 4. Хроматика первой октавы",
        subtitle="Все полутона и энгармонические братья-близнецы",
        note_ids=("Db4", "Ds4", "Gs4", "Ab4", "As4"),
        durations=(NoteDuration.HALF, NoteDuration.QUARTER),
        initial_unlocked_count=2,
    ),
    CurriculumStage(
        index=4,
        title="Этап 5. Поход во вторую октаву",
        subtitle="Ре, Ми-бемоль, Ми, Фа, Фа-диез и Соль второй октавы",
        note_ids=("D5", "Eb5", "E5", "F5", "Fs5", "G5"),
        durations=(NoteDuration.WHOLE, NoteDuration.HALF, NoteDuration.QUARTER),
        initial_unlocked_count=2,
    ),
    CurriculumStage(
        index=5,
        title="Этап 6. Виртуоз верхнего регистра",
        subtitle="Ля-бемоль, Ля, Си-бемоль, Си и королевское До третьей октавы!",
        note_ids=("Ab5", "A5", "Bb5", "B5", "C6"),
        durations=(NoteDuration.WHOLE, NoteDuration.HALF, NoteDuration.QUARTER),
        initial_unlocked_count=2,
    ),
)


@dataclass
class NoteProgress:
    note_id: str
    unlocked: bool = False
    seen_intro: bool = False
    mastery: float = 0.0  # 0.0 .. 1.0
    attempts: int = 0
    correct: int = 0
    error_count: int = 0
    streak: int = 0
    last_practiced_step: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "note_id": self.note_id,
            "unlocked": self.unlocked,
            "seen_intro": self.seen_intro,
            "mastery": round(self.mastery, 4),
            "attempts": self.attempts,
            "correct": self.correct,
            "error_count": self.error_count,
            "streak": self.streak,
            "last_practiced_step": self.last_practiced_step,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NoteProgress:
        return cls(
            note_id=str(data["note_id"]),
            unlocked=bool(data.get("unlocked", False)),
            seen_intro=bool(data.get("seen_intro", False)),
            mastery=float(data.get("mastery", 0.0)),
            attempts=int(data.get("attempts", 0)),
            correct=int(data.get("correct", 0)),
            error_count=int(data.get("error_count", 0)),
            streak=int(data.get("streak", 0)),
            last_practiced_step=int(data.get("last_practiced_step", 0)),
        )


@dataclass(frozen=True)
class Exercise:
    exercise_type: ExerciseType
    target_note: TrumpetNote
    duration: NoteDuration
    options: tuple[TrumpetNote, ...] = ()
    is_review: bool = False


@dataclass
class PlayerProfile:
    stars: int = 0
    xp: int = 0
    current_streak: int = 0
    best_streak: int = 0
    current_stage_idx: int = 0
    max_unlocked_stage_idx: int = 0
    with_trumpet: bool = False
    step_counter: int = 0
    note_progress: dict[str, NoteProgress] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        for stage in CURRICULUM_STAGES:
            for idx, note_id in enumerate(stage.note_ids):
                if note_id not in self.note_progress:
                    unlocked = stage.index == 0 and idx < stage.initial_unlocked_count
                    self.note_progress[note_id] = NoteProgress(
                        note_id=note_id,
                        unlocked=unlocked,
                    )
        # Гарантируем, что на каждом уже открытом этапе открыто хотя бы initial_unlocked_count нот
        for stage_idx in range(self.max_unlocked_stage_idx + 1):
            stage = CURRICULUM_STAGES[stage_idx]
            for note_id in stage.note_ids[: stage.initial_unlocked_count]:
                self.note_progress[note_id].unlocked = True

    def unlocked_notes_for_stage(self, stage_idx: int) -> list[TrumpetNote]:
        stage = CURRICULUM_STAGES[stage_idx]
        result = [
            get_note(nid)
            for nid in stage.note_ids
            if self.note_progress[nid].unlocked
        ]
        if not result:
            first_id = stage.note_ids[0]
            self.note_progress[first_id].unlocked = True
            result.append(get_note(first_id))
        return result

    def all_unlocked_notes(self) -> list[TrumpetNote]:
        result: list[TrumpetNote] = []
        for stage in CURRICULUM_STAGES:
            for nid in stage.note_ids:
                if self.note_progress[nid].unlocked:
                    result.append(get_note(nid))
        return result

    def stage_mastery(self, stage_idx: int) -> float:
        stage = CURRICULUM_STAGES[stage_idx]
        values = [self.note_progress[nid].mastery for nid in stage.note_ids]
        return sum(values) / len(values) if values else 0.0

    def record_answer(
        self,
        note_id: str,
        is_correct: bool,
        exercise_type: ExerciseType | None = None,
    ) -> dict[str, Any]:
        """
        Обновляет прогресс ученика после ответа и проверяет открытие новых нот и этапов.
        Возвращает словарь с событиями ('newly_unlocked_notes', 'newly_unlocked_stage', 'stars_earned').
        """
        self.step_counter += 1
        prog = self.note_progress[note_id]
        prog.unlocked = True
        prog.last_practiced_step = self.step_counter

        if exercise_type is ExerciseType.INTRO:
            prog.seen_intro = True
            prog.mastery = max(prog.mastery, 0.25)
            self.xp += 10
            self.stars += 1
            return {
                "newly_unlocked_notes": [],
                "newly_unlocked_stage": None,
                "stars_earned": 1,
            }

        prog.attempts += 1
        prog.seen_intro = True
        stars_earned = 0

        if is_correct:
            prog.correct += 1
            prog.streak += 1
            self.current_streak += 1
            self.best_streak = max(self.best_streak, self.current_streak)
            gain = 0.24 if exercise_type is ExerciseType.PLAY_TRUMPET else 0.18
            if prog.streak >= 3:
                gain += 0.05
            prog.mastery = min(1.0, prog.mastery + gain)
            stars_earned = 2 if self.current_streak >= 3 else 1
            self.stars += stars_earned
            self.xp += 15 + min(25, self.current_streak * 3)
        else:
            prog.error_count += 1
            prog.streak = 0
            self.current_streak = 0
            prog.mastery = max(0.05, prog.mastery - 0.15)

        newly_unlocked_notes = self._check_progression()
        return {
            "newly_unlocked_notes": newly_unlocked_notes,
            "newly_unlocked_stage": self._check_stage_unlock(),
            "stars_earned": stars_earned,
        }

    def _check_progression(self) -> list[str]:
        """Если открытые ноты текущего этапа освоены >= 0.55, открываем следующую ноту этапа."""
        stage = CURRICULUM_STAGES[self.current_stage_idx]
        unlocked_progs = [
            self.note_progress[nid]
            for nid in stage.note_ids
            if self.note_progress[nid].unlocked
        ]
        if not unlocked_progs:
            return []

        avg_unlocked = sum(p.mastery for p in unlocked_progs) / len(unlocked_progs)
        min_unlocked = min(p.mastery for p in unlocked_progs)
        newly_unlocked: list[str] = []

        if avg_unlocked >= 0.55 and min_unlocked >= 0.35:
            for nid in stage.note_ids:
                if not self.note_progress[nid].unlocked:
                    self.note_progress[nid].unlocked = True
                    newly_unlocked.append(nid)
                    break
        return newly_unlocked

    def _check_stage_unlock(self) -> int | None:
        """Если все ноты текущего этапа открыты и среднее мастерство >= 0.68, открываем следующий этап."""
        stage = CURRICULUM_STAGES[self.current_stage_idx]
        all_unlocked = all(self.note_progress[nid].unlocked for nid in stage.note_ids)
        if (
            all_unlocked
            and self.stage_mastery(self.current_stage_idx) >= 0.68
            and self.current_stage_idx == self.max_unlocked_stage_idx
            and self.max_unlocked_stage_idx + 1 < len(CURRICULUM_STAGES)
        ):
            self.max_unlocked_stage_idx += 1
            next_stage = CURRICULUM_STAGES[self.max_unlocked_stage_idx]
            for nid in next_stage.note_ids[: next_stage.initial_unlocked_count]:
                self.note_progress[nid].unlocked = True
            return self.max_unlocked_stage_idx
        return None

    def unlock_stage_manually(self, stage_idx: int) -> None:
        """Позволяет родителю или ученику переключиться на любой этап при необходимости."""
        stage_idx = max(0, min(len(CURRICULUM_STAGES) - 1, stage_idx))
        self.max_unlocked_stage_idx = max(self.max_unlocked_stage_idx, stage_idx)
        self.current_stage_idx = stage_idx
        stage = CURRICULUM_STAGES[stage_idx]
        for nid in stage.note_ids[: stage.initial_unlocked_count]:
            self.note_progress[nid].unlocked = True

    def save(self, path: str | Path) -> None:
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "stars": self.stars,
            "xp": self.xp,
            "current_streak": self.current_streak,
            "best_streak": self.best_streak,
            "current_stage_idx": self.current_stage_idx,
            "max_unlocked_stage_idx": self.max_unlocked_stage_idx,
            "with_trumpet": self.with_trumpet,
            "step_counter": self.step_counter,
            "note_progress": {
                nid: prog.to_dict() for nid, prog in self.note_progress.items()
            },
        }
        file_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> PlayerProfile:
        file_path = Path(path)
        if not file_path.exists():
            return cls()
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8"))
            note_progress = {
                nid: NoteProgress.from_dict(pdata)
                for nid, pdata in raw.get("note_progress", {}).items()
                if nid in NOTES_BY_ID
            }
            return cls(
                stars=int(raw.get("stars", 0)),
                xp=int(raw.get("xp", 0)),
                current_streak=int(raw.get("current_streak", 0)),
                best_streak=int(raw.get("best_streak", 0)),
                current_stage_idx=int(raw.get("current_stage_idx", 0)),
                max_unlocked_stage_idx=int(raw.get("max_unlocked_stage_idx", 0)),
                with_trumpet=bool(raw.get("with_trumpet", False)),
                step_counter=int(raw.get("step_counter", 0)),
                note_progress=note_progress,
            )
        except Exception:
            return cls()


class CurriculumEngine:
    def __init__(self, profile: PlayerProfile, rng: random.Random | None = None) -> None:
        self.profile = profile
        self.rng = rng or random.Random()

    def _review_pool(self, current_stage_idx: int) -> list[TrumpetNote]:
        """Пул ранее изученных нот из предыдущих этапов или хорошо освоенных нот для закрепления."""
        stage_note_ids = set(CURRICULUM_STAGES[current_stage_idx].note_ids)
        pool: list[TrumpetNote] = []
        for s_idx in range(current_stage_idx):
            for nid in CURRICULUM_STAGES[s_idx].note_ids:
                if self.profile.note_progress[nid].unlocked:
                    pool.append(get_note(nid))
        # Также добавляем уже хорошо изученные ноты текущего этапа (mastery >= 0.75), если открыто > 2 нот
        current_unlocked = self.profile.unlocked_notes_for_stage(current_stage_idx)
        if len(current_unlocked) > 2:
            for note in current_unlocked:
                prog = self.profile.note_progress[note.id]
                if prog.mastery >= 0.75 and note not in pool:
                    pool.append(note)
        return pool

    def _pick_weighted_current_note(self, notes: list[TrumpetNote]) -> TrumpetNote:
        weights: list[float] = []
        for note in notes:
            prog = self.profile.note_progress[note.id]
            # Новые и сложные ноты получают больший вес
            w = max(0.15, 1.35 - prog.mastery) + 0.25 * prog.error_count
            weights.append(w)
        return self.rng.choices(notes, weights=weights, k=1)[0]

    def _pick_weighted_review_note(self, review_notes: list[TrumpetNote]) -> TrumpetNote:
        weights: list[float] = []
        for note in review_notes:
            prog = self.profile.note_progress[note.id]
            steps_ago = max(1, self.profile.step_counter - prog.last_practiced_step)
            w = 1.0 + 0.5 * prog.error_count + min(3.0, steps_ago * 0.15) + (1.0 - prog.mastery)
            weights.append(w)
        return self.rng.choices(review_notes, weights=weights, k=1)[0]

    def _build_distractor_options(
        self,
        target: TrumpetNote,
        count: int = 4,
    ) -> tuple[TrumpetNote, ...]:
        unlocked = self.profile.all_unlocked_notes()
        candidates = [n for n in unlocked if n.id != target.id and n.full_name != target.full_name]
        if len(candidates) < count - 1:
            for stage in CURRICULUM_STAGES:
                for nid in stage.note_ids:
                    n = get_note(nid)
                    if n.id != target.id and n not in candidates and n.full_name != target.full_name:
                        candidates.append(n)
                    if len(candidates) >= count - 1:
                        break
                if len(candidates) >= count - 1:
                    break
        chosen = self.rng.sample(candidates, k=min(count - 1, len(candidates)))
        options = [target, *chosen]
        self.rng.shuffle(options)
        return tuple(options)

    def next_exercise(
        self,
        stage_idx: int | None = None,
        forced_type: ExerciseType | None = None,
    ) -> Exercise:
        s_idx = self.profile.current_stage_idx if stage_idx is None else stage_idx
        stage = CURRICULUM_STAGES[s_idx]
        current_notes = self.profile.unlocked_notes_for_stage(s_idx)

        # 1. Проверяем, есть ли открытая нота, с которой ученик ещё не познакомился (INTRO)
        if forced_type is None:
            for note in current_notes:
                if not self.profile.note_progress[note.id].seen_intro:
                    return Exercise(
                        exercise_type=ExerciseType.INTRO,
                        target_note=note,
                        duration=stage.durations[0],
                        options=(),
                        is_review=False,
                    )

        # 2. Выбираем целевую ноту: ~70% текущие ноты этапа, ~30% интервальное повторение (Spaced Repetition)
        review_pool = self._review_pool(s_idx)
        is_review = False
        if review_pool and self.rng.random() < 0.30:
            target = self._pick_weighted_review_note(review_pool)
            is_review = True
        else:
            target = self._pick_weighted_current_note(current_notes)

        duration = self.rng.choice(stage.durations)

        # 3. Выбираем тип задания с учётом режима "С трубой / Без трубы"
        if forced_type is not None:
            ex_type = forced_type
        else:
            available_types = [
                ExerciseType.STAFF_TO_NAME,
                ExerciseType.STAFF_TO_VALVES,
                ExerciseType.EAR_TO_NOTE,
            ]
            if self.profile.with_trumpet:
                available_types.append(ExerciseType.PLAY_TRUMPET)
            ex_type = self.rng.choice(available_types)

        options: tuple[TrumpetNote, ...] = ()
        if ex_type in (ExerciseType.STAFF_TO_NAME, ExerciseType.EAR_TO_NOTE):
            options = self._build_distractor_options(target, count=4)

        return Exercise(
            exercise_type=ex_type,
            target_note=target,
            duration=duration,
            options=options,
            is_review=is_review,
        )

    def generate_round(self, length: int = 8, stage_idx: int | None = None) -> list[Exercise]:
        return [self.next_exercise(stage_idx=stage_idx) for _ in range(length)]
