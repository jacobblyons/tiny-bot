class IApp:
    def __init__(self):
        raise NotImplementedError

    def SwitchScene(self, scene):
        raise NotImplementedError

    def Run(self):
        raise NotImplementedError

    def GetKeyboard(self):
        raise NotImplementedError

    def GetTrackball(self):
        raise NotImplementedError
