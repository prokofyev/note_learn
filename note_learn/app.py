from __future__ import annotations

from enum import Enum
from pathlib import Path
import pygame

from note_learn.audio import DEFAULT_ASSETS_DIR, SoundEngine
from note_learn.curriculum import (
    CURRICULUM_STAGES,
    CurriculumEngine,
    Exercise,
    ExerciseType,
    PlayerProfile,
)
from note_learn.microphone import DurationHoldTracker, MicrophoneListener, PitchReading
from note_learn.profile_store import DEFAULT_LEGACY_PROFILE_PATH, ProfileStore
from note_learn.model import (
    NOTES_BY_ID,
    NoteDuration,
    TrumpetNote,
    get_note,
)
from note_learn.renderer import (
    ACCENT_BLUE,
    ACCENT_GOLD,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    ACCENT_PURPLE,
    ACCENT_RED,
    PANEL_DARK,
    PANEL_LIGHT,
    ParticleSystem,
    TEXT_DARK,
    TEXT_LIGHT,
    TEXT_MUTED,
    UIRenderer,
    draw_star,
)


DEFAULT_SAVE_PATH = Path.home() / ".note_learn_profile.json"

# Коды символов и клавиш для трёх помп трубы (J/K/L, 1/2/3, русские Ф/Ы/В и А/В/Д)
VALVE_1_CHARS = {"j", "1", "ф", "а"}
VALVE_2_CHARS = {"k", "2", "ы", "в"}
VALVE_3_CHARS = {"l", "3", "в", "д"}


class AppScreen(str, Enum):
    MAP = "map"
    EXERCISE = "exercise"
    SUMMARY = "summary"
    ENCYCLOPEDIA = "encyclopedia"
    USERS = "users"


