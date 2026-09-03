"""场景基类与场景管理（栈式切换，策划书 4.4）。"""


class Scene:
    def __init__(self, game):
        self.game = game

    def handle_events(self, events):
        pass

    def update(self, dt):
        pass

    def render(self, screen):
        pass


class SceneManager:
    def __init__(self):
        self._stack = []

    def push(self, scene):
        self._stack.append(scene)

    def pop(self):
        return self._stack.pop() if self._stack else None

    def switch(self, scene):
        if self._stack:
            self._stack.pop()
        self._stack.append(scene)

    def current(self):
        return self._stack[-1] if self._stack else None
