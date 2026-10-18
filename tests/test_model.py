import math
import pytest

from note_learn.model import (
    Accidental,
    CANONICAL_NOTES_BY_MIDI,
    NOTES_BY_ID,
    NoteDuration,
    concert_to_written_midi,
    freq_to_midi,
    get_canonical_note,
    get_note,
    midi_to_freq,
    written_to_concert_midi,
)


def test_full_range_covered():
    assert set(CANONICAL_NOTES_BY_MIDI.keys()) == set(range(60, 85))
    c4 = get_note("C4")
    assert c4.written_midi == 60
    assert c4.full_name == "До первой октавы"
    assert c4.staff_position == 0
    assert c4.ledger_positions == (0,)
    assert c4.valves == (0, 0, 0)


def test_enharmonic_notes_and_accidentals():
    bb4 = get_note("Bb4")
    as4 = get_note("As4")
    assert bb4.written_midi == 70
    assert as4.written_midi == 70
    assert bb4.full_name == "Си-бемоль первой октавы"
    assert as4.full_name == "Ля-диез первой октавы"
    assert bb4.staff_position == 6  # третья линейка (Си)
    assert as4.staff_position == 5  # между 2 и 3 линейками (Ля)
    assert bb4.accidental is Accidental.FLAT
    assert bb4.accidental.asset_filename == "accidental_flat.png"
    assert as4.accidental.asset_filename == "accidental_sharp.png"
    assert get_note("B4_nat").accidental.asset_filename == "accidental_natural.png"


def test_valve_combinations_and_open_harmonics():
    open_midis = (60, 67, 72, 76, 79, 84)
    for midi in open_midis:
        note = get_canonical_note(midi)
        assert note.valves == (0, 0, 0)

    d4 = get_note("D4")
    assert d4.valves == (1, 0, 1)
    assert d4.matches_valves((1, 0, 1))
    assert not d4.matches_valves((1, 0, 0))

    e4 = get_note("E4")
    assert e4.valves == (1, 1, 0)
    assert e4.matches_valves((1, 1, 0))
    assert e4.matches_valves((0, 0, 1), allow_alt=True)


def test_bb_transposition_and_frequencies():
    c4 = get_note("C4")
    # На трубе Си-бемоль До первой октавы (written 60) звучит как Си-бемоль малой (concert 58, ~233.08 Гц)
    assert c4.concert_midi == 58
    assert math.isclose(c4.concert_freq_hz, 233.08188, rel_tol=1e-4)

    g4 = get_note("G4")
    assert g4.concert_midi == 65
    assert math.isclose(g4.concert_freq_hz, 349.22823, rel_tol=1e-4)

    # Обратное преобразование с микрофона
    measured_concert = freq_to_midi(233.08188)
    written = concert_to_written_midi(measured_concert)
    assert math.isclose(written, 60.0, abs_tol=1e-3)


def test_staff_stems_and_durations():
    # Ниже 3-й линейки штиль вверх, на 3-й линейке (Си1, pos=6) и выше — вниз
    assert get_note("A4").stem_up is True
    assert get_note("B4").stem_up is False
    assert get_note("C6").ledger_positions == (12, 14)

    assert NoteDuration.WHOLE.beats == 4
    assert not NoteDuration.WHOLE.has_stem
    assert not NoteDuration.WHOLE.is_filled_head

    assert NoteDuration.HALF.beats == 2
    assert NoteDuration.HALF.has_stem
    assert not NoteDuration.HALF.is_filled_head

    assert NoteDuration.QUARTER.beats == 1
    assert NoteDuration.QUARTER.has_stem
    assert NoteDuration.QUARTER.is_filled_head
