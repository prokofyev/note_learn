from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import random
import pygame

from note_learn.audio import DEFAULT_ASSETS_DIR
from note_learn.microphone import PitchReading
from note_learn.model import Accidental, HARMONIC_PARTIAL, NoteDuration, TrumpetNote


# Цветовая палитра (тёплая, игровая и контрастная)
BG_TOP = (22, 28, 48)
BG_BOTTOM = (38, 48, 78)
CARD_BG = (250, 247, 238)
CARD_BORDER = (218, 208, 188)
PANEL_DARK = (32, 41, 66)
PANEL_LIGHT = (46, 58, 92)
TEXT_LIGHT = (245, 247, 252)
TEXT_MUTED = (172, 184, 212)
TEXT_DARK = (34, 38, 52)
ACCENT_GOLD = (255, 198, 62)
ACCENT_ORANGE = (245, 132, 54)
ACCENT_BLUE = (72, 168, 250)
ACCENT_GREEN = (58, 204, 122)
ACCENT_RED = (238, 82, 83)
ACCENT_PURPLE = (162, 118, 255)
STAFF_LINE_COLOR = (55, 60, 78)


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    size: float
    color: tuple[int, int, int]
    life: float
    max_life: float
    star: bool = False


class ParticleSystem:
    def __init__(self, rng: random.Random | None = None) -> None:
        self.particles: list[Particle] = []
        self.rng = rng or random.Random()

    def emit_burst(self, x: float, y: float, count: int = 36) -> None:
        palette = [ACCENT_GOLD, ACCENT_GREEN, ACCENT_BLUE, ACCENT_ORANGE, (255, 235, 130)]
        for _ in range(count):
            angle = self.rng.uniform(0.0, 2.0 * math.pi)
            speed = self.rng.uniform(90.0, 340.0)
            life = self.rng.uniform(0.55, 1.15)
            self.particles.append(
                Particle(
                    x=x,
                    y=y,
                    vx=math.cos(angle) * speed,
                    vy=math.sin(angle) * speed - 80.0,
                    size=self.rng.uniform(4.0, 9.0),
                    color=self.rng.choice(palette),
                    life=life,
                    max_life=life,
                    star=self.rng.random() < 0.45,
                )
            )

    def update(self, dt: float) -> None:
        alive: list[Particle] = []
        for p in self.particles:
            p.life -= dt
            if p.life > 0.0:
                p.x += p.vx * dt
                p.y += p.vy * dt
                p.vy += 380.0 * dt  # гравитация
                alive.append(p)
        self.particles = alive

    def draw(self, surface: pygame.Surface) -> None:
        for p in self.particles:
            ratio = max(0.0, min(1.0, p.life / p.max_life))
            radius = max(1, int(p.size * ratio))
            if p.star and radius >= 3:
                draw_star(surface, (int(p.x), int(p.y)), radius * 1.4, p.color)
            else:
                pygame.draw.circle(surface, p.color, (int(p.x), int(p.y)), radius)


def draw_star(
    surface: pygame.Surface,
    center: tuple[float, float],
    outer_radius: float,
    color: tuple[int, int, int],
    points: int = 5,
) -> None:
    cx, cy = center
    inner_radius = outer_radius * 0.45
    coords: list[tuple[float, float]] = []
    for i in range(points * 2):
        r = outer_radius if i % 2 == 0 else inner_radius
        angle = -math.pi / 2 + i * (math.pi / points)
        coords.append((cx + math.cos(angle) * r, cy + math.sin(angle) * r))
    pygame.draw.polygon(surface, color, coords)


