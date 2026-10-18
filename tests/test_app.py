from pathlib import Path
import os
import pygame

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from note_learn.app import AppScreen, TrumpetLearningApp
from note_learn.curriculum import ExerciseType
from note_learn.model import get_note
from note_learn.profile_store import ProfileStore


def _keydown(key: int, unicode: str = "") -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode=unicode, mod=0, scancode=0)


def _make_app(tmp_path: Path) -> tuple[TrumpetLearningApp, ProfileStore]:
    store = ProfileStore(root=tmp_path / "store", legacy_profile_path=tmp_path / "missing.json")
    app = TrumpetLearningApp(
        save_path=tmp_path / "single.json",
        audio_enabled=False,
        headless=True,
        store=store,
    )
    return app, store


def test_app_screens_and_round_flow(tmp_path: Path):
    save_file = tmp_path / "profile.json"
    app = TrumpetLearningApp(save_path=save_file, audio_enabled=False, headless=True)
    try:
        # 1. Главный экран карты курса отрисовывается и регистрирует кнопки
        app.update(0.016)
        app.draw()
        assert app.current_screen is AppScreen.MAP
        assert "start_stage:0" in app._click_targets

        # 2. Запускаем раунд из 3 заданий
        app.start_round(stage_idx=0, round_len=3)
        assert app.current_screen is AppScreen.EXERCISE
        assert app.current_exercise is not None
        assert app.current_exercise.exercise_type is ExerciseType.INTRO

        # Завершаем все 3 задания раунда
        for _ in range(3):
            app.update(0.05)
            app.draw()
            ex = app.current_exercise
            assert ex is not None
            if ex.exercise_type is ExerciseType.INTRO:
                app.complete_intro_card()
            elif ex.exercise_type is ExerciseType.STAFF_TO_VALVES:
                app.pressed_valves = list(ex.target_note.valves)
                app.submit_valves_answer()
            elif ex.exercise_type in (ExerciseType.STAFF_TO_NAME, ExerciseType.EAR_TO_NOTE):
                app.submit_option_answer(ex.target_note)
            elif ex.exercise_type is ExerciseType.PLAY_TRUMPET:
                app._trigger_action("simulate_mic_success")
            assert app.answered is True
            app.advance_after_answer()

        # 3. После завершения раунда открывается экран наград SUMMARY
        assert app.current_screen is AppScreen.SUMMARY
        app.draw()
        assert save_file.exists()

        # 4. Проверяем интерактивный справочник всех нот и знаков альтерации
        app._trigger_action("nav_encyclopedia")
        assert app.current_screen is AppScreen.ENCYCLOPEDIA
        app._trigger_action("enc_note:Bb4")
        assert app.encyclopedia_note.id == "Bb4"
        app._trigger_action("enc_dur:whole")
        app.update(0.05)
        app.draw()
    finally:
        app.mic.stop()
        pygame.quit()


def test_explicit_save_path_keeps_single_profile_mode(tmp_path: Path):
    save_file = tmp_path / "profile.json"
    app = TrumpetLearningApp(save_path=save_file, audio_enabled=False, headless=True)
    try:
        assert app.store is None
        app.start_round(stage_idx=0, round_len=1)
        app.complete_intro_card()
        assert save_file.exists()
    finally:
        app.mic.stop()
        pygame.quit()


def test_users_screen_renders_and_registers_targets(tmp_path: Path):
    app, store = _make_app(tmp_path)
    try:
        store.create_user("Маша")
        app.profile = store.active_profile()
        app.current_screen = AppScreen.USERS
        app.draw()
        assert "nav_users" in app._click_targets
        assert "new_user" in app._click_targets
        assert "nav_map" in app._click_targets
        assert any(t.startswith("select_user:") for t in app._click_targets)
        assert any(t.startswith("delete_user:") for t in app._click_targets)
    finally:
        app.mic.stop()
        pygame.quit()


def test_top_bar_shows_profile_button_on_every_screen(tmp_path: Path):
    app, store = _make_app(tmp_path)
    try:
        for screen in (AppScreen.MAP, AppScreen.ENCYCLOPEDIA, AppScreen.USERS):
            app.current_screen = screen
            app.draw()
            assert "nav_users" in app._click_targets
        app._trigger_action("nav_users")
        assert app.current_screen is AppScreen.USERS
    finally:
        app.mic.stop()
        pygame.quit()


def test_create_user_through_inline_input(tmp_path: Path):
    app, store = _make_app(tmp_path)
    try:
        app._trigger_action("nav_users")
        app.handle_event(_keydown(pygame.K_RETURN))
        assert app.name_input_active is True
        for char in "Маша":
            app.handle_event(_keydown(pygame.K_a, char))
        assert app.name_input_text == "Маша"
        app.handle_event(_keydown(pygame.K_RETURN))
        assert app.name_input_active is False
        assert [u.name for u in store.users()] == ["Ученик", "Маша"]
        assert store.active_user().name == "Маша"
        assert app.current_screen is AppScreen.MAP
        # Прогресс нового пользователя чистый независимо от прежнего.
        assert app.profile.stars == 0
    finally:
        app.mic.stop()
        pygame.quit()


