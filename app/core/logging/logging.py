
class LoggingBackend():
    """
    Abstract Class representing different Logging Backends
    """
    def __init__(self,project_name: str):
        self.project_name = project_name
    
    async def write(logmsg : str):
        raise NotImplementedError()
