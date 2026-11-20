class FieldInfo:
    def __init__(self, default=None, **k):
        self.default = default
        self.meta = k


def Field(default=None, **k):
    return FieldInfo(default, **k)


def field_validator(*names, **kw):
    def deco(fn):
        fn.__validator__ = names
        return fn
    return deco


class BaseModel:
    def model_dump(self):
        return {k: getattr(self, k) for k in type(self).__fields__}

    def __init__(self, **data):
        cls = type(self)
        cls.__fields__ = getattr(cls, "__fields__", set()) or set()
        for name, val in data.items():
            setattr(self, name, val)
            cls.__fields__.add(name)
        # Run @field_validator-decorated classmethods, mirroring pydantic v2.
        for attr in dir(cls):
            fn = getattr(cls, attr, None)
            names = getattr(fn, "__validator__", ())
            for name in names:
                if name in data:
                    setattr(self, name, fn(cls, getattr(self, name)))
