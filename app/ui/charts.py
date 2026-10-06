from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import cairo

from app.ui import theme
from app.ui.gtk import Gdk, Gtk


def _rgb(color: str) -> tuple[float, float, float]:
    value = color.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return (
        int(value[0:2], 16) / 255.0,
        int(value[2:4], 16) / 255.0,
        int(value[4:6], 16) / 255.0,
    )


@dataclass
class Series:
    label: str
    values: list[float]
    color: str = theme.AMBER
    dashed: bool = False
    width: float = 1.5


@dataclass
class ChartData:
    dates: list[str] = field(default_factory=list)
    series: list[Series] = field(default_factory=list)
    candles: list[dict[str, Any]] | None = None
    volumes: list[float] | None = None
    sub: list[Series] = field(default_factory=list)
    sub_guides: list[float] = field(default_factory=list)
    sub_min: float | None = None
    sub_max: float | None = None
    legend: bool = True
    empty_text: str = "no data"
    y_fmt: Callable[[float], str] = lambda v: f"{v:,.2f}"


class Chart(Gtk.DrawingArea):
    def __init__(self, height: int = 280):
        super().__init__()
        self.data = ChartData()
        self.height = height
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.add_css_class("ft-panel")
        self._hover_index: int | None = None
        self._plot: tuple[float, float, float, float] | None = None
        self._size = (0, 0)
        self.set_draw_func(self._on_draw)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

    def set_data(self, data: ChartData) -> None:
        self.data = data
        self._hover_index = None
        self.queue_draw()

    def clear(self, text: str = "no data") -> None:
        self.data = ChartData(empty_text=text)
        self.queue_draw()

    @staticmethod
    def _values() -> list[float]:
        return []

    def _main_extent(self) -> tuple[float, float]:
        data = self.data
        values: list[float] = []
        if data.candles:
            for candle in data.candles:
                for key in ("high", "low", "open", "close"):
                    value = candle.get(key)
                    if isinstance(value, (int, float)) and not math.isnan(value):
                        values.append(float(value))
        for series in data.series:
            values.extend(v for v in series.values if v is not None and not math.isnan(v))
        if not values:
            return 0.0, 1.0
        low, high = min(values), max(values)
        if low == high:
            low, high = low - 1.0, high + 1.0
        pad = (high - low) * 0.06
        return low - pad, high + pad

    def _sub_extent(self) -> tuple[float, float]:
        data = self.data
        values: list[float] = []
        for series in data.sub:
            values.extend(v for v in series.values if v is not None and not math.isnan(v))
        low = min(values) if values else 0.0
        high = max(values) if values else 100.0
        if data.sub_min is not None:
            low = data.sub_min
        if data.sub_max is not None:
            high = data.sub_max
        if low == high:
            low, high = low - 1.0, high + 1.0
        pad = (high - low) * 0.08
        return low - pad, high + pad

    def _count(self) -> int:
        data = self.data
        if data.candles:
            return len(data.candles)
        if data.series:
            return max((len(s.values) for s in data.series), default=0)
        return 0

    def _on_draw(
        self, _area: Gtk.DrawingArea, ctx: cairo.Context, width: int, height: int
    ) -> None:
        self._size = (width, height)
        if width <= 10 or height <= 10:
            return
        count = self._count()
        if count == 0:
            self._draw_text(ctx, self.data.empty_text, width, height, _rgb(theme.DIM))
            return

        right = 62.0
        left = 8.0
        top = 16.0
        bottom = 20.0
        sub_gap = 8.0
        has_sub = bool(self.data.sub)
        total_h = height - top - bottom
        sub_h = total_h * 0.26 if has_sub else 0.0
        main_h = total_h - (sub_h + sub_gap if has_sub else 0.0)
        plot_w = width - left - right

        ctx.set_source_rgb(*_rgb(theme.BG))
        ctx.paint()

        x0, y0 = left, top
        x1, y1 = left + plot_w, top + main_h
        self._plot = (x0, y0, x1, y1)

        low, high = self._main_extent()

        def sx(index: float) -> float:
            if count <= 1:
                return x0 + plot_w / 2
            return x0 + index * (plot_w / (count - 1))

        def sy(value: float) -> float:
            return y1 - (value - low) / (high - low) * main_h

        self._grid(ctx, x0, y0, x1, y1, low, high, sy)
        if self.data.volumes:
            self._volumes(ctx, x0, y0, x1, y1)
        if self.data.candles:
            self._candles(ctx, sx, sy, x0, y1)
        else:
            for series in self.data.series:
                self._line(ctx, series, sx, sy)
        self._x_axis(ctx, sx, x0, x1, y1, width, height)

        if has_sub:
            sy0 = y1 + sub_gap
            sy1 = sy0 + sub_h
            slow, shigh = self._sub_extent()

            def ssy(value: float) -> float:
                return sy1 - (value - slow) / (shigh - slow) * sub_h

            self._grid(ctx, x0, sy0, x1, sy1, slow, shigh, ssy)
            for guide in self.data.sub_guides:
                if slow <= guide <= shigh:
                    gy = ssy(guide)
                    ctx.set_source_rgba(*_rgb(theme.DIM), 0.5)
                    ctx.set_dash([3, 3])
                    ctx.move_to(x0, gy)
                    ctx.line_to(x1, gy)
                    ctx.stroke()
                    ctx.set_dash([])
            for series in self.data.sub:
                self._line(ctx, series, sx, ssy)

        if self.data.legend:
            self._legend(ctx, x0 + 6, y0 + 12)
        if self._hover_index is not None and 0 <= self._hover_index < count:
            self._crosshair(ctx, sx, sy, x0, y0, x1, y1, count, low, high, width, height)
        else:
            self._last_value(ctx, x1, sy, count, width)

    def _grid(
        self,
        ctx: cairo.Context,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        low: float,
        high: float,
        sy: Callable[[float], float],
    ) -> None:
        ctx.set_font_size(9)
        steps = 4
        for i in range(steps + 1):
            value = low + (high - low) * i / steps
            y = sy(value)
            ctx.set_source_rgba(*_rgb(theme.BORDER), 0.7)
            ctx.set_line_width(1)
            ctx.move_to(x0, y)
            ctx.line_to(x1, y)
            ctx.stroke()
            ctx.set_source_rgb(*_rgb(theme.DIM))
            label = self.data.y_fmt(value)
            ctx.move_to(x1 + 6, y + 3)
            ctx.show_text(label)

    def _line(
        self,
        ctx: cairo.Context,
        series: Series,
        sx: Callable[[float], float],
        sy: Callable[[float], float],
    ) -> None:
        values = series.values
        if not values:
            return
        ctx.set_source_rgb(*_rgb(series.color))
        ctx.set_line_width(series.width)
        if series.dashed:
            ctx.set_dash([5, 4])
        started = False
        for index, value in enumerate(values):
            if value is None or (isinstance(value, float) and math.isnan(value)):
                started = False
                continue
            x, y = sx(index), sy(float(value))
            if not started:
                ctx.move_to(x, y)
                started = True
            else:
                ctx.line_to(x, y)
        ctx.stroke()
        ctx.set_dash([])

    def _candles(
        self,
        ctx: cairo.Context,
        sx: Callable[[float], float],
        sy: Callable[[float], float],
        x0: float,
        y1: float,
    ) -> None:
        candles = self.data.candles or []
        count = max(1, len(candles))
        plot_width = max(1.0, self._size[0] - x0 - 62)
        step = plot_width / max(1, count)
        body = max(1.0, min(9.0, step * 0.7))
        for index, candle in enumerate(candles):
            open_ = candle.get("open")
            close = candle.get("close")
            high = candle.get("high")
            low = candle.get("low")
            if None in (open_, close, high, low):
                continue
            up = float(close) >= float(open_)
            color = _rgb(theme.GREEN if up else theme.RED)
            x = sx(index)
            ctx.set_source_rgb(*color)
            ctx.set_line_width(1)
            ctx.move_to(x, sy(float(high)))
            ctx.line_to(x, sy(float(low)))
            ctx.stroke()
            yo, yc = sy(float(open_)), sy(float(close))
            top, bottom = min(yo, yc), max(yo, yc)
            if bottom - top < 1:
                bottom = top + 1
            if up:
                ctx.set_line_width(1)
                ctx.rectangle(x - body / 2, top, body, bottom - top)
                ctx.stroke()
            else:
                ctx.rectangle(x - body / 2, top, body, bottom - top)
                ctx.fill()

    def _volumes(
        self,
        ctx: cairo.Context,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> None:
        volumes = [v for v in self.data.volumes if v]
        if not volumes:
            return
        candles = self.data.candles
        total = len(candles) if candles else len(self.data.volumes or [])
        if total == 0:
            return
        peak = max(volumes) or 1.0
        step = (x1 - x0) / total
        body = max(1.0, step * 0.6)
        max_h = (y1 - y0) * 0.22
        ctx.set_source_rgba(*_rgb(theme.BLUE), 0.35)
        series = self.data.volumes or []
        for index, value in enumerate(series):
            if not value:
                continue
            x = x0 + (index + 0.5) * step
            h = float(value) / peak * max_h
            ctx.rectangle(x - body / 2, y1 - h, body, h)
        ctx.fill()

    def _x_axis(
        self,
        ctx: cairo.Context,
        sx: Callable[[float], float],
        x0: float,
        x1: float,
        y1: float,
        width: float,
        height: float,
    ) -> None:
        dates = self.data.dates
        count = self._count()
        if not dates or count == 0:
            return
        ctx.set_font_size(9)
        ticks = max(2, min(7, int((x1 - x0) // 90)))
        for i in range(ticks + 1):
            index = int(round(i * (count - 1) / max(1, ticks)))
            if index >= len(dates):
                index = len(dates) - 1
            x = sx(index)
            label = dates[index]
            if len(label) > 10:
                label = label[10:]
            ctx.set_source_rgb(*_rgb(theme.DIM))
            extents = ctx.text_extents(label)
            tx = min(max(x - extents.width / 2, x0), x1 - extents.width)
            ctx.move_to(tx, height - 6)
            ctx.show_text(label)

    def _legend(self, ctx: cairo.Context, x: float, y: float) -> None:
        entries: list[Series] = []
        if self.data.candles:
            entries.append(Series("OHLC", [], theme.GREEN))
        entries.extend(self.data.series)
        entries.extend(self.data.sub)
        ctx.set_font_size(9)
        cursor = x
        for entry in entries:
            ctx.set_source_rgb(*_rgb(entry.color))
            ctx.rectangle(cursor, y - 6, 12, 3)
            ctx.fill()
            cursor += 16
            ctx.set_source_rgb(*_rgb(theme.FG))
            ctx.move_to(cursor, y - 1)
            ctx.show_text(entry.label)
            cursor += ctx.text_extents(entry.label).width + 14

    def _last_value(
        self,
        ctx: cairo.Context,
        x1: float,
        sy: Callable[[float], float],
        count: int,
        width: float,
    ) -> None:
        series = self.data.series
        if not series or not series[0].values:
            return
        value = series[0].values[-1]
        if value is None:
            return
        y = sy(float(value))
        ctx.set_source_rgb(*_rgb(series[0].color))
        ctx.arc(x1, y, 2.5, 0, math.pi * 2)
        ctx.fill()
        label = self.data.y_fmt(float(value))
        ctx.set_font_size(9)
        extents = ctx.text_extents(label)
        ctx.set_source_rgb(*_rgb(theme.PANEL))
        ctx.rectangle(x1 + 3, y - extents.height / 2 - 2, extents.width + 6, extents.height + 4)
        ctx.fill()
        ctx.set_source_rgb(*_rgb(series[0].color))
        ctx.move_to(x1 + 6, y + extents.height / 2 - 1)
        ctx.show_text(label)

    def _crosshair(
        self,
        ctx: cairo.Context,
        sx: Callable[[float], float],
        sy: Callable[[float], float],
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        count: int,
        low: float,
        high: float,
        width: float,
        height: float,
    ) -> None:
        index = self._hover_index or 0
        x = sx(index)
        ctx.set_source_rgba(*_rgb(theme.DIM), 0.7)
        ctx.set_dash([3, 3])
        ctx.set_line_width(1)
        ctx.move_to(x, y0)
        ctx.line_to(x, y1)
        ctx.stroke()
        ctx.set_dash([])
        lines: list[str] = []
        if self.data.dates and index < len(self.data.dates):
            lines.append(self.data.dates[index])
        if self.data.candles and index < len(self.data.candles):
            candle = self.data.candles[index]
            lines.append(
                f"O {self.data.y_fmt(float(candle.get('open') or 0))}  "
                f"H {self.data.y_fmt(float(candle.get('high') or 0))}  "
                f"L {self.data.y_fmt(float(candle.get('low') or 0))}  "
                f"C {self.data.y_fmt(float(candle.get('close') or 0))}"
            )
        for series in self.data.series:
            if index < len(series.values) and series.values[index] is not None:
                lines.append(f"{series.label}: {self.data.y_fmt(float(series.values[index]))}")
        if not lines:
            return
        ctx.set_font_size(9)
        box_w = max(ctx.text_extents(line).width for line in lines) + 12
        box_h = len(lines) * 12 + 8
        bx = x0 + 4
        by = y0 + 2
        ctx.set_source_rgba(*_rgb(theme.PANEL), 0.92)
        ctx.rectangle(bx, by, box_w, box_h)
        ctx.fill()
        ctx.set_source_rgb(*_rgb(theme.FG))
        for i, line in enumerate(lines):
            ctx.move_to(bx + 6, by + 14 + i * 12)
            ctx.show_text(line)

    def _on_motion(self, _controller: Gtk.EventControllerMotion, x: float, y: float) -> None:
        count = self._count()
        if count == 0 or self._plot is None:
            return
        x0, _y0, x1, _y1 = self._plot
        if x < x0 or x > x1:
            self._hover_index = None
        else:
            ratio = (x - x0) / max(1.0, x1 - x0)
            self._hover_index = max(0, min(count - 1, int(round(ratio * (count - 1)))))
        self.queue_draw()

    def _on_leave(self, _controller: Gtk.EventControllerMotion) -> None:
        self._hover_index = None
        self.queue_draw()

    @staticmethod
    def _draw_text(ctx: cairo.Context, text: str, width: int, height: int, color: tuple) -> None:
        ctx.set_source_rgb(*_rgb(theme.BG))
        ctx.paint()
        ctx.set_source_rgb(*color)
        ctx.set_font_size(11)
        extents = ctx.text_extents(text)
        ctx.move_to((width - extents.width) / 2, (height + extents.height) / 2)
        ctx.show_text(text)


def history_to_chart(history: Any, label: str = "close") -> ChartData:
    candles = [
        {"open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
        for c in history.candles
    ]
    volumes = [float(c.volume or 0) for c in history.candles]
    return ChartData(
        dates=[c.ts for c in history.candles],
        candles=candles,
        volumes=volumes,
        series=[Series(label, [c.close for c in history.candles], theme.AMBER)],
    )
