class BaseHTTPMiddleware:
    def __init__(self,app=None,*a,**k):self.app=app
    async def dispatch(self,request,call_next):return await call_next(request)
