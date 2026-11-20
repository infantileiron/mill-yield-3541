class Response:
    def __init__(self,content="",media_type=None,headers=None):
        self.content=content;self.media_type=media_type;self.headers=headers or {}
class JSONResponse(Response):
    def __init__(self,content=None,status_code=200,**k):super().__init__(str(content),"application/json");self.status_code=status_code
