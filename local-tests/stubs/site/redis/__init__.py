# Minimal in-memory redis stand-in implementing only the used surface.
# Locks and the posted-key set are shared across clients (class state) to
# mirror a real Redis server that all backend/worker connections see.
class Lock:
    def __init__(self, client, name, timeout=None, blocking_timeout=None):
        self.client, self.name = client, name

    def acquire(self, blocking=True):
        if self.name in Redis._locks:
            return False
        Redis._locks.add(self.name)
        return True

    def release(self):
        Redis._locks.discard(self.name)


class Redis:
    _locks = set()
    _sets = {}
    _lists = {}

    def __init__(self, *a, **k):
        pass

    @classmethod
    def from_url(cls, *a, **k):
        return cls()

    def lock(self, name, timeout=None, blocking_timeout=None):
        return Lock(self, name, timeout, blocking_timeout)

    def ping(self):
        return True

    def rpush(self, key, *vals):
        Redis._lists.setdefault(key, []).extend(vals)
        return len(Redis._lists[key])

    def blpop(self, key, timeout=0):
        return None

    def sadd(self, key, *vals):
        s = Redis._sets.setdefault(key, set())
        s.update(vals)
        return len(vals)

    def sismember(self, key, val):
        return val in Redis._sets.get(key, set())
