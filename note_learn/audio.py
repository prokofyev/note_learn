from __future__ import annotations

from pathlib import Path
import math
import numpy as np
import pygame

from note_learn.model import NoteDuration, TrumpetNote, get_canonical_note


DEFAULT_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def pitch_shift_samples(samples: np.ndarray, semitones: float) -> np.ndarray:
    """
    Изменяет высоту тона аудиомассива на заданное число полутонов через ресэмплинг.
    При semitones = -2.0 понижает частоту в 2^(-2/12) раза (на 1 тон вниз под строй Си-бемоль).
    Поддерживает 1D (mono) и 2D (stereo) массивы.
    """
    if abs(semitones) < 1e-6 or len(samples) == 0:
        return samples.copy()

    rate = 2.0 ** (semitones / 12.0)
    n_in = samples.shape[0]
    n_out = max(1, int(round(n_in / rate)))
    x_old = np.arange(n_in, dtype=np.float64)
    x_new = np.linspace(0.0, n_in - 1, n_out, dtype=np.float64)

    if samples.ndim == 1:
        shifted = np.interp(x_new, x_old, samples.astype(np.float64))
        return shifted.astype(samples.dtype)

    channels = []
    for ch in range(samples.shape[1]):
        ch_shifted = np.interp(x_new, x_old, samples[:, ch].astype(np.float64))
        channels.append(ch_shifted)
    stacked = np.column_stack(channels)
    return stacked.astype(samples.dtype)


def shape_note_duration(
    samples: np.ndarray,
    sample_rate: int,
    duration_sec: float,
) -> np.ndarray:
    """
    Формирует звучание ноты нужной длительности (четверть, половинная, целая)
    с сохранением атаки, плавным продлением сустейна при необходимости и мягким затуханием.
    """
    target_len = max(int(sample_rate * 0.25), int(round(sample_rate * duration_sec)))
    work = samples.astype(np.float32).copy()
    is_mono = work.ndim == 1
    if is_mono:
        work = work[:, np.newaxis]

    n_in = work.shape[0]
    if target_len <= n_in:
        out = work[:target_len].copy()
    else:
        # Выделяем участок устойчивого сустейна в середине сэмпла (30%..72%)
        loop_start = int(n_in * 0.30)
        loop_end = int(n_in * 0.72)
        loop_chunk = work[loop_start:loop_end]
        if len(loop_chunk) < 64:
            loop_chunk = work

        # Делаем зеркальный пинг-понг сустейна, чтобы избежать скачков фазы
        ping_pong = np.concatenate([loop_chunk, loop_chunk[::-1]], axis=0)
        parts = [work[:loop_end]]
        current_len = loop_end
        while current_len < target_len:
            need = target_len - current_len
            parts.append(ping_pong[:need])
            current_len += min(len(ping_pong), need)
        out = np.concatenate(parts, axis=0)[:target_len]

    # Плавная огибающая затухания (fade-out последние 120 мс)
    fade_len = min(int(sample_rate * 0.12), len(out) // 3)
    if fade_len > 1:
        envelope = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)[:, np.newaxis]
        out[-fade_len:] *= envelope

    if np.issubdtype(samples.dtype, np.integer):
        info = np.iinfo(samples.dtype)
        out = np.clip(out, info.min, info.max).astype(samples.dtype)
    else:
        out = out.astype(samples.dtype)

    return out[:, 0] if is_mono else out


