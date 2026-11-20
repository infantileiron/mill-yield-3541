# Minimal in-memory redis stand-in implementing only the used surface.
class Lock:
    def __init__(self, client, name, timeout=None, blocking_timeout=None):
        self.client, self.name = client, name
    def acquire(self, blocking=True):
        if self.name in self.client._locks:
            return False
        self.client._locks.add(self.name); return True
    def release(self):
        self.client._locks.discard(self.name)
class Redis:
    def __init__(self, *a, **k):
        self._sets={}; self._locks=set(); self._lists={}
    @classmethod
    def from_url(cls,*a,**k): return cls()
    def lock(self,name,timeout=None,blocking_timeout=None): return Lock(self,name,timeout,blocking_timeout)
    def ping(self): return True
    def rpush(self,key,*vals): self._lists.setdefault(key,[]).extend(vals); return len(self._lists[key])
    def blpop(self,key,timeout=0): return None
    def sadd(self,key,*vals): s=self._sets.setdefault(key,set()); s.update(vals); return len(vals)
    def sismember(self,key,val): return val in self._sets.get(key,set())
