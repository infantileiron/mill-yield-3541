class HTTPException(Exception):
    def __init__(self,status_code=500,detail="error"):
        self.status_code=status_code;self.detail=detail;super().__init__(detail)
class Request:
    def __init__(self):self.state=type("S",(),{})();self.client=None;self.url=None;self.method="GET"
class APIRouter:
    def __init__(self,*a,**k):self.routes=[]
    def _add(self,method,path):
        def deco(fn):self.routes.append((method,path,fn));return fn
        return deco
    def get(self,path,*a,**k):return self._add("GET",path)
    def post(self,path,*a,**k):return self._add("POST",path)
    def put(self,path,*a,**k):return self._add("PUT",path)
    def delete(self,path,*a,**k):return self._add("DELETE",path)
class FastAPI:
    def __init__(self,*a,**k):self.routes=[];self.middlewares=[]
    def include_router(self,r,*a,**k):self.routes.extend(getattr(r,"routes",[]))
    def add_middleware(self,*a,**k):self.middlewares.append(a)
    def get(self,path,*a,**k):
        def deco(fn):self.routes.append(("GET",path,fn));return fn
        return deco
    def exception_handler(self,exc):
        def deco(fn):return fn
        return deco
def Depends(fn=None,*a,**k):return ("depends",fn)
