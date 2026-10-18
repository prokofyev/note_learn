from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import statistics
import threading
import numpy as np

from note_learn.model import (
    NoteDuration,
    TrumpetNote,
    concert_to_written_midi,
    freq_to_midi,
    get_canonical_note,
)


@dataclass(frozen=True)
class PitchReading:
    freq_hz: float | None
    rms: float
    written_midi_float: float | None
    nearest_note: TrumpetNote | None
    cents_from_nearest: float
    cents_from_target: float | None
    is_on_target: bool
    direction_hint: str  # "exact", "low", "high", "silent"


def detect_pitch_hz(
    samples: np.ndarray,
    sample_rate: int,
    min_freq: float = 175.0,
    max_freq: float = 1150.0,
    rms_threshold: float = 0.010,
) -> tuple[float | None, float]:
    """
    Определяет основную частоту монофонического сигнала методом нормализованной
    автокорреляции (McLeod Pitch Method / NSDF) на numpy.
    Возвращает (freq_hz | None, rms).
    """
    if len(samples) < 256:
        return None, 0.0

    x = samples.astype(np.float64)
    if x.ndim > 1:
        x = x[:, 0]
    x = x - np.mean(x)

    rms = float(np.sqrt(np.mean(x * x)))
    if rms < rms_threshold:
        return None, rms

    n = len(x)
    min_lag = max(2, int(sample_rate / max_freq))
    max_lag = min(n - 2, int(sample_rate / min_freq))
    if max_lag <= min_lag:
        return None, rms

    # Вычисляем автокорреляцию через БПФ
    fft_size = 1 << (2 * n - 1).bit_length()
    spec = np.fft.rfft(x, n=fft_size)
    acf = np.fft.irfft(spec * np.conj(spec), n=fft_size)[:n]

    # Нормализующий знаменатель энергии для NSDF
    sq = x * x
    cum_sq = np.cumsum(sq)
    total_energy = cum_sq[-1]
    lags = np.arange(n)
    # m[tau] = sum(x[0:n-tau]^2) + sum(x[tau:n]^2)
    m = np.empty(n, dtype=np.float64)
    m[0] = 2.0 * total_energy
    m[1:] = cum_sq[:-1] + (total_energy - cum_sq[:-1])
    nsdf = (2.0 * acf) / np.maximum(m, 1e-12)

    region = nsdf[min_lag : max_lag + 1]
    if len(region) < 3:
        return None, rms

    # Ищем положительные локальные максимумы после первого пересечения нуля
    zero_crossings = np.where(region < 0.0)[0]
    search_start = int(zero_crossings[0]) if len(zero_crossings) > 0 else 0

    peaks: list[tuple[int, float]] = []
    in_positive = False
    cur_best_idx = -1
    cur_best_val = -1.0

    for i in range(search_start, len(region)):
        val = float(region[i])
        if val > 0.0:
            in_positive = True
            if val > cur_best_val:
                cur_best_val = val
                cur_best_idx = i
        elif in_positive:
            if cur_best_idx >= 0:
                peaks.append((min_lag + cur_best_idx, cur_best_val))
            in_positive = False
            cur_best_idx = -1
            cur_best_val = -1.0

    if in_positive and cur_best_idx >= 0:
        peaks.append((min_lag + cur_best_idx, cur_best_val))

    if not peaks:
        return None, rms

    max_peak_val = max(p[1] for p in peaks)
    if max_peak_val < 0.55:
        return None, rms

    # Первый пик, превышающий 0.82 от глобального максимума — фундаментальный период
    threshold = 0.82 * max_peak_val
    chosen_lag = peaks[0][0]
    for lag_idx, peak_val in peaks:
        if peak_val >= threshold:
            chosen_lag = lag_idx
            break

    # Параболическая интерполяция вокруг chosen_lag
    if 1 <= chosen_lag < n - 1:
        y0 = float(nsdf[chosen_lag - 1])
        y1 = float(nsdf[chosen_lag])
        y2 = float(nsdf[chosen_lag + 1])
        denom = y0 - 2.0 * y1 + y2
        if abs(denom) > 1e-9:
            delta = 0.5 * (y0 - y2) / denom
            if -1.0 < delta < 1.0:
                refined_lag = chosen_lag + delta
            else:
                refined_lag = float(chosen_lag)
        else:
            refined_lag = float(chosen_lag)
    else:
        refined_lag = float(chosen_lag)

    freq = float(sample_rate / refined_lag)
    if not (min_freq <= freq <= max_freq):
        return None, rms
    return freq, rms


