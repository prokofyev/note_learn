import os
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from note_learn.audio import DEFAULT_ASSETS_DIR
from note_learn.model import NoteDuration, get_note
from note_learn.renderer import UIRenderer


def test_clef_asset_loaded_with_preserved_aspect_ratio():
    renderer = UIRenderer(assets_dir=DEFAULT_ASSETS_DIR)
    assert renderer.get_clef_surface(140) is not None

    raw = renderer._clef_raw
    assert raw is not None
    raw_w, raw_h = raw.get_size()

    for target_height in (60, 140):
        scaled = renderer.get_clef_surface(target_height)
        assert scaled is not None
        width, height = scaled.get_size()
        assert height == target_height
        # Пропорции рисунка сохраняются при масштабировании.
        assert abs((width / height) - (raw_w / raw_h)) < 0.05


def test_clef_surface_is_cached_per_height():
    renderer = UIRenderer(assets_dir=DEFAULT_ASSETS_DIR)
    first = renderer.get_clef_surface(120)
    second = renderer.get_clef_surface(120)
    assert first is second


def test_staff_card_falls_back_to_vector_clef_without_asset(tmp_path: Path):
    pygame.display.set_mode((64, 64))
    empty_assets = tmp_path / "assets"
    empty_assets.mkdir()
    renderer = UIRenderer(assets_dir=empty_assets)

    assert renderer.get_clef_surface(140) is None

    surface = pygame.Surface((660, 300))
    # При отсутствии GClef.png стан всё равно рисуется (векторный запасной ключ).
    renderer.draw_staff_card(
        surface,
        pygame.Rect(10, 10, 640, 280),
        get_note("C4"),
        NoteDuration.WHOLE,
        subtitle="До первой октавы",
    )
    assert surface.get_at((40, 150)) is not None


def test_staff_card_renders_with_clef_asset():
    pygame.display.set_mode((64, 64))
    renderer = UIRenderer(assets_dir=DEFAULT_ASSETS_DIR)
    assert renderer.get_clef_surface(140) is not None

    surface = pygame.Surface((660, 300))
    renderer.draw_staff_card(
        surface,
        pygame.Rect(10, 10, 640, 280),
        get_note("B4"),
        NoteDuration.HALF,
        subtitle="Си первой октавы",
    )
    # В левой части карточки (где стоит ключ) есть нарисованные пиксели.
    left_region = [surface.get_at((x, y)) for x in range(40, 90) for y in range(60, 240)]
    assert any(px[:3] != surface.get_at((5, 5))[:3] for px in left_region)
