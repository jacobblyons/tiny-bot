from engine.display.ui.elements import UIElement


class IView:
    def __init__(self, root_group):
        raise NotImplementedError("IView is an interface, do not instantiate it")

    def getElement(self) -> UIElement:
        raise NotImplementedError("IView is an interface, do not instantiate it")
