from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


class Accidental(str, Enum):
    NONE = "none"
    SHARP = "sharp"
    FLAT = "flat"
    NATURAL = "natural"

    @property
    def symbol(self) -> str:
        if self is Accidental.SHARP:
            return "#"
        if self is Accidental.FLAT:
            return "b"
        if self is Accidental.NATURAL:
            return "(бек.)"
        return ""

    @property
    def russian_name(self) -> str:
        if self is Accidental.SHARP:
            return "диез"
        if self is Accidental.FLAT:
            return "бемоль"
        if self is Accidental.NATURAL:
            return "бекар"
        return ""

    @property
    def asset_filename(self) -> str | None:
        if self is Accidental.SHARP:
            return "accidental_sharp.png"
        if self is Accidental.FLAT:
            return "accidental_flat.png"
        if self is Accidental.NATURAL:
            return "accidental_natural.png"
        return None


class NoteDuration(str, Enum):
    WHOLE = "whole"
    HALF = "half"
    QUARTER = "quarter"

    @property
    def beats(self) -> int:
        if self is NoteDuration.WHOLE:
            return 4
        if self is NoteDuration.HALF:
            return 2
        return 1

    @property
    def russian_name(self) -> str:
        if self is NoteDuration.WHOLE:
            return "Целая (4 счёта)"
        if self is NoteDuration.HALF:
            return "Половинная (2 счёта)"
        return "Четвертная (1 счёт)"

    @property
    def short_russian(self) -> str:
        if self is NoteDuration.WHOLE:
            return "Целая"
        if self is NoteDuration.HALF:
            return "Половинная"
        return "Четверть"

    @property
    def is_filled_head(self) -> bool:
        return self is NoteDuration.QUARTER

    @property
    def has_stem(self) -> bool:
        return self is not NoteDuration.WHOLE

    def duration_seconds(self, bpm: float = 72.0) -> float:
        return (60.0 / bpm) * self.beats


RUSSIAN_STEPS: tuple[str, ...] = ("До", "Ре", "Ми", "Фа", "Соль", "Ля", "Си")
STEP_SEMITONES: tuple[int, ...] = (0, 2, 4, 5, 7, 9, 11)

OCTAVE_NAMES: dict[int, str] = {
    4: "первой октавы",
    5: "второй октавы",
    6: "третьей октавы",
}

OCTAVE_SHORT_SUFFIX: dict[int, str] = {
    4: "1",
    5: "2",
    6: "3",
}

# Канонические и альтернативные аппликатуры трёх вентилей для written MIDI 60..84
VALVE_TABLE: dict[int, tuple[tuple[int, int, int], tuple[tuple[int, int, int], ...]]] = {
    60: ((0, 0, 0), ()),
    61: ((1, 1, 1), ()),
    62: ((1, 0, 1), ()),
    63: ((0, 1, 1), ()),
    64: ((1, 1, 0), ((0, 0, 1),)),
    65: ((1, 0, 0), ()),
    66: ((0, 1, 0), ()),
    67: ((0, 0, 0), ((1, 0, 1),)),
    68: ((0, 1, 1), ()),
    69: ((1, 1, 0), ((0, 0, 1),)),
    70: ((1, 0, 0), ()),
    71: ((0, 1, 0), ()),
    72: ((0, 0, 0), ()),
    73: ((1, 1, 0), ((0, 0, 1),)),
    74: ((1, 0, 0), ((1, 0, 1),)),
    75: ((0, 1, 0), ((0, 1, 1),)),
    76: ((0, 0, 0), ((1, 1, 0),)),
    77: ((1, 0, 0), ()),
    78: ((0, 1, 0), ()),
    79: ((0, 0, 0), ()),
    80: ((0, 1, 1), ()),
    81: ((1, 1, 0), ((0, 0, 1),)),
    82: ((1, 0, 0), ()),
    83: ((0, 1, 0), ()),
    84: ((0, 0, 0), ()),
}

# Номер гармоники (обертона) для подсказки ученику по зажатию губ (амбушюру)
HARMONIC_PARTIAL: dict[int, int] = {
    60: 2, 61: 2, 62: 2, 63: 2, 64: 2, 65: 2, 66: 2,
    67: 3, 68: 3, 69: 3, 70: 3, 71: 3,
    72: 4, 73: 4, 74: 4, 75: 4,
    76: 5, 77: 5, 78: 5,
    79: 6, 80: 6, 81: 6, 82: 6,
    83: 7, 84: 8,
}