def test_empty_name_is_rejected(tmp_path: Path):
    app, store = _make_app(tmp_path)
    try:
        app._trigger_action("nav_users")
        app.handle_event(_keydown(pygame.K_RETURN))
        app.handle_event(_keydown(pygame.K_RETURN))
        assert len(store.users()) == 1
        assert app.users_message
    finally:
        app.mic.stop()
        pygame.quit()


def test_delete_requires_confirmation_and_can_be_cancelled(tmp_path: Path):
    app, store = _make_app(tmp_path)
    try:
        default_id = store.active_user().id
        masha = store.create_user("Маша")
        app.profile = store.active_profile()

        app._trigger_action(f"delete_user:{masha.id}")
        assert app.pending_delete_user_id == masha.id
        assert {u.id for u in store.users()} == {default_id, masha.id}

        # Повторный вход на экран отменяет подтверждение.
        app._trigger_action("nav_users")
        assert app.pending_delete_user_id is None
        assert {u.id for u in store.users()} == {default_id, masha.id}

        app._trigger_action(f"delete_user:{masha.id}")
        app._trigger_action(f"delete_user:{masha.id}")
        assert {u.id for u in store.users()} == {default_id}
    finally:
        app.mic.stop()
        pygame.quit()


def test_switching_user_loads_that_users_progress(tmp_path: Path):
    app, store = _make_app(tmp_path)
    try:
        first_id = store.active_user().id
        profile_a = app.profile
        for _ in range(3):
            profile_a.record_answer("C4", True, ExerciseType.STAFF_TO_VALVES)
        app.save_profile()
        a_stars = profile_a.stars

        second = store.create_user("Второй")
        app.profile = store.active_profile()
        app.profile.record_answer("D4", True, ExerciseType.INTRO)
        app.save_profile()
        b_stars = app.profile.stars
        assert b_stars != a_stars

        app._trigger_action("nav_users")
        app._trigger_action(f"select_user:{first_id}")
        assert store.active_user().id == first_id
        assert app.profile.stars == a_stars
        assert app.profile.note_progress["D4"].mastery == 0.0

        app._trigger_action("nav_users")
        app._trigger_action(f"select_user:{second.id}")
        assert app.profile.stars == b_stars
    finally:
        app.mic.stop()
        pygame.quit()


def test_users_screen_in_single_profile_mode_is_read_only(tmp_path: Path):
    app = TrumpetLearningApp(save_path=tmp_path / "single.json", audio_enabled=False, headless=True)
    try:
        assert app.store is None
        app.current_screen = AppScreen.USERS
        app.draw()
        assert "nav_users" in app._click_targets
        assert "new_user" not in app._click_targets

        # Enter не открывает ввод имени, когда хранилища профилей нет.
        app.handle_event(_keydown(pygame.K_RETURN))
        assert app.name_input_active is False
    finally:
        app.mic.stop()
        pygame.quit()


def test_headless_mode_does_not_require_fullscreen(tmp_path: Path):
    app = TrumpetLearningApp(save_path=tmp_path / "p.json", audio_enabled=False, headless=True)
    try:
        # В headless-режиме полноэкранный режим не включается и поверхность остаётся полотном вёрстки.
        assert app.fullscreen is False
        assert app.screen.get_size() == (1180, 760)
        assert not (app.screen.get_flags() & pygame.FULLSCREEN)
    finally:
        app.mic.stop()
        pygame.quit()


def test_f11_toggles_fullscreen_without_breaking_draw(tmp_path: Path):
    app = TrumpetLearningApp(
        save_path=tmp_path / "p.json",
        audio_enabled=False,
        headless=True,
        fullscreen=False,
    )
    try:
        # В headless-режиме переключение безопасно и не включает полный экран.
        app.handle_event(_keydown(pygame.K_F11))
        assert app.fullscreen is False
        app.draw()

        # Прямой вызов set_fullscreen также не ломает отрисовку.
        app.set_fullscreen(True)
        app.set_fullscreen(False)
        assert app.fullscreen is False
        app.draw()
    finally:
        app.mic.stop()
        pygame.quit()


def test_esc_still_navigates_after_fullscreen_toggle(tmp_path: Path):
    app = TrumpetLearningApp(
        save_path=tmp_path / "p.json",
        audio_enabled=False,
        headless=True,
        fullscreen=False,
    )
    try:
        app._trigger_action("nav_encyclopedia")
        assert app.current_screen is AppScreen.ENCYCLOPEDIA
        app.handle_event(_keydown(pygame.K_F11))
        app.handle_event(_keydown(pygame.K_ESCAPE))
        # Esc по-прежнему выходит на карту курса, а не завершает приложение.
        assert app.current_screen is AppScreen.MAP
        assert app.running is True
    finally:
        app.mic.stop()
        pygame.quit()


def test_screens_still_render_in_fullscreen_layout(tmp_path: Path):
    app, store = _make_app(tmp_path)
    try:
        app.start_round(stage_idx=0, round_len=2)
        for screen in (AppScreen.EXERCISE, AppScreen.ENCYCLOPEDIA, AppScreen.MAP, AppScreen.USERS):
            app.current_screen = screen
            app.update(0.016)
            app.draw()
            assert "nav_users" in app._click_targets
    finally:
        app.mic.stop()
        pygame.quit()
