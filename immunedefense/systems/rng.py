"""每局独立的随机源（可复现种子）。"""
import random


class RunRNG:
    """肉鸽内容生成专用随机源；视觉抖动/飘字仍可用全局 random。"""

    def __init__(self, seed=None):
        if seed is None:
            seed = random.SystemRandom().randint(0, 2 ** 31 - 1)
        self.seed = seed
        self._rng = random.Random(seed)

    def random(self):
        return self._rng.random()

    def randint(self, a, b):
        return self._rng.randint(a, b)

    def uniform(self, a, b):
        return self._rng.uniform(a, b)

    def choice(self, seq):
        return self._rng.choice(seq)

    def choices(self, seq, weights=None, k=1):
        return self._rng.choices(seq, weights=weights, k=k)

    def shuffle(self, seq):
        self._rng.shuffle(seq)
