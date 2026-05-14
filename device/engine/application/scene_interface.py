from engine.application.app_interface import IApp


class IScene:
    def __init__(self, app: IApp):
        raise NotImplementedError

    def OnStartup(self):
        raise NotImplementedError

    def OnUpdate(self, delta_time):
        raise NotImplementedError

    def OnDraw(self):
        raise NotImplementedError

    def OnShutdown(self):
        raise NotImplementedError

    def GetRootGroup(self):
        raise NotImplementedError
