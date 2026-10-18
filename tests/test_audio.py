import math
import numpy as np

from note_learn.audio import SoundEngine, pitch_shift_samples, shape_note_duration
from note_learn.model import NoteDuration, get_note


def _estimate_freq_autocorr(signal: np.ndarray, sample_rate: int) -> float:
    mono = signal[:, 0].astype(np.float64) if signal.ndim == 2 else signal.astype(np.float64)
    mono = mono - np.mean(mono)
    start = len(mono) // 5
    window = mono[start : start + 4096]
    best_lag = 40
    best_val = -1e18
    for lag in range(30, 250):
        val = float(np.dot(window[:-lag], window[lag:]))
        if val > best_val:
            best_val = val
            best_lag = lag
    return sample_rate / best_lag


def test_pitch_shift_down_two_semitones():
    sr = 22050
    t = np.linspace(0.0, 0.5, sr // 2, endpoint=False)
    # Синусоида До первой октавы (C4 = 261.63 Гц)
    c4_wave = np.sin(2.0 * math.pi * 261.6256 * t).astype(np.float32)
    shifted = pitch_shift_samples(c4_wave, semitones=-2.0)

    # Должна получиться частота Си-бемоль малой октавы (Bb3 ≈ 233.08 Гц)
    est_freq = _estimate_freq_autocorr(shifted, sr)
    assert math.isclose(est_freq, 233.08, rel_tol=0.02)


def test_shape_note_duration_quarter_and_whole():
    sr = 22050
    raw = (np.sin(np.linspace(0, 200, int(sr * 1.2))) * 10000).astype(np.int16)

    quarter = shape_note_duration(raw, sr, duration_sec=0.75)
    whole = shape_note_duration(raw, sr, duration_sec=2.8)

    assert math.isclose(len(quarter) / sr, 0.75, rel_tol=0.02)
    assert math.isclose(len(whole) / sr, 2.8, rel_tol=0.02)
    # Проверяем плавное затухание в конце
    assert abs(int(whole[-1])) <= 5


def test_sound_engine_bb_transposition_from_assets():
    engine = SoundEngine(enabled=False)
    # Проверим также прямое чтение одного ogg, если доступно
    engine._init_mixer()
    if engine._initialized:
        c4_wave = engine.get_bb_wave_for_note(60, duration=NoteDuration.HALF)
        assert c4_wave is not None
        freq_c4 = _estimate_freq_autocorr(c4_wave, engine.sample_rate)
        assert math.isclose(freq_c4, get_note("C4").concert_freq_hz, rel_tol=0.03)
