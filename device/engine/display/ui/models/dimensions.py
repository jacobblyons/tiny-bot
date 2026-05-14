class Flex:
    Freely = 1
    Locked = 2


class Dimensions:
    def __init__(self, width: int = 0, height: int = 0, flex_x=Flex.Freely, flex_y=Flex.Freely):
        self.width = width
        self.height = height
        self.flex_x = flex_x
        self.flex_y = flex_y