class TrumpetLearningApp:
    def __init__(
        self,
        save_path: Path = DEFAULT_SAVE_PATH,
        assets_dir: Path = DEFAULT_ASSETS_DIR,
        audio_enabled: bool = True,
        headless: bool = False,
        store: ProfileStore | None = None,
        fullscreen: bool = True,
    ) -> None:
        self.save_path = Path(save_path)
        self.assets_dir = Path(assets_dir)
        self.headless = headless

        pygame.init()
        self.width = 1180
        self.height = 760
        # Полноэкранный режим использует SCALED: логическое полотно 1180×760
        # растягивается на весь дисплей без изменения координат вёрстки экранов.
        self.fullscreen = bool(fullscreen) and not headless
        self.screen = self._create_display(headless=headless)
        pygame.display.set_caption("Трубач: Учим ноты, аппликатуру и слух (Строй Си-бемоль)")

        self.clock = pygame.time.Clock()
        self.renderer = UIRenderer(assets_dir=self.assets_dir)
        self.sound = SoundEngine(assets_dir=self.assets_dir, enabled=audio_enabled)
        self.mic = MicrophoneListener()
        self.particles = ParticleSystem()

        # Мультипрофильное хранилище включается для обычного запуска (путь по умолчанию)
        # или когда хранилище передано явно. Свой save_path сохраняет режим одного профиля.
        if store is not None:
            self.store: ProfileStore | None = store
        elif self.save_path != DEFAULT_SAVE_PATH:
            self.store = None
        else:
            self.store = ProfileStore(
                legacy_profile_path=DEFAULT_LEGACY_PROFILE_PATH,
            )

        if self.store is not None:
            self.profile = self.store.active_profile()
        else:
            self.profile = PlayerProfile.load(self.save_path)
        self.engine = CurriculumEngine(self.profile)

        self.current_screen: AppScreen = AppScreen.MAP
        self.running = True

        # Состояние раунда тренировки
        self.round_exercises: list[Exercise] = []
        self.round_index: int = 0
        self.round_correct_count: int = 0
        self.round_stars_earned: int = 0
        self.round_unlocked_notes: list[str] = []
        self.current_exercise: Exercise | None = None

        # Интерактивное состояние внутри задания
        self.pressed_valves: list[int] = [0, 0, 0]
        self.valve_anim: list[float] = [0.0, 0.0, 0.0]
        self.note_anim_progress: float = 0.0
        self.answered: bool = False
        self.last_answer_correct: bool = False
        self.feedback_message: str = ""
        self.selected_option_id: str | None = None

        # Состояние микрофонного задания
        self.hold_tracker = DurationHoldTracker(required_seconds=1.5)
        self.last_pitch_reading = PitchReading(
            freq_hz=None,
            rms=0.0,
            written_midi_float=None,
            nearest_note=None,
            cents_from_nearest=0.0,
            cents_from_target=None,
            is_on_target=False,
            direction_hint="silent",
        )
        self.practice_hold_key_down: bool = False

        # Состояние интерактивного справочника
        self.encyclopedia_note: TrumpetNote = get_note("C4")
        self.encyclopedia_duration: NoteDuration = NoteDuration.HALF

        # Состояние экрана пользователей
        self.name_input_active: bool = False
        self.name_input_text: str = ""
        self.pending_delete_user_id: str | None = None
        self.users_message: str = ""

        # Кэш интерактивных прямоугольников текущего кадра
        self._click_targets: dict[str, pygame.Rect] = {}

        if self.profile.with_trumpet:
            self.mic.start()

    def save_profile(self) -> None:
        """Сохраняет прогресс активного пользователя (в хранилище или в одиночный файл)."""
        if self.store is not None:
            self.store.save_active(self.profile)
        else:
            self.profile.save(self.save_path)

    def _create_display(self, headless: bool) -> pygame.Surface:
        """Создаёт поверхность окна, откатываясь в оконный (или скрытый) режим при ошибке."""
        size = (self.width, self.height)
        if headless:
            return pygame.display.set_mode(size, pygame.HIDDEN)

        if self.fullscreen:
            try:
                return pygame.display.set_mode(size, pygame.FULLSCREEN | pygame.SCALED)
            except Exception:
                # Полноэкранный режим недоступен — продолжаем в оконном.
                self.fullscreen = False

        try:
            return pygame.display.set_mode(size, pygame.SCALED)
        except Exception:
            try:
                return pygame.display.set_mode(size, 0)
            except Exception:
                return pygame.display.set_mode(size, pygame.HIDDEN)

    def set_fullscreen(self, enabled: bool) -> None:
        """Переключает полноэкранный и оконный режим без перезапуска приложения."""
        if self.headless:
            self.fullscreen = False
            return

        requested = bool(enabled)
        if requested == self.fullscreen:
            return

        if requested:
            try:
                self.screen = pygame.display.set_mode(
                    (self.width, self.height),
                    pygame.FULLSCREEN | pygame.SCALED,
                )
                self.fullscreen = True
                return
            except Exception:
                # Не удалось развернуть — остаёмся в оконном режиме.
                self.fullscreen = False

        try:
            self.screen = pygame.display.set_mode((self.width, self.height), pygame.SCALED)
        except Exception:
            self.screen = pygame.display.set_mode((self.width, self.height), 0)
        self.fullscreen = False

    def _fit_text(self, text: str, max_width: int) -> str:
        """Обрезает подпись по ширине, добавляя многоточие, чтобы она влезала в кнопку."""
        font = self.renderer.font_xs
        if font.size(text)[0] <= max_width:
            return text
        truncated = text
        while truncated and font.size(truncated + "…")[0] > max_width:
            truncated = truncated[:-1]
        return truncated + "…" if truncated else "…"

    def _apply_profile(self, profile: PlayerProfile) -> None:
        """Делает переданный профиль текущим и пересобирает зависящее от него состояние."""
        self.profile = profile
        self.engine = CurriculumEngine(self.profile)

        # Сбрасываем незавершённый раунд: он принадлежал другому пользователю.
        self.round_exercises = []
        self.round_index = 0
        self.round_correct_count = 0
        self.round_stars_earned = 0
        self.round_unlocked_notes = []
        self.current_exercise = None
        self.answered = False
        self.last_answer_correct = False
        self.selected_option_id = None
        self.feedback_message = ""
        self.pressed_valves = [0, 0, 0]
        self.hold_tracker.reset()

        if self.profile.with_trumpet:
            if not self.mic.active:
                self.mic.start()
        else:
            self.mic.stop()

    def create_user(self, name: str) -> bool:
        if self.store is None:
            self.users_message = "Профили доступны только в многопользовательском режиме"
            return False
        try:
            self.store.create_user(name)
        except ValueError:
            self.users_message = "Введите имя пользователя"
            return False
        self._apply_profile(self.store.active_profile())
        self.users_message = f"Добавлен пользователь: {self.store.active_user().name}"
        return True

    def switch_user(self, user_id: str) -> bool:
        if self.store is None or not self.store.switch_user(user_id):
            return False
        self._apply_profile(self.store.active_profile())
        self.pending_delete_user_id = None
        self.users_message = f"Активный пользователь: {self.store.active_user().name}"
        return True

    def request_delete_user(self, user_id: str) -> None:
        """Первое нажатие «Удалить» лишь запрашивает подтверждение."""
        if self.store is None or not self.store.can_delete_user(user_id):
            self.users_message = "Нельзя удалить: должен остаться хотя бы один пользователь"
            self.pending_delete_user_id = None
            return
        if self.pending_delete_user_id == user_id:
            self.confirm_delete_user(user_id)
            return
        self.pending_delete_user_id = user_id
        name = next((u.name for u in self.store.users() if u.id == user_id), user_id)
        self.users_message = f"Нажмите «Удалить» ещё раз, чтобы подтвердить удаление «{name}»"

    def confirm_delete_user(self, user_id: str) -> bool:
        if self.store is None or not self.store.delete_user(user_id):
            self.users_message = "Нельзя удалить: должен остаться хотя бы один пользователь"
            self.pending_delete_user_id = None
            return False
        self._apply_profile(self.store.active_profile())
        self.pending_delete_user_id = None
        self.users_message = f"Активный пользователь: {self.store.active_user().name}"
        return True

    def toggle_trumpet_mode(self) -> None:
        self.profile.with_trumpet = not self.profile.with_trumpet
        if self.profile.with_trumpet:
            self.mic.start()
        else:
            self.mic.stop()
        self.save_profile()

    def start_round(self, stage_idx: int | None = None, round_len: int = 8) -> None:
        if stage_idx is not None:
            self.profile.unlock_stage_manually(stage_idx)
        self.round_exercises = []
        self.round_index = 0
        self.round_correct_count = 0
        self.round_stars_earned = 0
        self.round_unlocked_notes = []
        self._round_total = round_len
        self.current_screen = AppScreen.EXERCISE
        self._load_next_exercise_in_round()

    def _load_next_exercise_in_round(self) -> None:
        if self.round_index >= getattr(self, "_round_total", 8):
            self.current_screen = AppScreen.SUMMARY
            self.sound.play_success_chime()
            self.particles.emit_burst(self.width // 2, self.height // 3, count=55)
            self.save_profile()
            return

        ex = self.engine.next_exercise(stage_idx=self.profile.current_stage_idx)
        self.current_exercise = ex
        self.answered = False
        self.last_answer_correct = False
        self.selected_option_id = None
        self.note_anim_progress = 0.0
        self.practice_hold_key_down = False

        if ex.exercise_type is ExerciseType.INTRO:
            self.pressed_valves = list(ex.target_note.valves)
            self.feedback_message = (
                f"Новая нота: {ex.target_note.full_name}! "
                f"Аппликатура: {ex.target_note.valves_display}"
            )
            self.sound.play_note(ex.target_note, ex.duration)
        elif ex.exercise_type is ExerciseType.PLAY_TRUMPET:
            self.pressed_valves = list(ex.target_note.valves)
            self.hold_tracker.reset(ex.duration.duration_seconds(bpm=76.0))
            self.feedback_message = (
                f"Зажми помпы {ex.target_note.valves_display} и сыграй "
                f"«{ex.target_note.full_name}» в микрофон!"
            )
            if self.profile.with_trumpet and not self.mic.active:
                self.mic.start()
            self.sound.play_note(ex.target_note, NoteDuration.QUARTER)
        elif ex.exercise_type is ExerciseType.EAR_TO_NOTE:
            self.pressed_valves = [0, 0, 0]
            self.feedback_message = "Послушай как звучит труба и угадай, какая это нота!"
            self.sound.play_note(ex.target_note, ex.duration)
        elif ex.exercise_type is ExerciseType.STAFF_TO_VALVES:
            self.pressed_valves = [0, 0, 0]
            self.feedback_message = (
                f"Зажми помпы для ноты «{ex.target_note.full_name}» "
                f"и нажми [Enter] или «Проверить»"
            )
        else:
            self.pressed_valves = list(ex.target_note.valves)
            self.feedback_message = "Посмотри на нотный стан и выбери правильное название ноты!"

    def submit_option_answer(self, chosen_note: TrumpetNote) -> None:
        if self.current_exercise is None or self.answered:
            return
        ex = self.current_exercise
        self.selected_option_id = chosen_note.id
        is_ok = chosen_note.written_midi == ex.target_note.written_midi and (
            chosen_note.id == ex.target_note.id
        )
        self._finalize_answer(is_ok)

    def submit_valves_answer(self) -> None:
        if self.current_exercise is None or self.answered:
            return
        ex = self.current_exercise
        pressed_tuple = (self.pressed_valves[0], self.pressed_valves[1], self.pressed_valves[2])
        is_ok = ex.target_note.matches_valves(pressed_tuple, allow_alt=True)
        self._finalize_answer(is_ok)

    def complete_intro_card(self) -> None:
        if self.current_exercise is None or self.answered:
            return
        self._finalize_answer(True)

    def _finalize_answer(self, is_correct: bool) -> None:
        if self.current_exercise is None or self.answered:
            return
        ex = self.current_exercise
        self.answered = True
        self.last_answer_correct = is_correct
        self.pressed_valves = list(ex.target_note.valves)

        outcome = self.profile.record_answer(
            ex.target_note.id,
            is_correct=is_correct,
            exercise_type=ex.exercise_type,
        )
        self.save_profile()

        for nid in outcome["newly_unlocked_notes"]:
            if nid not in self.round_unlocked_notes:
                self.round_unlocked_notes.append(nid)

        if is_correct:
            self.round_correct_count += 1
            self.round_stars_earned += outcome["stars_earned"]
            self.feedback_message = (
                f"Молодец! Это {ex.target_note.full_name} | Помпы: {ex.target_note.valves_display}"
            )
            self.sound.play_note(ex.target_note, ex.duration)
            self.particles.emit_burst(self.width // 2, self.height // 2 - 40, count=40)
        else:
            self.feedback_message = (
                f"Почти! Правильный ответ: {ex.target_note.full_name} "
                f"(помпы: {ex.target_note.valves_display}). Послушай и запомни!"
            )
            self.sound.play_error_tone()

    def advance_after_answer(self) -> None:
        if not self.answered:
            return
        self.round_index += 1
        self._load_next_exercise_in_round()

    def toggle_valve(self, idx: int) -> None:
        if 0 <= idx < 3 and not self.answered:
            self.pressed_valves[idx] = 0 if self.pressed_valves[idx] else 1
            if self.current_screen is AppScreen.ENCYCLOPEDIA:
                self._sync_encyclopedia_valves()

    def _sync_encyclopedia_valves(self) -> None:
        pass

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
            return

        if event.type == pygame.KEYDOWN:
            self._handle_keydown(event)
        elif event.type == pygame.KEYUP:
            if event.key == pygame.K_h:
                self.practice_hold_key_down = False
                self.mic.set_simulated_frequency(None)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._handle_mouse_click(event.pos)

    def _handle_keydown(self, event: pygame.event.Event) -> None:
        ch = (event.unicode or "").lower()

        # Ввод имени пользователя перехватывает клавиши, пока поле активно.
        if self.name_input_active:
            self._handle_name_input_key(event, ch)
            return

        # F11 переключает полноэкранный и оконный режим на любом экране.
        if event.key == pygame.K_F11:
            self.set_fullscreen(not self.fullscreen)
            return

        if event.key == pygame.K_ESCAPE:
            if self.current_screen is not AppScreen.MAP:
                self.current_screen = AppScreen.MAP
            else:
                self.running = False
            return

        if self.current_screen is AppScreen.USERS:
            if self.store is not None and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.name_input_active = True
                self.name_input_text = ""
                self.users_message = "Введите имя нового пользователя и нажмите Enter"
            return

        if self.current_screen is AppScreen.EXERCISE and self.current_exercise is not None:
            ex = self.current_exercise
            if event.key == pygame.K_SPACE:
                self.sound.play_note(ex.target_note, ex.duration)
                return

            if self.answered and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_RIGHT):
                self.advance_after_answer()
                return

            if not self.answered:
                if ex.exercise_type in (ExerciseType.STAFF_TO_VALVES, ExerciseType.INTRO):
                    if event.key in (pygame.K_1, pygame.K_j) or ch in VALVE_1_CHARS:
                        self.toggle_valve(0)
                    elif event.key in (pygame.K_2, pygame.K_k) or ch in VALVE_2_CHARS:
                        self.toggle_valve(1)
                    elif event.key in (pygame.K_3, pygame.K_l) or ch in VALVE_3_CHARS:
                        self.toggle_valve(2)
                    elif event.key == pygame.K_0 or ch == "0":
                        self.pressed_valves = [0, 0, 0]
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if ex.exercise_type is ExerciseType.INTRO:
                            self.complete_intro_card()
                        else:
                            self.submit_valves_answer()
                elif ex.exercise_type in (ExerciseType.STAFF_TO_NAME, ExerciseType.EAR_TO_NOTE):
                    idx_map = {
                        pygame.K_1: 0,
                        pygame.K_2: 1,
                        pygame.K_3: 2,
                        pygame.K_4: 3,
                    }
                    if event.key in idx_map and idx_map[event.key] < len(ex.options):
                        self.submit_option_answer(ex.options[idx_map[event.key]])
                elif ex.exercise_type is ExerciseType.PLAY_TRUMPET:
                    if event.key == pygame.K_h:
                        self.practice_hold_key_down = True
                        self.mic.set_simulated_frequency(ex.target_note.concert_freq_hz)
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        self._finalize_answer(True)

        elif self.current_screen is AppScreen.ENCYCLOPEDIA:
            if event.key == pygame.K_SPACE:
                self.sound.play_note(self.encyclopedia_note, self.encyclopedia_duration)

    def _handle_name_input_key(self, event: pygame.event.Event, ch: str) -> None:
        if event.key == pygame.K_ESCAPE:
            self.name_input_active = False
            self.name_input_text = ""
            self.users_message = "Создание пользователя отменено"
            return
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            name = self.name_input_text.strip()
            self.name_input_active = False
            self.name_input_text = ""
            if not name:
                self.users_message = "Введите имя пользователя"
                return
            if self.create_user(name):
                self.current_screen = AppScreen.MAP
            return
        if event.key == pygame.K_BACKSPACE:
            self.name_input_text = self.name_input_text[:-1]
            return
        if event.unicode and event.unicode.isprintable():
            if len(self.name_input_text) < 40:
                self.name_input_text += event.unicode

    def _handle_mouse_click(self, pos: tuple[int, int]) -> None:
        for action_id, rect in list(self._click_targets.items()):
            if rect.collidepoint(pos):
                self._trigger_action(action_id)
                return

    def _trigger_action(self, action_id: str) -> None:
        if action_id == "nav_map":
            self.current_screen = AppScreen.MAP
        elif action_id == "nav_users":
            self.current_screen = AppScreen.USERS
            self.name_input_active = False
            self.name_input_text = ""
            self.pending_delete_user_id = None
            self.users_message = ""
        elif action_id == "new_user":
            if self.store is not None:
                self.name_input_active = True
                self.name_input_text = ""
                self.users_message = "Введите имя нового пользователя и нажмите Enter"
        elif action_id.startswith("select_user:"):
            self.switch_user(action_id.split(":", 1)[1])
        elif action_id.startswith("delete_user:"):
            self.request_delete_user(action_id.split(":", 1)[1])
        elif action_id == "nav_encyclopedia":
            self.current_screen = AppScreen.ENCYCLOPEDIA
            self.pressed_valves = list(self.encyclopedia_note.valves)
            self.sound.play_note(self.encyclopedia_note, self.encyclopedia_duration)
        elif action_id == "toggle_trumpet":
            self.toggle_trumpet_mode()
        elif action_id.startswith("start_stage:"):
            s_idx = int(action_id.split(":")[1])
            self.start_round(stage_idx=s_idx)
        elif action_id == "play_current_note":
            if self.current_screen is AppScreen.EXERCISE and self.current_exercise:
                self.sound.play_note(self.current_exercise.target_note, self.current_exercise.duration)
            elif self.current_screen is AppScreen.ENCYCLOPEDIA:
                self.sound.play_note(self.encyclopedia_note, self.encyclopedia_duration)
        elif action_id.startswith("valve:"):
            v_idx = int(action_id.split(":")[1])
            self.toggle_valve(v_idx)
        elif action_id == "reset_valves":
            if not self.answered:
                self.pressed_valves = [0, 0, 0]
        elif action_id == "submit_valves":
            self.submit_valves_answer()
        elif action_id == "complete_intro":
            self.complete_intro_card()
        elif action_id.startswith("option:"):
            nid = action_id.split(":")[1]
            self.submit_option_answer(get_note(nid))
        elif action_id == "next_exercise":
            self.advance_after_answer()
        elif action_id == "simulate_mic_success":
            if self.current_exercise and not self.answered:
                self.hold_tracker.update(self.hold_tracker.required_seconds, is_on_target=True)
                self._finalize_answer(True)
        elif action_id.startswith("enc_note:"):
            nid = action_id.split(":")[1]
            self.encyclopedia_note = get_note(nid)
            self.pressed_valves = list(self.encyclopedia_note.valves)
            self.sound.play_note(self.encyclopedia_note, self.encyclopedia_duration)
        elif action_id.startswith("enc_dur:"):
            dur_val = action_id.split(":")[1]
            self.encyclopedia_duration = NoteDuration(dur_val)
            self.sound.play_note(self.encyclopedia_note, self.encyclopedia_duration)

    def update(self, dt: float) -> None:
        self.particles.update(dt)
        self.note_anim_progress = min(1.0, self.note_anim_progress + dt * 4.5)

        # Пружинная интерполяция поршней трёх помп
        for i in range(3):
            target = float(self.pressed_valves[i])
            self.valve_anim[i] += (target - self.valve_anim[i]) * min(1.0, dt * 16.0)

        # Обновление микрофона и трекера удержания длительности в режиме PLAY_TRUMPET
        if (
            self.current_screen is AppScreen.EXERCISE
            and self.current_exercise is not None
            and self.current_exercise.exercise_type is ExerciseType.PLAY_TRUMPET
            and not self.answered
        ):
            target_midi = self.current_exercise.target_note.written_midi
            self.last_pitch_reading = self.mic.read_pitch(target_written_midi=target_midi)
            prog = self.hold_tracker.update(dt, self.last_pitch_reading.is_on_target)
            if prog >= 1.0 and self.hold_tracker.completed:
                self.mic.set_simulated_frequency(None)
                self._finalize_answer(True)

    def draw(self) -> None:
        self._click_targets.clear()
        self.renderer.draw_background(self.screen)
        self._draw_top_bar()

        if self.current_screen is AppScreen.MAP:
            self._draw_map_screen()
        elif self.current_screen is AppScreen.EXERCISE:
            self._draw_exercise_screen()
        elif self.current_screen is AppScreen.SUMMARY:
            self._draw_summary_screen()
        elif self.current_screen is AppScreen.ENCYCLOPEDIA:
            self._draw_encyclopedia_screen()
        elif self.current_screen is AppScreen.USERS:
            self._draw_users_screen()

        self.particles.draw(self.screen)
        if not self.headless:
            pygame.display.flip()

    def _draw_top_bar(self) -> None:
        bar_rect = pygame.Rect(20, 14, self.width - 40, 62)
        pygame.draw.rect(self.screen, PANEL_DARK, bar_rect, border_radius=16)
        pygame.draw.rect(self.screen, (66, 82, 124), bar_rect, width=2, border_radius=16)

        # Кнопки навигации слева
        map_btn = pygame.Rect(34, 24, 156, 42)
        self.renderer.draw_button(
            self.screen,
            map_btn,
            "Карта курса",
            bg_color=ACCENT_BLUE if self.current_screen is AppScreen.MAP else PANEL_LIGHT,
            font=self.renderer.font_sm,
        )
        self._click_targets["nav_map"] = map_btn

        enc_btn = pygame.Rect(200, 24, 190, 42)
        self.renderer.draw_button(
            self.screen,
            enc_btn,
            "Все ноты и помпы",
            bg_color=ACCENT_PURPLE if self.current_screen is AppScreen.ENCYCLOPEDIA else PANEL_LIGHT,
            font=self.renderer.font_sm,
        )
        self._click_targets["nav_encyclopedia"] = enc_btn

        # Статистика в центре: Звёзды, Серия, Опыт
        draw_star(self.screen, (416, 45), 13, ACCENT_GOLD)
        stars_surf = self.renderer.font_md.render(f"{self.profile.stars}", True, ACCENT_GOLD)
        self.screen.blit(stars_surf, (434, 32))

        streak_col = ACCENT_ORANGE if self.profile.current_streak >= 3 else TEXT_LIGHT
        streak_surf = self.renderer.font_xs.render(
            f"Серия {self.profile.current_streak}x",
            True,
            streak_col,
        )
        self.screen.blit(streak_surf, (474, 40))

        xp_surf = self.renderer.font_xs.render(f"Опыт: {self.profile.xp} XP", True, TEXT_MUTED)
        self.screen.blit(xp_surf, (562, 40))

        # Активный пользователь: кнопка ведёт на экран управления профилями
        active_name = self.store.active_user().name if self.store is not None else "Один профиль"
        profile_btn = pygame.Rect(676, 24, 354, 42)
        profile_label = self._fit_text(f"Профиль: {active_name}", profile_btn.width - 20)
        self.renderer.draw_button(
            self.screen,
            profile_btn,
            profile_label,
            bg_color=ACCENT_GOLD if self.current_screen is AppScreen.USERS else PANEL_LIGHT,
            text_color=TEXT_DARK if self.current_screen is AppScreen.USERS else TEXT_LIGHT,
            font=self.renderer.font_xs,
        )
        self._click_targets["nav_users"] = profile_btn

        # Переключатель "С трубой / Без трубы" справа
        mic_btn = pygame.Rect(1040, 24, 126, 42)
        mic_on = self.profile.with_trumpet
        self.renderer.draw_button(
            self.screen,
            mic_btn,
            "С трубой" if mic_on else "Без трубы",
            bg_color=ACCENT_GREEN if mic_on else (72, 82, 112),
            text_color=TEXT_DARK if mic_on else TEXT_LIGHT,
            font=self.renderer.font_xs,
        )
        self._click_targets["toggle_trumpet"] = mic_btn

    def _draw_map_screen(self) -> None:
        header = self.renderer.font_xl.render(
            "Школа юного трубача (Строй Си-бемоль | Унисон)",
            True,
            TEXT_LIGHT,
        )
        self.screen.blit(header, (40, 92))

        sub = self.renderer.font_sm.render(
            "Идём от простого к сложному: новые ноты открываются по мере освоения, а пройденные возвращаются для закрепления!",
            True,
            TEXT_MUTED,
        )
        self.screen.blit(sub, (40, 134))

        cols = 2
        card_w = (self.width - 100) // cols
        card_h = 172
        start_y = 172

        for idx, stage in enumerate(CURRICULUM_STAGES):
            r = idx // cols
            c = idx % cols
            x = 40 + c * (card_w + 20)
            y = start_y + r * (card_h + 18)
            rect = pygame.Rect(x, y, card_w, card_h)

            is_unlocked = idx <= self.profile.max_unlocked_stage_idx
            is_current = idx == self.profile.current_stage_idx
            bg = (40, 54, 88) if is_unlocked else (28, 34, 54)
            border = ACCENT_GOLD if is_current else (ACCENT_BLUE if is_unlocked else (65, 75, 102))

            pygame.draw.rect(self.screen, bg, rect, border_radius=16)
            pygame.draw.rect(self.screen, border, rect, width=3 if is_current else 2, border_radius=16)

            title_surf = self.renderer.font_md.render(stage.title, True, TEXT_LIGHT)
            self.screen.blit(title_surf, (rect.left + 18, rect.top + 14))

            sub_surf = self.renderer.font_xs.render(stage.subtitle, True, TEXT_MUTED)
            self.screen.blit(sub_surf, (rect.left + 18, rect.top + 42))

            # Бейджи нот этапа с полоской мастерства
            badge_x = rect.left + 18
            badge_y = rect.top + 68
            for nid in stage.note_ids:
                note = get_note(nid)
                prog = self.profile.note_progress[nid]
                b_rect = pygame.Rect(badge_x, badge_y, 68, 42)
                b_col = (58, 76, 118) if prog.unlocked else (34, 42, 64)
                pygame.draw.rect(self.screen, b_col, b_rect, border_radius=8)

                lbl = self.renderer.font_sm.render(
                    note.short_name,
                    True,
                    TEXT_LIGHT if prog.unlocked else TEXT_MUTED,
                )
                self.screen.blit(lbl, (b_rect.centerx - lbl.get_width() // 2, b_rect.top + 4))

                # Мини-индикатор мастерства ноты
                m_bar = pygame.Rect(b_rect.left + 6, b_rect.bottom - 10, b_rect.width - 12, 5)
                pygame.draw.rect(self.screen, (20, 26, 40), m_bar, border_radius=3)
                if prog.mastery > 0:
                    fill = int(m_bar.width * prog.mastery)
                    m_col = ACCENT_GREEN if prog.mastery >= 0.7 else ACCENT_GOLD
                    pygame.draw.rect(
                        self.screen,
                        m_col,
                        (m_bar.left, m_bar.top, max(4, fill), m_bar.height),
                        border_radius=3,
                    )
                badge_x += 74

            # Общий процент освоения этапа и кнопка старта
            mastery_pct = int(round(self.profile.stage_mastery(idx) * 100))
            pct_surf = self.renderer.font_sm.render(f"Освоено: {mastery_pct}%", True, ACCENT_GOLD)
            self.screen.blit(pct_surf, (rect.left + 18, rect.bottom - 38))

            btn_rect = pygame.Rect(rect.right - 188, rect.bottom - 46, 170, 36)
            btn_label = "Тренировать ->" if is_unlocked else "Открыть этап ->"
            btn_col = ACCENT_GREEN if is_current else (ACCENT_BLUE if is_unlocked else (78, 90, 125))
            self.renderer.draw_button(
                self.screen,
                btn_rect,
                btn_label,
                bg_color=btn_col,
                text_color=TEXT_DARK if is_current else TEXT_LIGHT,
                font=self.renderer.font_sm,
            )
            self._click_targets[f"start_stage:{idx}"] = btn_rect

    def _draw_exercise_screen(self) -> None:
        if self.current_exercise is None:
            return
        ex = self.current_exercise
        stage = CURRICULUM_STAGES[self.profile.current_stage_idx]

        # Заголовок задания и прогресс раунда
        total_q = getattr(self, "_round_total", 8)
        header_txt = f"{stage.title}  |  Задание {self.round_index + 1} из {total_q}: {ex.exercise_type.title_ru}"
        if ex.is_review:
            header_txt += "  [Повторение пройденного!]"
        hdr = self.renderer.font_lg.render(header_txt, True, ACCENT_GOLD if ex.is_review else TEXT_LIGHT)
        self.screen.blit(hdr, (40, 92))

        # Левая верхняя область: Карточка нотного стана
        staff_rect = pygame.Rect(40, 136, 650, 290)
        show_note_on_staff = ex.exercise_type is not ExerciseType.EAR_TO_NOTE or self.answered
        note_to_draw = ex.target_note if show_note_on_staff else None

        if ex.exercise_type in (ExerciseType.INTRO, ExerciseType.STAFF_TO_VALVES, ExerciseType.PLAY_TRUMPET) or self.answered:
            staff_subtitle = f"{ex.target_note.full_name}  ({ex.duration.russian_name})"
        elif ex.exercise_type is ExerciseType.EAR_TO_NOTE:
            staff_subtitle = "Звучит загаданная нота... Какая она?"
        else:
            staff_subtitle = f"Какая это нота на нотном стане? ({ex.duration.short_russian})"

        hl_color = None
        if self.answered:
            hl_color = ACCENT_GREEN if self.last_answer_correct else ACCENT_ORANGE

        ghost = None
        if ex.exercise_type is ExerciseType.PLAY_TRUMPET and not self.answered:
            ghost = self.last_pitch_reading.nearest_note

        self.renderer.draw_staff_card(
            self.screen,
            staff_rect,
            note_to_draw,
            ex.duration,
            subtitle=staff_subtitle,
            highlight_color=hl_color,
            anim_progress=self.note_anim_progress,
            ghost_note=ghost,
        )

        # Если это задание "Угадай на слух" до ответа — рисуем крупный вопросительный знак на стане
        if not show_note_on_staff:
            q_surf = self.renderer.font_xl.render("? Послушай звук трубы ?", True, ACCENT_BLUE)
            self.screen.blit(q_surf, (staff_rect.centerx - q_surf.get_width() // 2, staff_rect.centery - 22))

        # Кнопка "Послушать ноту (Пробел)" под нотным станом
        listen_btn = pygame.Rect(40, 440, 315, 48)
        self.renderer.draw_button(
            self.screen,
            listen_btn,
            "Послушать ноту [Пробел]",
            bg_color=ACCENT_BLUE,
            font=self.renderer.font_sm,
        )
        self._click_targets["play_current_note"] = listen_btn

        # Правая область: Помпы трубы (и/или Тюнер микрофона)
        valves_rect = pygame.Rect(714, 136, 426, 290)
        expected_v = ex.target_note.valves if (self.answered or ex.exercise_type is ExerciseType.INTRO) else None
        valve_boxes = self.renderer.draw_valves_widget(
            self.screen,
            valves_rect,
            (self.pressed_valves[0], self.pressed_valves[1], self.pressed_valves[2]),
            self.valve_anim,
            expected_valves=expected_v,
            interactive_hint=(ex.exercise_type in (ExerciseType.STAFF_TO_VALVES, ExerciseType.INTRO)),
            harmonic_note=ex.target_note,
        )
        for i, vbox in enumerate(valve_boxes):
            self._click_targets[f"valve:{i}"] = vbox

        # Кнопка сброса помп ("Открыто 0-0-0")
        if ex.exercise_type is ExerciseType.STAFF_TO_VALVES and not self.answered:
            rst_btn = pygame.Rect(714, 440, 200, 48)
            self.renderer.draw_button(
                self.screen,
                rst_btn,
                "Открытые (0-0-0)",
                bg_color=PANEL_LIGHT,
                font=self.renderer.font_sm,
            )
            self._click_targets["reset_valves"] = rst_btn

            chk_btn = pygame.Rect(928, 440, 212, 48)
            self.renderer.draw_button(
                self.screen,
                chk_btn,
                "Проверить [Enter]",
                bg_color=ACCENT_GREEN,
                text_color=TEXT_DARK,
                font=self.renderer.font_md,
            )
            self._click_targets["submit_valves"] = chk_btn

        # Нижняя интерактивная панель в зависимости от типа задания
        if ex.exercise_type is ExerciseType.INTRO and not self.answered:
            info_rect = pygame.Rect(40, 508, self.width - 80, 140)
            pygame.draw.rect(self.screen, PANEL_DARK, info_rect, border_radius=16)
            pygame.draw.rect(self.screen, ACCENT_GOLD, info_rect, width=2, border_radius=16)

            t1 = self.renderer.font_lg.render(
                f"Запомни: {ex.target_note.full_name}  —  помпы: {ex.target_note.valves_display}",
                True,
                ACCENT_GOLD,
            )
            self.screen.blit(t1, (info_rect.left + 24, info_rect.top + 18))

            t2 = self.renderer.font_sm.render(
                f"Попробуй нажать помпы на клавиатуре (J, K, L или 1, 2, 3), послушай звук в унисон со своей трубой и жми «Понятно!»",
                True,
                TEXT_LIGHT,
            )
            self.screen.blit(t2, (info_rect.left + 24, info_rect.top + 58))

            ok_btn = pygame.Rect(info_rect.right - 260, info_rect.bottom - 54, 236, 42)
            self.renderer.draw_button(
                self.screen,
                ok_btn,
                "Понятно! Дальше [Enter]",
                bg_color=ACCENT_GREEN,
                text_color=TEXT_DARK,
                font=self.renderer.font_sm,
            )
            self._click_targets["complete_intro"] = ok_btn

        elif ex.exercise_type in (ExerciseType.STAFF_TO_NAME, ExerciseType.EAR_TO_NOTE):
            opt_y = 514
            opt_w = (self.width - 80 - 36) // 4
            for i, opt_note in enumerate(ex.options):
                opt_rect = pygame.Rect(40 + i * (opt_w + 12), opt_y, opt_w, 92)
                bg = PANEL_LIGHT
                txt_col = TEXT_LIGHT
                if self.answered:
                    if opt_note.id == ex.target_note.id:
                        bg = ACCENT_GREEN
                        txt_col = TEXT_DARK
                    elif opt_note.id == self.selected_option_id:
                        bg = ACCENT_RED
                self.renderer.draw_button(
                    self.screen,
                    opt_rect,
                    f"{i + 1}. {opt_note.full_name}",
                    bg_color=bg,
                    text_color=txt_col,
                    font=self.renderer.font_sm,
                    icon_accidental=opt_note.accidental,
                )
                if not self.answered:
                    self._click_targets[f"option:{opt_note.id}"] = opt_rect

        elif ex.exercise_type is ExerciseType.PLAY_TRUMPET and not self.answered:
            tuner_rect = pygame.Rect(40, 500, 780, 210)
            self.renderer.draw_tuner_and_hold_widget(
                self.screen,
                tuner_rect,
                self.last_pitch_reading,
                self.hold_tracker.progress,
                ex.target_note,
                ex.duration,
                mic_available=self.mic.active,
            )

            sim_btn = pygame.Rect(840, 530, 300, 54)
            self.renderer.draw_button(
                self.screen,
                sim_btn,
                "Засчитать ноту [Enter]",
                bg_color=ACCENT_GREEN,
                text_color=TEXT_DARK,
                font=self.renderer.font_sm,
            )
            self._click_targets["simulate_mic_success"] = sim_btn

            hint_sim = self.renderer.font_xs.render(
                "Или удерживай клавишу [H] для проверки тюнера",
                True,
                TEXT_MUTED,
            )
            self.screen.blit(hint_sim, (845, 598))

        # Панель обратной связи и кнопка перехода к следующему заданию
        fb_rect = pygame.Rect(40, self.height - 86, self.width - 80, 66)
        fb_bg = (34, 68, 56) if (self.answered and self.last_answer_correct) else (
            (76, 44, 48) if self.answered else PANEL_DARK
        )
        pygame.draw.rect(self.screen, fb_bg, fb_rect, border_radius=14)
        fb_surf = self.renderer.font_md.render(self.feedback_message, True, TEXT_LIGHT)
        self.screen.blit(fb_surf, (fb_rect.left + 20, fb_rect.centery - fb_surf.get_height() // 2))

        if self.answered:
            next_btn = pygame.Rect(fb_rect.right - 230, fb_rect.top + 11, 214, 44)
            self.renderer.draw_button(
                self.screen,
                next_btn,
                "Дальше [Enter] ->",
                bg_color=ACCENT_GOLD,
                text_color=TEXT_DARK,
                font=self.renderer.font_md,
            )
            self._click_targets["next_exercise"] = next_btn

    def _draw_users_screen(self) -> None:
        hdr = self.renderer.font_lg.render(
            "Пользователи: у каждого свой прогресс по курсу",
            True,
            TEXT_LIGHT,
        )
        self.screen.blit(hdr, (40, 92))

        if self.store is None:
            warn = self.renderer.font_sm.render(
                "Приложение запущено с одним профилем по указанному пути. "
                "Запустите обычным способом (main.py), чтобы включить несколько пользователей.",
                True,
                ACCENT_ORANGE,
            )
            self.screen.blit(warn, (40, 150))
            back_btn = pygame.Rect(40, 200, 220, 48)
            self.renderer.draw_button(
                self.screen, back_btn, "На карту курса", bg_color=ACCENT_BLUE,
                font=self.renderer.font_sm,
            )
            self._click_targets["nav_map"] = back_btn
            return

        users = self.store.users()
        active = self.store.active_user()

        list_rect = pygame.Rect(40, 136, 700, 470)
        pygame.draw.rect(self.screen, PANEL_DARK, list_rect, border_radius=16)
        pygame.draw.rect(self.screen, (70, 86, 128), list_rect, width=2, border_radius=16)

        row_h = 74
        for idx, record in enumerate(users):
            row = pygame.Rect(list_rect.left + 14, list_rect.top + 14 + idx * (row_h + 8), list_rect.width - 28, row_h)
            is_active = record.id == active.id
            pygame.draw.rect(
                self.screen,
                (34, 84, 62) if is_active else PANEL_LIGHT,
                row,
                border_radius=12,
            )
            if is_active:
                pygame.draw.rect(self.screen, ACCENT_GREEN, row, width=2, border_radius=12)

            name_surf = self.renderer.font_md.render(
                record.name,
                True,
                TEXT_LIGHT,
            )
            self.screen.blit(name_surf, (row.left + 16, row.top + 10))

            hint = "Активный профиль" if is_active else "Нажмите, чтобы переключиться"
            hint_surf = self.renderer.font_xs.render(hint, True, ACCENT_GREEN if is_active else TEXT_MUTED)
            self.screen.blit(hint_surf, (row.left + 16, row.top + 42))

            if not is_active:
                sel_btn = pygame.Rect(row.right - 216, row.top + 16, 130, 42)
                self.renderer.draw_button(
                    self.screen, sel_btn, "Переключить", bg_color=ACCENT_BLUE,
                    font=self.renderer.font_xs,
                )
                self._click_targets[f"select_user:{record.id}"] = sel_btn

            if self.store.can_delete_user(record.id):
                del_rect = pygame.Rect(row.right - 78, row.top + 16, 62, 42)
                pending = self.pending_delete_user_id == record.id
                self.renderer.draw_button(
                    self.screen,
                    del_rect,
                    "Точно?" if pending else "Удалить",
                    bg_color=ACCENT_RED if pending else (84, 60, 72),
                    font=self.renderer.font_xs,
                )
                self._click_targets[f"delete_user:{record.id}"] = del_rect

        panel = pygame.Rect(760, 136, 380, 470)
        pygame.draw.rect(self.screen, PANEL_DARK, panel, border_radius=16)
        pygame.draw.rect(self.screen, (70, 86, 128), panel, width=2, border_radius=16)

        title = self.renderer.font_md.render("Новый пользователь", True, ACCENT_GOLD)
        self.screen.blit(title, (panel.left + 20, panel.top + 18))

        if self.name_input_active:
            field = pygame.Rect(panel.left + 20, panel.top + 62, panel.width - 40, 48)
            pygame.draw.rect(self.screen, (18, 24, 40), field, border_radius=10)
            pygame.draw.rect(self.screen, ACCENT_GOLD, field, width=2, border_radius=10)
            shown = self.name_input_text or ""
            text_surf = self.renderer.font_sm.render(shown + "_", True, TEXT_LIGHT)
            self.screen.blit(text_surf, (field.left + 12, field.centery - text_surf.get_height() // 2))

            hint2 = self.renderer.font_xs.render(
                "Enter — создать, Esc — отмена", True, TEXT_MUTED,
            )
            self.screen.blit(hint2, (panel.left + 20, field.bottom + 12))
        else:
            new_btn = pygame.Rect(panel.left + 20, panel.top + 62, panel.width - 40, 52)
            self.renderer.draw_button(
                self.screen, new_btn, "Добавить пользователя", bg_color=ACCENT_GREEN,
                text_color=TEXT_DARK, font=self.renderer.font_sm,
            )
            self._click_targets["new_user"] = new_btn
            hint2 = self.renderer.font_xs.render(
                "Или нажмите [Enter] для ввода имени", True, TEXT_MUTED,
            )
            self.screen.blit(hint2, (panel.left + 20, panel.top + 126))

        if self.users_message:
            msg_surf = self.renderer.font_xs.render(self.users_message, True, ACCENT_GOLD)
            self.screen.blit(msg_surf, (panel.left + 20, panel.top + 168))

        info_y = panel.bottom - 150
        info_lines = [
            f"Всего пользователей: {len(users)}",
            "Прогресс каждого хранится отдельно:",
            "звёзды, серия, этапы и освоенность нот.",
        ]
        for i, line in enumerate(info_lines):
            surf = self.renderer.font_xs.render(line, True, TEXT_MUTED)
            self.screen.blit(surf, (panel.left + 20, info_y + i * 24))

        back_btn = pygame.Rect(panel.left + 20, panel.bottom - 64, panel.width - 40, 46)
        self.renderer.draw_button(
            self.screen, back_btn, "На карту курса", bg_color=ACCENT_BLUE,
            font=self.renderer.font_sm,
        )
        self._click_targets["nav_map"] = back_btn

    def _draw_summary_screen(self) -> None:
        card = pygame.Rect(180, 130, self.width - 360, 520)
        pygame.draw.rect(self.screen, PANEL_DARK, card, border_radius=22)
        pygame.draw.rect(self.screen, ACCENT_GOLD, card, width=3, border_radius=22)

        title = self.renderer.font_xl.render("Раунд завершён! Отличная работа!", True, ACCENT_GOLD)
        self.screen.blit(title, (card.centerx - title.get_width() // 2, card.top + 36))

        total_q = getattr(self, "_round_total", 8)
        stats_lines = [
            f"Правильных ответов: {self.round_correct_count} из {total_q}",
            f"Заработано звёзд за раунд: +{self.round_stars_earned} * (всего {self.profile.stars} *)",
            f"Лучшая серия подряд: {self.profile.best_streak}x",
        ]
        for i, line in enumerate(stats_lines):
            s = self.renderer.font_lg.render(line, True, TEXT_LIGHT)
            self.screen.blit(s, (card.centerx - s.get_width() // 2, card.top + 120 + i * 52))

        if self.round_unlocked_notes:
            names = ", ".join(get_note(nid).full_name for nid in self.round_unlocked_notes)
            un_surf = self.renderer.font_md.render(f"Открыты новые ноты: {names}!", True, ACCENT_GREEN)
            self.screen.blit(un_surf, (card.centerx - un_surf.get_width() // 2, card.top + 300))

        again_btn = pygame.Rect(card.centerx - 250, card.bottom - 96, 230, 54)
        self.renderer.draw_button(
            self.screen,
            again_btn,
            "Ещё один раунд ->",
            bg_color=ACCENT_GREEN,
            text_color=TEXT_DARK,
        )
        self._click_targets[f"start_stage:{self.profile.current_stage_idx}"] = again_btn

        map_btn = pygame.Rect(card.centerx + 20, card.bottom - 96, 230, 54)
        self.renderer.draw_button(
            self.screen,
            map_btn,
            "На карту уровней",
            bg_color=ACCENT_BLUE,
        )
        self._click_targets["nav_map"] = map_btn

    def _draw_encyclopedia_screen(self) -> None:
        hdr = self.renderer.font_lg.render(
            "Интерактивный справочник: нажми на любую ноту, чтобы увидеть стан, помпы и услышать унисон!",
            True,
            TEXT_LIGHT,
        )
        self.screen.blit(hdr, (40, 92))

        staff_rect = pygame.Rect(40, 134, 650, 270)
        self.renderer.draw_staff_card(
            self.screen,
            staff_rect,
            self.encyclopedia_note,
            self.encyclopedia_duration,
            subtitle=f"{self.encyclopedia_note.full_name}  |  Концертная частота: {self.encyclopedia_note.concert_freq_hz:.1f} Гц",
            highlight_color=ACCENT_BLUE,
        )

        valves_rect = pygame.Rect(714, 134, 426, 270)
        self.renderer.draw_valves_widget(
            self.screen,
            valves_rect,
            self.encyclopedia_note.valves,
            self.valve_anim,
            expected_valves=self.encyclopedia_note.valves,
            interactive_hint=False,
            harmonic_note=self.encyclopedia_note,
        )

        # Переключатели длительности и кнопка прослушивания
        for i, dur in enumerate((NoteDuration.WHOLE, NoteDuration.HALF, NoteDuration.QUARTER)):
            d_btn = pygame.Rect(40 + i * 210, 418, 198, 40)
            is_sel = dur is self.encyclopedia_duration
            self.renderer.draw_button(
                self.screen,
                d_btn,
                dur.russian_name,
                bg_color=ACCENT_GOLD if is_sel else PANEL_LIGHT,
                text_color=TEXT_DARK if is_sel else TEXT_LIGHT,
                font=self.renderer.font_xs,
            )
            self._click_targets[f"enc_dur:{dur.value}"] = d_btn

        play_btn = pygame.Rect(714, 418, 426, 40)
        self.renderer.draw_button(
            self.screen,
            play_btn,
            "Прослушать в строе Си-бемоль [Пробел]",
            bg_color=ACCENT_GREEN,
            text_color=TEXT_DARK,
            font=self.renderer.font_sm,
        )
        self._click_targets["play_current_note"] = play_btn

        # Сетка всех нот курса по этапам
        y = 474
        for stage in CURRICULUM_STAGES:
            st_lbl = self.renderer.font_xs.render(stage.title + ":", True, TEXT_MUTED)
            self.screen.blit(st_lbl, (40, y + 10))
            x = 320
            for nid in stage.note_ids:
                note = get_note(nid)
                n_btn = pygame.Rect(x, y, 118, 36)
                is_cur = note.id == self.encyclopedia_note.id
                self.renderer.draw_button(
                    self.screen,
                    n_btn,
                    f"{note.short_name} ({'-'.join(str(v) for v in note.valves)})",
                    bg_color=ACCENT_BLUE if is_cur else PANEL_DARK,
                    border_color=ACCENT_GOLD if is_cur else None,
                    font=self.renderer.font_xs,
                )
                self._click_targets[f"enc_note:{note.id}"] = n_btn
                x += 126
            y += 44

    def run(self) -> None:
        try:
            while self.running:
                dt = self.clock.tick(60) / 1000.0
                for event in pygame.event.get():
                    self.handle_event(event)
                self.update(dt)
                self.draw()
        finally:
            self.mic.stop()
            self.save_profile()
            pygame.quit()
