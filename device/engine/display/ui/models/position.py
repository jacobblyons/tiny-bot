import math


class Position:
    def __init__(self, x=0.0, y=0.0):
        self.x = x
        self.y = y

    def __eq__(self, other):
        return self.x == other.x and self.y == other.y

    def as_tuple(self):
        return [self.x, self.y]

    def distance(self, target):
        xdeltasq = math.pow(target.x - self.x, 2)
        ydeltasq = math.pow(target.y - self.y, 2)
        return math.sqrt(xdeltasq + ydeltasq)

    def minus(self, target):
        return Position(int(self.x - target.x), int(self.y - target.y))

    def plus(self, target):
        return Position(int(self.x + target.x), int(self.y + target.y))

    def magnitude(self):
        return math.sqrt(math.pow(self.x, 2) + math.pow(self.y, 2))

    def normalized(self):
        mag = self.magnitude()
        if mag == 0:
            return Position(0, 0)
        return Position(self.x / mag, self.y / mag)
