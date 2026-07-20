"""2D screen buffer for layer compositing.

Layers write into the buffer back-to-front. Later writes overwrite earlier
ones at the same cell. The renderer reads the final buffer to blit to
curses or ANSI output.
"""
from __future__ import annotations


class ScreenBuffer:
    """Fixed-size grid of (char, color_name) cells."""

    __slots__ = ('width', 'height', '_chars', '_colors')

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        n = width * height
        self._chars = [' '] * n
        self._colors = ['sky'] * n

    def clear(self) -> None:
        n = self.width * self.height
        self._chars[:] = [' '] * n
        self._colors[:] = ['sky'] * n

    def put(self, row: int, col: int, char: str, color: str) -> None:
        if 0 <= row < self.height and 0 <= col < self.width:
            idx = row * self.width + col
            self._chars[idx] = char
            self._colors[idx] = color

    def put_str(self, row: int, col: int, text: str, color: str) -> None:
        if row < 0 or row >= self.height:
            return
        for i, ch in enumerate(text):
            c = col + i
            if 0 <= c < self.width:
                idx = row * self.width + c
                self._chars[idx] = ch
                self._colors[idx] = color

    def get(self, row: int, col: int) -> tuple[str, str]:
        if 0 <= row < self.height and 0 <= col < self.width:
            idx = row * self.width + col
            return self._chars[idx], self._colors[idx]
        return ' ', 'sky'

    def resize(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        n = width * height
        self._chars = [' '] * n
        self._colors = ['sky'] * n