def midi_to_freq(midi_note: float) -> float:
    """Конвертирует MIDI-ноту в частоту в Гц (A4 = 69 = 440 Гц)."""
    return 440.0 * (2.0 ** ((midi_note - 69.0) / 12.0))


def freq_to_midi(freq_hz: float) -> float:
    """Конвертирует частоту в Гц в дробное значение MIDI."""
    if freq_hz <= 0:
        raise ValueError("Frequency must be positive")
    return 69.0 + 12.0 * math.log2(freq_hz / 440.0)


def written_to_concert_midi(written_midi: int) -> int:
    """Труба в строе Си-бемоль (Bb) звучит на 2 полутона (1 тон) ниже написанного."""
    return written_midi - 2


def concert_to_written_midi(concert_midi: float) -> float:
    """Переводит реальную (концертную) высоту звука в написанную ноту для трубы Bb."""
    return concert_midi + 2.0


@dataclass(frozen=True)
class TrumpetNote:
    id: str
    written_midi: int
    step_index: int  # 0..6 (До..Си)
    octave: int      # 4 = 1-я октава, 5 = 2-я октава, 6 = 3-я октава
    accidental: Accidental = Accidental.NONE

    @property
    def russian_step(self) -> str:
        return RUSSIAN_STEPS[self.step_index]

    @property
    def accidental_symbol(self) -> str:
        return self.accidental.symbol

    @property
    def base_russian_name(self) -> str:
        """Имя ноты без октавы: 'До', 'Фа-диез', 'Си-бемоль'."""
        if self.accidental in (Accidental.SHARP, Accidental.FLAT, Accidental.NATURAL):
            return f"{self.russian_step}-{self.accidental.russian_name}"
        return self.russian_step

    @property
    def short_name(self) -> str:
        """Короткое имя для кнопок: 'До1', 'Фа♯1', 'Си♭1', 'До2'."""
        oct_suffix = OCTAVE_SHORT_SUFFIX.get(self.octave, str(self.octave))
        return f"{self.russian_step}{self.accidental.symbol}{oct_suffix}"

    @property
    def button_label(self) -> str:
        """Название на кнопке выбора ноты: 'До', 'Фа♯', 'Си♭'."""
        return f"{self.russian_step}{self.accidental.symbol}"

    @property
    def full_name(self) -> str:
        """Полное русское название: 'До первой октавы', 'Си-бемоль первой октавы'."""
        oct_name = OCTAVE_NAMES.get(self.octave, f"{self.octave}-й октавы")
        return f"{self.base_russian_name} {oct_name}"

    @property
    def staff_position(self) -> int:
        """
        Диатоническая позиция на нотном стане относительно До первой октавы (C4 = 0).
        Линейки нотного стана: 2 (Ми1), 4 (Соль1), 6 (Си1), 8 (Ре2), 10 (Фа2).
        Промежутки: 1 (Ре1), 3 (Фа1), 5 (Ля1), 7 (До2), 9 (Ми2), 11 (Соль2).
        Добавочные линейки: 0 (До1), 12 (Ля2), 14 (До3).
        """
        return (self.octave - 4) * 7 + self.step_index

    @property
    def stem_up(self) -> bool:
        """По правилам нотной графики: ниже 3-й линейки (Си1, pos=6) штиль вверх, иначе вниз."""
        return self.staff_position < 6

    @property
    def ledger_positions(self) -> tuple[int, ...]:
        """Возвращает список диатонических позиций добавочных линеек для данной ноты."""
        pos = self.staff_position
        if pos <= 0:
            return tuple(range(0, pos - 1, -2))
        if pos >= 12:
            return tuple(range(12, pos + 1, 2))
        return ()

    @property
    def valves(self) -> tuple[int, int, int]:
        """Каноническая аппликатура трёх помп (v1, v2, v3)."""
        return VALVE_TABLE[self.written_midi][0]

    @property
    def alt_valves(self) -> tuple[tuple[int, int, int], ...]:
        """Альтернативные допустимые аппликатуры."""
        return VALVE_TABLE[self.written_midi][1]

    def matches_valves(self, pressed: tuple[int, int, int], allow_alt: bool = True) -> bool:
        """Проверяет, подходит ли нажатая комбинация помп для этой ноты."""
        if pressed == self.valves:
            return True
        if allow_alt and pressed in self.alt_valves:
            return True
        return False

    @property
    def valves_display(self) -> str:
        """Человекочитаемое описание зажатых помп, например '1 + 3' или 'Открыто (0)'."""
        active = [str(i + 1) for i, v in enumerate(self.valves) if v]
        if not active:
            return "Открыто (0-0-0)"
        return " + ".join(active) + f" ({'-'.join(str(v) for v in self.valves)})"

    @property
    def concert_midi(self) -> int:
        return written_to_concert_midi(self.written_midi)

    @property
    def concert_freq_hz(self) -> float:
        """Реальная частота звучания трубы Си-бемоль в Гц."""
        return midi_to_freq(self.concert_midi)

    @property
    def written_freq_hz(self) -> float:
        """Частота исходного нетранспонированного сэмпла в Гц."""
        return midi_to_freq(self.written_midi)

    @property
    def sample_filename(self) -> str:
        return f"trumpet_{self.written_midi}.ogg"


