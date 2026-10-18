import math
import numpy as np

from note_learn.audio import SoundEngine
from note_learn.microphone import (
    DurationHoldTracker,
    MicrophoneListener,
    detect_pitch_hz,
    evaluate_pitch,
)
from note_learn.model import NoteDuration, get_note


def test_detect_pitch_on_pure_sine_and_harmonics():
    sr = 22050
    t = np.linspace(0.0, 2048 / sr, 2048, endpoint=False)
    # Частота concert Bb3 (233.08 Гц) = написанное До1 на трубе Си-бемоль, с богатыми обертонами трубы
    f0 = 233.0819
    signal = (
        0.5 * np.sin(2 * math.pi * f0 * t)
        + 0.8 * np.sin(2 * math.pi * (2 * f0) * t)
        + 0.4 * np.sin(2 * math.pi * (3 * f0) * t)
    ).astype(np.float32)

    freq, rms = detect_pitch_hz(signal, sr)
    assert freq is not None
    assert rms > 0.1
    assert math.isclose(freq, f0, rel_tol=0.008)

    reading = evaluate_pitch(freq, rms, target_written_midi=60)
    assert reading.nearest_note is not None
    assert reading.nearest_note.written_midi == 60
    assert reading.is_on_target is True
    assert reading.direction_hint == "exact"


def test_evaluate_pitch_low_and_high_hints():
    g4 = get_note("G4")  # written MIDI 67, concert F4 ~ 349.23 Hz
    # Сыграно ниже (например, Ми1, concert D4 ~ 293.66 Гц)
    low_reading = evaluate_pitch(293.66, 0.2, target_written_midi=g4.written_midi)
    assert low_reading.is_on_target is False
    assert low_reading.direction_hint == "low"
    assert low_reading.nearest_note is not None
    assert low_reading.nearest_note.written_midi == 64

    # Сыграно выше (Ля1, concert G4 ~ 392.00 Гц)
    high_reading = evaluate_pitch(392.00, 0.2, target_written_midi=g4.written_midi)
    assert high_reading.is_on_target is False
    assert high_reading.direction_hint == "high"


def test_detect_pitch_on_actual_trumpet_sample():
    engine = SoundEngine(enabled=False)
    engine._init_mixer()
    if engine._initialized:
        # Берём сдвинутый в строй Bb сэмпл Соль первой октавы (written 67 -> concert 65)
        wave = engine.get_bb_wave_for_note(67, duration=NoteDuration.HALF)
        assert wave is not None
        mid_slice = wave[4000 : 4000 + 2048].astype(np.float32) / 32768.0
        freq, rms = detect_pitch_hz(mid_slice, engine.sample_rate)
        assert freq is not None
        reading = evaluate_pitch(freq, rms, target_written_midi=67)
        assert reading.is_on_target is True


def test_duration_hold_tracker_with_grace_period():
    tracker = DurationHoldTracker(required_seconds=1.0, grace_period_sec=0.2)
    assert tracker.update(0.4, is_on_target=True) == 0.4
    # Короткий провал (0.1 с <= grace_period) не уменьшает накопленную длительность
    assert tracker.update(0.1, is_on_target=False) == 0.4
    # Возврат на верную ноту и завершение удержания
    assert tracker.update(0.6, is_on_target=True) == 1.0
    assert tracker.completed is True


def test_microphone_listener_simulated_mode():
    listener = MicrophoneListener()
    listener.set_simulated_frequency(get_note("F4").concert_freq_hz)
    reading = listener.read_pitch(target_written_midi=65)
    assert reading.is_on_target is True
    assert reading.nearest_note is not None
    assert reading.nearest_note.id == "F4"