def evaluate_pitch(
    freq_hz: float | None,
    rms: float,
    target_written_midi: int | None = None,
    tolerance_cents: float = 45.0,
) -> PitchReading:
    if freq_hz is None or freq_hz <= 0.0:
        return PitchReading(
            freq_hz=None,
            rms=rms,
            written_midi_float=None,
            nearest_note=None,
            cents_from_nearest=0.0,
            cents_from_target=None,
            is_on_target=False,
            direction_hint="silent",
        )

    concert_midi = freq_to_midi(freq_hz)
    written_float = concert_to_written_midi(concert_midi)
    nearest_midi = int(round(written_float))
    nearest_note = get_canonical_note(nearest_midi)
    cents_nearest = (written_float - nearest_midi) * 100.0

    if target_written_midi is None:
        return PitchReading(
            freq_hz=freq_hz,
            rms=rms,
            written_midi_float=written_float,
            nearest_note=nearest_note,
            cents_from_nearest=cents_nearest,
            cents_from_target=None,
            is_on_target=False,
            direction_hint="exact" if abs(cents_nearest) <= tolerance_cents else ("low" if cents_nearest < 0 else "high"),
        )

    cents_target = (written_float - float(target_written_midi)) * 100.0
    on_target = abs(cents_target) <= tolerance_cents
    if on_target:
        hint = "exact"
    elif cents_target < 0:
        hint = "low"
    else:
        hint = "high"

    return PitchReading(
        freq_hz=freq_hz,
        rms=rms,
        written_midi_float=written_float,
        nearest_note=nearest_note,
        cents_from_nearest=cents_nearest,
        cents_from_target=cents_target,
        is_on_target=on_target,
        direction_hint=hint,
    )


class DurationHoldTracker:
    """
    Отслеживает выдерживание правильной ноты в течение заданной длительности
    с защитой от кратковременного дрожания звука (grace period).
    """

    def __init__(
        self,
        required_seconds: float,
        grace_period_sec: float = 0.18,
        decay_rate: float = 0.65,
    ) -> None:
        self.required_seconds = max(0.25, float(required_seconds))
        self.grace_period_sec = grace_period_sec
        self.decay_rate = decay_rate
        self.held_seconds = 0.0
        self._off_target_seconds = 0.0
        self.completed = False

    def reset(self, required_seconds: float | None = None) -> None:
        if required_seconds is not None:
            self.required_seconds = max(0.25, float(required_seconds))
        self.held_seconds = 0.0
        self._off_target_seconds = 0.0
        self.completed = False

    @property
    def progress(self) -> float:
        return min(1.0, self.held_seconds / self.required_seconds)

    def update(self, dt: float, is_on_target: bool) -> float:
        if self.completed:
            return 1.0

        dt = max(0.0, float(dt))
        if is_on_target:
            self._off_target_seconds = 0.0
            self.held_seconds = min(self.required_seconds, self.held_seconds + dt)
            if self.held_seconds >= self.required_seconds - 1e-4:
                self.held_seconds = self.required_seconds
                self.completed = True
        else:
            self._off_target_seconds += dt
            if self._off_target_seconds > self.grace_period_sec:
                self.held_seconds = max(0.0, self.held_seconds - dt * self.decay_rate)

        return self.progress


class MicrophoneListener:
    """
    Асинхронный захват звука с микрофона через sounddevice с безопасным fallback
    при отсутствии аудиовхода или прав доступа.
    """

    def __init__(self, sample_rate: int = 22050, window_size: int = 2048) -> None:
        self.sample_rate = sample_rate
        self.window_size = window_size
        self._buffer = np.zeros(window_size, dtype=np.float32)
        self._lock = threading.Lock()
        self._stream = None
        self.available = False
        self.active = False
        self.error_message: str | None = None
        self._recent_freqs: deque[float] = deque(maxlen=3)
        self._simulated_freq_hz: float | None = None

    def start(self) -> bool:
        if self.active:
            return True
        try:
            import sounddevice as sd

            def _callback(indata: np.ndarray, frames: int, time_info, status) -> None:
                mono = indata[:, 0] if indata.ndim > 1 else indata
                with self._lock:
                    if len(mono) >= self.window_size:
                        self._buffer[:] = mono[-self.window_size :]
                    else:
                        self._buffer = np.roll(self._buffer, -len(mono))
                        self._buffer[-len(mono) :] = mono

            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=512,
                callback=_callback,
            )
            self._stream.start()
            self.available = True
            self.active = True
            self.error_message = None
            return True
        except Exception as exc:
            self.available = False
            self.active = False
            self.error_message = str(exc)
            return False

    def stop(self) -> None:
        self.active = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._recent_freqs.clear()

    def set_simulated_frequency(self, freq_hz: float | None) -> None:
        """Позволяет симулировать входную частоту для тестирования и демо-режима."""
        self._simulated_freq_hz = freq_hz

    def read_pitch(
        self,
        target_written_midi: int | None = None,
        tolerance_cents: float = 45.0,
    ) -> PitchReading:
        if self._simulated_freq_hz is not None:
            return evaluate_pitch(
                self._simulated_freq_hz,
                rms=0.15,
                target_written_midi=target_written_midi,
                tolerance_cents=tolerance_cents,
            )

        if not self.active:
            return evaluate_pitch(None, 0.0, target_written_midi, tolerance_cents)

        with self._lock:
            snapshot = self._buffer.copy()

        raw_freq, rms = detect_pitch_hz(snapshot, self.sample_rate)
        if raw_freq is not None:
            self._recent_freqs.append(raw_freq)
            smoothed_freq = float(statistics.median(self._recent_freqs))
        else:
            if len(self._recent_freqs) > 0:
                self._recent_freqs.popleft()
            smoothed_freq = None

        return evaluate_pitch(
            smoothed_freq,
            rms=rms,
            target_written_midi=target_written_midi,
            tolerance_cents=tolerance_cents,
        )