def _build_catalog() -> tuple[dict[str, TrumpetNote], dict[int, TrumpetNote]]:
    notes_by_id: dict[str, TrumpetNote] = {}
    canonical_by_midi: dict[int, TrumpetNote] = {}

    specs: list[tuple[str, int, int, int, Accidental, bool]] = [
        # Первая октава (octave = 4)
        ("C4",  60, 0, 4, Accidental.NONE,  True),
        ("Cs4", 61, 0, 4, Accidental.SHARP, True),
        ("Db4", 61, 1, 4, Accidental.FLAT,  False),
        ("D4",  62, 1, 4, Accidental.NONE,  True),
        ("Eb4", 63, 2, 4, Accidental.FLAT,  True),
        ("Ds4", 63, 1, 4, Accidental.SHARP, False),
        ("E4",  64, 2, 4, Accidental.NONE,  True),
        ("F4",  65, 3, 4, Accidental.NONE,  True),
        ("Fs4", 66, 3, 4, Accidental.SHARP, True),
        ("Gb4", 66, 4, 4, Accidental.FLAT,  False),
        ("G4",  67, 4, 4, Accidental.NONE,  True),
        ("Gs4", 68, 4, 4, Accidental.SHARP, True),
        ("Ab4", 68, 5, 4, Accidental.FLAT,  False),
        ("A4",  69, 5, 4, Accidental.NONE,  True),
        ("Bb4", 70, 6, 4, Accidental.FLAT,  True),
        ("As4", 70, 5, 4, Accidental.SHARP, False),
        ("B4",  71, 6, 4, Accidental.NONE,  True),
        ("B4_nat", 71, 6, 4, Accidental.NATURAL, False),
        # Вторая октава (octave = 5)
        ("C5",  72, 0, 5, Accidental.NONE,  True),
        ("Cs5", 73, 0, 5, Accidental.SHARP, True),
        ("Db5", 73, 1, 5, Accidental.FLAT,  False),
        ("D5",  74, 1, 5, Accidental.NONE,  True),
        ("Eb5", 75, 2, 5, Accidental.FLAT,  True),
        ("Ds5", 75, 1, 5, Accidental.SHARP, False),
        ("E5",  76, 2, 5, Accidental.NONE,  True),
        ("F5",  77, 3, 5, Accidental.NONE,  True),
        ("Fs5", 78, 3, 5, Accidental.SHARP, True),
        ("Gb5", 78, 4, 5, Accidental.FLAT,  False),
        ("G5",  79, 4, 5, Accidental.NONE,  True),
        ("Ab5", 80, 5, 5, Accidental.FLAT,  True),
        ("Gs5", 80, 4, 5, Accidental.SHARP, False),
        ("A5",  81, 5, 5, Accidental.NONE,  True),
        ("Bb5", 82, 6, 5, Accidental.FLAT,  True),
        ("As5", 82, 5, 5, Accidental.SHARP, False),
        ("B5",  83, 6, 5, Accidental.NONE,  True),
        # Третья октава (octave = 6)
        ("C6",  84, 0, 6, Accidental.NONE,  True),
    ]

    for note_id, midi, step, octave, acc, is_canonical in specs:
        note = TrumpetNote(
            id=note_id,
            written_midi=midi,
            step_index=step,
            octave=octave,
            accidental=acc,
        )
        notes_by_id[note_id] = note
        if is_canonical:
            canonical_by_midi[midi] = note

    return notes_by_id, canonical_by_midi


NOTES_BY_ID, CANONICAL_NOTES_BY_MIDI = _build_catalog()


def get_note(note_id: str) -> TrumpetNote:
    return NOTES_BY_ID[note_id]


def get_canonical_note(written_midi: int) -> TrumpetNote:
    clamped = max(60, min(84, int(round(written_midi))))
    return CANONICAL_NOTES_BY_MIDI[clamped]