class UIRenderer:
    def __init__(self, assets_dir: Path = DEFAULT_ASSETS_DIR) -> None:
        pygame.font.init()
        self.assets_dir = Path(assets_dir)
        font_candidates = [
            "Avenir Next",
            "SF Pro Display",
            "Helvetica Neue",
            "Arial",
            "DejaVu Sans",
        ]
        self.font_xs = pygame.font.SysFont(font_candidates, 15)
        self.font_sm = pygame.font.SysFont(font_candidates, 18)
        self.font_md = pygame.font.SysFont(font_candidates, 22, bold=True)
        self.font_lg = pygame.font.SysFont(font_candidates, 28, bold=True)
        self.font_xl = pygame.font.SysFont(font_candidates, 36, bold=True)

        self._accidental_raw: dict[Accidental, pygame.Surface] = {}
        self._accidental_scaled: dict[tuple[Accidental, int], pygame.Surface] = {}
        self._load_accidental_assets()

        self._clef_raw: pygame.Surface | None = None
        self._clef_scaled: dict[int, pygame.Surface] = {}
        self._load_clef_asset()

    def _load_accidental_assets(self) -> None:
        for acc in (Accidental.SHARP, Accidental.FLAT, Accidental.NATURAL):
            fname = acc.asset_filename
            if not fname:
                continue
            path = self.assets_dir / fname
            if path.exists():
                try:
                    img = pygame.image.load(str(path))
                    if pygame.display.get_surface() is not None:
                        img = img.convert_alpha()
                    self._accidental_raw[acc] = img
                except Exception:
                    pass

    def get_accidental_surface(self, accidental: Accidental, target_height: int) -> pygame.Surface | None:
        if accidental not in self._accidental_raw:
            return None
        key = (accidental, target_height)
        if key not in self._accidental_scaled:
            raw = self._accidental_raw[accidental]
            w, h = raw.get_size()
            scale = target_height / max(1, h)
            new_w = max(8, int(round(w * scale)))
            self._accidental_scaled[key] = pygame.transform.smoothscale(raw, (new_w, target_height))
        return self._accidental_scaled[key]

    def _load_clef_asset(self) -> None:
        """Загружает рисунок скрипичного ключа assets/GClef.png (если он есть)."""
        path = self.assets_dir / "GClef.png"
        if not path.exists():
            return
        try:
            img = pygame.image.load(str(path))
            if pygame.display.get_surface() is not None:
                img = img.convert_alpha()
            self._clef_raw = img
        except Exception:
            self._clef_raw = None

    def get_clef_surface(self, target_height: int) -> pygame.Surface | None:
        """Возвращает масштабированный ключ с сохранением пропорций или None, если ассета нет."""
        if self._clef_raw is None:
            return None
        target_height = max(8, int(target_height))
        if target_height not in self._clef_scaled:
            w, h = self._clef_raw.get_size()
            scale = target_height / max(1, h)
            new_w = max(4, int(round(w * scale)))
            self._clef_scaled[target_height] = pygame.transform.smoothscale(
                self._clef_raw, (new_w, target_height)
            )
        return self._clef_scaled[target_height]

    def draw_background(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        for y in range(0, height, 4):
            t = y / max(1, height)
            color = (
                int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t),
                int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t),
                int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t),
            )
            pygame.draw.rect(surface, color, (0, y, width, 4))

    def draw_button(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        text: str,
        *,
        bg_color: tuple[int, int, int] = PANEL_LIGHT,
        text_color: tuple[int, int, int] = TEXT_LIGHT,
        border_color: tuple[int, int, int] | None = None,
        hovered: bool = False,
        font: pygame.font.Font | None = None,
        icon_accidental: Accidental | None = None,
    ) -> None:
        use_font = font or self.font_md
        draw_rect = rect.inflate(4, 4) if hovered else rect
        col = tuple(min(255, c + 18) for c in bg_color) if hovered else bg_color

        # Тень
        shadow = draw_rect.move(0, 3)
        pygame.draw.rect(surface, (14, 18, 32), shadow, border_radius=12)
        pygame.draw.rect(surface, col, draw_rect, border_radius=12)
        if border_color:
            pygame.draw.rect(surface, border_color, draw_rect, width=2, border_radius=12)

        label = use_font.render(text, True, text_color)
        if icon_accidental and icon_accidental is not Accidental.NONE:
            acc_surf = self.get_accidental_surface(icon_accidental, int(draw_rect.height * 0.58))
            if acc_surf is not None:
                total_w = label.get_width() + acc_surf.get_width() + 6
                start_x = draw_rect.centerx - total_w // 2
                surface.blit(label, (start_x, draw_rect.centery - label.get_height() // 2))
                surface.blit(
                    acc_surf,
                    (start_x + label.get_width() + 6, draw_rect.centery - acc_surf.get_height() // 2),
                )
                return

        label_rect = label.get_rect(center=draw_rect.center)
        surface.blit(label, label_rect)

    def draw_staff_card(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        note: TrumpetNote | None,
        duration: NoteDuration = NoteDuration.HALF,
        *,
        subtitle: str = "",
        highlight_color: tuple[int, int, int] | None = None,
        anim_progress: float = 1.0,
        ghost_note: TrumpetNote | None = None,
    ) -> None:
        """
        Отрисовывает карточку нотного стана со скрипичным ключом, 5 линейками,
        добавочными линейками, знаком альтерации из assets/ и нотой нужной длительности.
        """
        shadow = rect.move(0, 5)
        pygame.draw.rect(surface, (15, 20, 35), shadow, border_radius=18)
        pygame.draw.rect(surface, CARD_BG, rect, border_radius=18)
        border_col = highlight_color if highlight_color else CARD_BORDER
        pygame.draw.rect(surface, border_col, rect, width=3, border_radius=18)

        line_spacing = 20  # расстояние между соседними линейками
        step_px = line_spacing // 2  # 10 px на одну диатоническую ступень
        # Позиция 1-й линейки (Ми1, staff_position = 2)
        bottom_line_y = rect.centery + int(line_spacing * 1.75)

        def pos_to_y(staff_pos: int) -> int:
            return bottom_line_y - (staff_pos - 2) * step_px

        staff_left = rect.left + 36
        staff_right = rect.right - 36

        # 5 основных линеек стана (staff_position = 2, 4, 6, 8, 10)
        for pos in (2, 4, 6, 8, 10):
            y = pos_to_y(pos)
            pygame.draw.line(surface, STAFF_LINE_COLOR, (staff_left, y), (staff_right, y), 2)

        # Двойная тактовая черта справа
        top_y = pos_to_y(10)
        bot_y = pos_to_y(2)
        pygame.draw.line(surface, STAFF_LINE_COLOR, (staff_right - 8, top_y), (staff_right - 8, bot_y), 2)
        pygame.draw.line(surface, STAFF_LINE_COLOR, (staff_right - 2, top_y), (staff_right - 2, bot_y), 5)

        # Скрипичный ключ слева: рисунок из assets/GClef.png, при отсутствии — векторный запасной.
        self._draw_staff_clef(surface, staff_left, bottom_line_y, line_spacing)

        # Если нужно показать призрачную ноту (например, то, что сейчас слышит микрофон)
        if ghost_note is not None and (note is None or ghost_note.written_midi != note.written_midi):
            self._draw_single_note_on_staff(
                surface,
                ghost_note,
                NoteDuration.QUARTER,
                note_x=rect.centerx + 75,
                pos_to_y=pos_to_y,
                line_spacing=line_spacing,
                color=(150, 160, 185),
            )

        # Основная нота
        if note is not None:
            slide_offset = int((1.0 - min(1.0, anim_progress)) * 40)
            note_x = rect.centerx + 15 + slide_offset
            note_color = highlight_color if highlight_color else TEXT_DARK
            self._draw_single_note_on_staff(
                surface,
                note,
                duration,
                note_x=note_x,
                pos_to_y=pos_to_y,
                line_spacing=line_spacing,
                color=note_color,
            )

        # Бейдж длительности в правом верхнем углу карточки
        dur_badge = self.font_sm.render(f"Длительность: {duration.russian_name}", True, (90, 96, 118))
        surface.blit(dur_badge, (rect.right - dur_badge.get_width() - 22, rect.top + 14))

        if subtitle:
            sub_surf = self.font_md.render(subtitle, True, TEXT_DARK)
            surface.blit(sub_surf, (rect.centerx - sub_surf.get_width() // 2, rect.bottom - 38))

    # Доля высоты рисунка ключа от верха до центра завитка (линейка «Соль»)
    CLEF_G_LINE_FRACTION = 0.60
    # Высота ключа в единицах расстояния между линейками стана
    CLEF_HEIGHT_IN_SPACINGS = 7.0

    def _draw_staff_clef(
        self,
        surface: pygame.Surface,
        staff_left: int,
        bottom_line_y: int,
        line_spacing: int,
    ) -> None:
        """
        Рисует скрипичный ключ слева на стане: из assets/GClef.png, выравнивая
        завиток по 2-й линейке «Соль». Если ассета нет — векторный запасной вариант.
        """
        g_line_y = bottom_line_y - line_spacing
        target_height = int(round(line_spacing * self.CLEF_HEIGHT_IN_SPACINGS))
        clef = self.get_clef_surface(target_height)
        if clef is not None:
            clef_x = staff_left + 6
            clef_y = int(round(g_line_y - clef.get_height() * self.CLEF_G_LINE_FRACTION))
            surface.blit(clef, (clef_x, clef_y))
            return
        self._draw_treble_clef(surface, staff_left + 34, bottom_line_y, line_spacing)

    def _draw_treble_clef(
        self,
        surface: pygame.Surface,
        cx: int,
        bottom_line_y: int,
        line_spacing: int,
    ) -> None:
        """Векторная отрисовка скрипичного ключа вокруг 2-й линейки (Соль)."""
        col = (44, 48, 66)
        top_y = bottom_line_y - int(line_spacing * 4.8)
        bot_y = bottom_line_y + int(line_spacing * 1.2)
        g_line_y = bottom_line_y - line_spacing  # 2-я линейка (Соль)

        # Главный вертикальный стержень с завитком внизу
        pygame.draw.line(surface, col, (cx, top_y + 10), (cx - 2, bot_y), 4)
        pygame.draw.circle(surface, col, (cx - 10, bot_y - 2), 7)

        # Верхняя петля ключа
        upper_rect = pygame.Rect(cx - 8, top_y, 24, int(line_spacing * 2.2))
        pygame.draw.arc(surface, col, upper_rect, -math.pi * 0.45, math.pi * 1.15, 4)

        # Нижняя широкая дуга и завиток вокруг линейки Соль (2-я линейка)
        belly_rect = pygame.Rect(cx - 20, g_line_y - int(line_spacing * 1.35), 38, int(line_spacing * 2.4))
        pygame.draw.arc(surface, col, belly_rect, math.pi * 0.1, math.pi * 1.85, 4)
        spiral_rect = pygame.Rect(cx - 10, g_line_y - int(line_spacing * 0.55), 22, int(line_spacing * 1.15))
        pygame.draw.arc(surface, col, spiral_rect, 0.0, math.pi * 1.65, 3)

    def _draw_single_note_on_staff(
        self,
        surface: pygame.Surface,
        note: TrumpetNote,
        duration: NoteDuration,
        *,
        note_x: int,
        pos_to_y,
        line_spacing: int,
        color: tuple[int, int, int],
    ) -> None:
        note_y = pos_to_y(note.staff_position)
        head_w = 28
        head_h = 20

        # 1. Добавочные линейки (ledger lines)
        for l_pos in note.ledger_positions:
            ly = pos_to_y(l_pos)
            pygame.draw.line(
                surface,
                STAFF_LINE_COLOR,
                (note_x - 22, ly),
                (note_x + 22, ly),
                3,
            )

        # 2. Знак альтерации слева от ноты (из assets/*.png)
        if note.accidental is not Accidental.NONE:
            acc_surf = self.get_accidental_surface(note.accidental, int(line_spacing * 2.7))
            if acc_surf is not None:
                acc_x = note_x - head_w // 2 - acc_surf.get_width() - 8
                # У бемоля пузико в нижней части знака, поэтому смещаем чуть выше
                y_shift = -int(acc_surf.get_height() * 0.58) if note.accidental is Accidental.FLAT else -int(acc_surf.get_height() * 0.50)
                surface.blit(acc_surf, (acc_x, note_y + y_shift))

        # 3. Головка ноты (целая / половинная / четвертная)
        head_surf = pygame.Surface((head_w + 8, head_h + 8), pygame.SRCALPHA)
        ellipse_rect = pygame.Rect(4, 4, head_w, head_h)
        if duration.is_filled_head:
            pygame.draw.ellipse(head_surf, color, ellipse_rect)
        else:
            pygame.draw.ellipse(head_surf, color, ellipse_rect, width=4)
        if duration is not NoteDuration.WHOLE:
            head_surf = pygame.transform.rotate(head_surf, 16)
        head_rect = head_surf.get_rect(center=(note_x, note_y))
        surface.blit(head_surf, head_rect)

        # 4. Штиль (для половинной и четвертной)
        if duration.has_stem:
            stem_len = int(line_spacing * 3.3)
            if note.stem_up:
                sx = note_x + head_w // 2 - 2
                pygame.draw.line(surface, color, (sx, note_y - 2), (sx, note_y - stem_len), 3)
            else:
                sx = note_x - head_w // 2 + 2
                pygame.draw.line(surface, color, (sx, note_y + 2), (sx, note_y + stem_len), 3)

    def draw_valves_widget(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        pressed_valves: tuple[int, int, int],
        valve_anim: list[float],
        *,
        expected_valves: tuple[int, int, int] | None = None,
        interactive_hint: bool = True,
        harmonic_note: TrumpetNote | None = None,
    ) -> list[pygame.Rect]:
        """
        Рисует блок трёх помп трубы с плавной анимацией опускания поршней.
        Возвращает список прямоугольников 3 помп для обработки кликов мышью.
        """
        pygame.draw.rect(surface, PANEL_DARK, rect, border_radius=16)
        pygame.draw.rect(surface, (70, 86, 128), rect, width=2, border_radius=16)

        title = self.font_md.render("Помпы трубы (Аппликатура)", True, TEXT_LIGHT)
        surface.blit(title, (rect.centerx - title.get_width() // 2, rect.top + 12))

        valve_rects: list[pygame.Rect] = []
        spacing = 86
        start_x = rect.centerx - spacing
        base_top = rect.top + 54

        key_hints = ("J / 1", "K / 2", "L / 3")

        # Горизонтальные соединительные трубки между цилиндрами
        pygame.draw.rect(
            surface,
            (182, 142, 62),
            (start_x - 28, base_top + 76, spacing * 2 + 56, 14),
            border_radius=6,
        )
        pygame.draw.rect(
            surface,
            (182, 142, 62),
            (start_x - 22, base_top + 114, spacing * 2 + 44, 12),
            border_radius=5,
        )

        for i in range(3):
            cx = start_x + i * spacing
            anim = max(0.0, min(1.0, valve_anim[i]))
            travel_px = int(anim * 28)

            v_rect = pygame.Rect(cx - 28, base_top, 56, 165)
            valve_rects.append(v_rect)

            is_pressed = bool(pressed_valves[i])
            body_col = (214, 170, 74) if not is_pressed else (238, 196, 88)
            if expected_valves is not None:
                if expected_valves[i] == pressed_valves[i]:
                    ring_col = ACCENT_GREEN
                else:
                    ring_col = ACCENT_RED
            else:
                ring_col = ACCENT_BLUE if is_pressed else (120, 134, 168)

            # Шток поршня и шляпка с перламутровой вставкой
            stem_top = base_top + 8 + travel_px
            pygame.draw.rect(surface, (210, 215, 228), (cx - 6, stem_top + 14, 12, 38), border_radius=4)
            cap_rect = pygame.Rect(cx - 24, stem_top, 48, 20)
            pygame.draw.rect(surface, body_col, cap_rect, border_radius=8)
            pygame.draw.rect(surface, (245, 244, 238), cap_rect.inflate(-12, -8), border_radius=6)

            # Цилиндр помпы
            cyl_rect = pygame.Rect(cx - 22, base_top + 52, 44, 102)
            pygame.draw.rect(surface, body_col, cyl_rect, border_radius=8)
            pygame.draw.rect(surface, ring_col, cyl_rect, width=3, border_radius=8)

            # Номер помпы
            num_surf = self.font_lg.render(str(i + 1), True, TEXT_DARK)
            surface.blit(num_surf, (cx - num_surf.get_width() // 2, cyl_rect.centery - num_surf.get_height() // 2 - 6))

            state_text = "НАЖАТ" if is_pressed else "откр."
            st_surf = self.font_xs.render(state_text, True, (30, 35, 48))
            surface.blit(st_surf, (cx - st_surf.get_width() // 2, cyl_rect.bottom - 24))

            # Подсказка клавиши
            kh_surf = self.font_xs.render(f"[{key_hints[i]}]", True, TEXT_MUTED)
            surface.blit(kh_surf, (cx - kh_surf.get_width() // 2, cyl_rect.bottom + 6))

        if harmonic_note is not None:
            partial = HARMONIC_PARTIAL.get(harmonic_note.written_midi, 2)
            lip_labels = {
                2: "Свободные губы (нижний регистр)",
                3: "Умеренный напор дыхания (средний регистр)",
                4: "Собранные губы (верх 1-й — начало 2-й октавы)",
                5: "Упругие губы и быстрое дыхание (2-я октава)",
                6: "Высокий регистр — быстрая струя воздуха!",
                7: "Высокий регистр — собранный амбушюр!",
                8: "Вершина диапазона (До 3-й октавы)!",
            }
            lip_txt = self.font_xs.render(
                f"Гармоника #{partial}: {lip_labels.get(partial, '')}",
                True,
                ACCENT_GOLD,
            )
            surface.blit(lip_txt, (rect.centerx - lip_txt.get_width() // 2, rect.bottom - 44))

        if interactive_hint:
            hint = self.font_xs.render(
                "Кликай мышкой или нажимай клавиши J, K, L (или 1, 2, 3) | 0 — открыть все",
                True,
                TEXT_MUTED,
            )
            surface.blit(hint, (rect.centerx - hint.get_width() // 2, rect.bottom - 22))

        return valve_rects

    def draw_tuner_and_hold_widget(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        reading: PitchReading,
        hold_progress: float,
        target_note: TrumpetNote,
        duration: NoteDuration,
        *,
        mic_available: bool = True,
    ) -> None:
        """
        Отрисовывает живой тюнер микрофона (Ниже <-- Точно --> Выше)
        и шкалу удержания длительности ноты.
        """
        pygame.draw.rect(surface, PANEL_DARK, rect, border_radius=16)
        pygame.draw.rect(surface, (70, 86, 128), rect, width=2, border_radius=16)

        title = self.font_md.render("Тюнер микрофона (Строй Си-бемоль)", True, TEXT_LIGHT)
        surface.blit(title, (rect.centerx - title.get_width() // 2, rect.top + 12))

        # Текущая слышимая нота
        if reading.nearest_note is not None and reading.freq_hz is not None:
            detected_str = f"Слышу: {reading.nearest_note.full_name} ({reading.freq_hz:.0f} Гц)"
            det_col = ACCENT_GREEN if reading.is_on_target else ACCENT_GOLD
        else:
            detected_str = (
                f"Сыграй в микрофон: {target_note.full_name}"
                if mic_available
                else "Микрофон не активен — удерживай [Пробел] для теста"
            )
            det_col = TEXT_MUTED

        det_surf = self.font_sm.render(detected_str, True, det_col)
        surface.blit(det_surf, (rect.centerx - det_surf.get_width() // 2, rect.top + 46))

        # Полоса отклонения интонации (-100 .. +100 центов)
        gauge_rect = pygame.Rect(rect.left + 28, rect.top + 82, rect.width - 56, 28)
        pygame.draw.rect(surface, (20, 26, 44), gauge_rect, border_radius=14)

        # Зелёная зона точного попадания в центре
        exact_w = int(gauge_rect.width * 0.32)
        exact_rect = pygame.Rect(
            gauge_rect.centerx - exact_w // 2,
            gauge_rect.top + 3,
            exact_w,
            gauge_rect.height - 6,
        )
        pygame.draw.rect(surface, (36, 112, 76), exact_rect, border_radius=10)
        pygame.draw.line(
            surface,
            ACCENT_GREEN,
            (gauge_rect.centerx, gauge_rect.top),
            (gauge_rect.centerx, gauge_rect.bottom),
            2,
        )

        # Индикатор (стрелка-бегунок)
        if reading.cents_from_target is not None:
            norm = max(-1.0, min(1.0, reading.cents_from_target / 100.0))
            marker_x = int(gauge_rect.centerx + norm * (gauge_rect.width // 2 - 12))
            marker_col = ACCENT_GREEN if reading.is_on_target else ACCENT_ORANGE
            pygame.draw.circle(surface, marker_col, (marker_x, gauge_rect.centery), 11)
            pygame.draw.circle(surface, TEXT_LIGHT, (marker_x, gauge_rect.centery), 11, width=2)

        low_lbl = self.font_xs.render("<< Ниже", True, TEXT_MUTED)
        ok_lbl = self.font_xs.render("ТОЧНО", True, ACCENT_GREEN)
        high_lbl = self.font_xs.render("Выше >>", True, TEXT_MUTED)
        surface.blit(low_lbl, (gauge_rect.left, gauge_rect.bottom + 4))
        surface.blit(ok_lbl, (gauge_rect.centerx - ok_lbl.get_width() // 2, gauge_rect.bottom + 4))
        surface.blit(high_lbl, (gauge_rect.right - high_lbl.get_width(), gauge_rect.bottom + 4))

        # Полоса удержания длительности ноты
        hold_top = gauge_rect.bottom + 36
        hold_lbl = self.font_sm.render(
            f"Удержание длительности ({duration.russian_name}): {int(hold_progress * 100)}%",
            True,
            TEXT_LIGHT,
        )
        surface.blit(hold_lbl, (rect.left + 28, hold_top))

        bar_rect = pygame.Rect(rect.left + 28, hold_top + 26, rect.width - 56, 26)
        pygame.draw.rect(surface, (20, 26, 44), bar_rect, border_radius=13)
        if hold_progress > 0.0:
            fill_w = max(12, int(bar_rect.width * min(1.0, hold_progress)))
            fill_rect = pygame.Rect(bar_rect.left, bar_rect.top, fill_w, bar_rect.height)
            pygame.draw.rect(surface, ACCENT_GREEN, fill_rect, border_radius=13)
        pygame.draw.rect(surface, (90, 110, 155), bar_rect, width=2, border_radius=13)

        # Деления долей (beats)
        beats = duration.beats
        for b in range(1, beats):
            bx = bar_rect.left + int(bar_rect.width * (b / beats))
            pygame.draw.line(surface, TEXT_LIGHT, (bx, bar_rect.top + 3), (bx, bar_rect.bottom - 3), 2)