class SoundEngine:
    """
    Отвечает за загрузку сэмплов трубы из assets/trumpet/trumpet_60..84.ogg,
    транспонирование в строй Си-бемоль (-2 полутона) и звуковые эффекты.
    """

    def __init__(self, assets_dir: Path = DEFAULT_ASSETS_DIR, enabled: bool = True) -> None:
        self.assets_dir = Path(assets_dir)
        self.enabled = enabled
        self.sample_rate = 22050
        self.channels = 2
        self._raw_arrays: dict[int, np.ndarray] = {}
        self._bb_arrays: dict[int, np.ndarray] = {}
        self._sound_cache: dict[tuple[int, str], pygame.mixer.Sound] = {}
        self._active_channel: pygame.mixer.Channel | None = None
        self._initialized = False

        if self.enabled:
            self._init_mixer()

    def _init_mixer(self) -> None:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
            init_info = pygame.mixer.get_init()
            if init_info:
                self.sample_rate, _, self.channels = init_info
                self._initialized = True
                self._load_all_samples()
        except Exception:
            self._initialized = False

    def _load_all_samples(self) -> None:
        trumpet_dir = self.assets_dir / "trumpet"
        for midi in range(60, 85):
            ogg_path = trumpet_dir / f"trumpet_{midi}.ogg"
            if ogg_path.exists():
                snd = pygame.mixer.Sound(str(ogg_path))
                arr = pygame.sndarray.array(snd)
                self._raw_arrays[midi] = arr

        # Формируем буферы в строе Си-бемоль (на 2 полутона ниже написанной ноты):
        # Для M >= 62 можно взять записанный сэмпл M-2, либо сдвинуть исходный M на -2 полутона.
        # Сдвиг исходного сэмпла на -2 полутона работает для всех M=60..84 (включая До1=60 и До#1=61).
        for midi in range(60, 85):
            if midi - 2 in self._raw_arrays:
                self._bb_arrays[midi] = self._raw_arrays[midi - 2].copy()
            elif midi in self._raw_arrays:
                self._bb_arrays[midi] = pitch_shift_samples(self._raw_arrays[midi], -2.0)

    def get_bb_wave_for_note(
        self,
        written_midi: int,
        duration: NoteDuration = NoteDuration.HALF,
        bpm: float = 76.0,
    ) -> np.ndarray | None:
        """Возвращает готовый PCM-массив для написанной ноты в строе Си-бемоль и нужной длительности."""
        clamped = max(60, min(84, int(written_midi)))
        base = self._bb_arrays.get(clamped)
        if base is None:
            return None
        dur_sec = duration.duration_seconds(bpm=bpm)
        return shape_note_duration(base, self.sample_rate, dur_sec)

    def play_note(
        self,
        note: TrumpetNote | int,
        duration: NoteDuration = NoteDuration.HALF,
        bpm: float = 76.0,
    ) -> None:
        if not self._initialized:
            return
        midi = note.written_midi if isinstance(note, TrumpetNote) else int(note)
        key = (midi, duration.value)
        if key not in self._sound_cache:
            arr = self.get_bb_wave_for_note(midi, duration=duration, bpm=bpm)
            if arr is None:
                return
            self._sound_cache[key] = pygame.sndarray.make_sound(arr)
        self.stop_note()
        self._active_channel = self._sound_cache[key].play()

    def stop_note(self) -> None:
        if self._active_channel is not None:
            try:
                self._active_channel.stop()
            except Exception:
                pass
            self._active_channel = None

    def _make_synth_sound(self, mono_float: np.ndarray) -> pygame.mixer.Sound | None:
        if not self._initialized:
            return None
        pcm = np.clip(mono_float * 32767.0, -32767, 32767).astype(np.int16)
        if self.channels == 2 and pcm.ndim == 1:
            pcm = np.column_stack([pcm, pcm])
        return pygame.sndarray.make_sound(pcm)

    def play_metronome_tick(self, accent: bool = False) -> None:
        if not self._initialized:
            return
        dur = 0.045
        t = np.linspace(0.0, dur, int(self.sample_rate * dur), endpoint=False)
        freq = 1100.0 if accent else 780.0
        env = np.exp(-t * 65.0)
        wave = 0.25 * np.sin(2.0 * math.pi * freq * t) * env
        snd = self._make_synth_sound(wave)
        if snd is not None:
            snd.play()

    def play_success_chime(self) -> None:
        if not self._initialized:
            return
        # Победное трезвучие Си-бемоль мажор (в унисон с До-Ми-Соль на трубе Bb!)
        freqs = (233.08, 293.66, 349.23, 466.16)
        parts = []
        for idx, freq in enumerate(freqs):
            dur = 0.09 if idx < 3 else 0.22
            t = np.linspace(0.0, dur, int(self.sample_rate * dur), endpoint=False)
            env = np.exp(-t * 10.0)
            parts.append(0.22 * np.sin(2.0 * math.pi * freq * t) * env)
        wave = np.concatenate(parts)
        snd = self._make_synth_sound(wave)
        if snd is not None:
            snd.play()

    def play_error_tone(self) -> None:
        if not self._initialized:
            return
        dur = 0.22
        t = np.linspace(0.0, dur, int(self.sample_rate * dur), endpoint=False)
        env = np.linspace(1.0, 0.0, len(t))
        wave = 0.18 * np.sin(2.0 * math.pi * 165.0 * t) * env
        snd = self._make_synth_sound(wave)
        if snd is not None:
            snd.play()
