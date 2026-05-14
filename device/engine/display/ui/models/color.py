class Color:
    def __init__(self, hex=None, r=0, g=0, b=0):
        if hex is not None:
            self.value = hex
        else:
            self.value = int("0x%02x%02x%02x" % (r, g, b))


class MonoColor(Color):
    MAX_VALUE: int = 0xFFFFFF

    def __init__(self, value: float = 1):
        super().__init__(hex=int(value * self.MAX_VALUE))
