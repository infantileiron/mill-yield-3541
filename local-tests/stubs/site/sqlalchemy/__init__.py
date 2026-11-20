"""Minimal SQLAlchemy stand-in (only the surface this project uses).

It is intentionally tiny: declarative models get a working keyword
constructor, column markers remember primary-key/unique metadata, and the
fake Session stores rows in an in-memory registry supporting the select/
where/like/get/scalar/scalars/add/commit/rollback calls made by the app.
"""


class IntegrityError(Exception):
    def __init__(self, *a, **k):
        super().__init__("integrity constraint violation (stub)")


class _Cond:
    def __init__(self, key, op, value):
        self.key, self.op, self.value = key, op, value


class _Column:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return _Cond(self.name, "eq", other)

    def like(self, pattern):
        return _Cond(self.name, "like", pattern)

    def desc(self):
        return ("order", self.name, "desc")

    def asc(self):
        return ("order", self.name, "asc")

    def in_(self, values):
        return _Cond(self.name, "in", list(values))

    def in_(self, values):
        return _Cond(self.name, "in", list(values))


class _Marker:
    def __init__(self, name, type_, pk, unique, index, default, nullable):
        self.name = name
        self.type_ = type_
        self.pk = pk
        self.unique = unique
        self.index = index
        self.default = default
        self.nullable = nullable

    def __eq__(self, other):
        return _Cond(self.name, "eq", other)

    def like(self, pattern):
        return _Cond(self.name, "like", pattern)

    def desc(self):
        return ("order", self.name, "desc")

    def asc(self):
        return ("order", self.name, "asc")


def mapped_column(type_=None, *rest, primary_key=False, unique=False,
                  index=False, default=None, nullable=True, **k):
    return _Marker(None, type_, primary_key, unique, index, default, nullable)


def ForeignKey(ref):
    return ("fk", ref)


class _Type:
    def __init__(self, *a, **k):
        pass


def _type(name):
    return type(name, (_Type,), {})


String = _type("String")
Float = _type("Float")
Integer = _type("Integer")
Text = _type("Text")
DateTime = _type("DateTime")


class JSON(_Type):
    pass


class _Mapped:
    def __class_getitem__(cls, item):
        return type("MappedType", (), {"__args__": (item,)})

    def __getitem__(self, item):
        # Mapped is exported as an instance; Mapped[int] hits this hook.
        return type("MappedType", (), {"__args__": (item,)})


Mapped = _Mapped()


class _DeclMeta(type):
    def __new__(mcs, name, bases, ns):
        cols = {}
        for base in bases:
            cols.update(getattr(base, "__columns__", {}))
        for attr, value in list(ns.items()):
            if isinstance(value, _Marker):
                value.name = attr
                cols[attr] = value
        ns["__columns__"] = cols
        cls = super().__new__(mcs, name, bases, ns)
        return cls

    def __call__(cls, *a, **kw):
        obj = cls.__new__(cls)
        for cname, marker in cls.__columns__.items():
            if cname in kw:
                setattr(obj, cname, kw[cname])
            elif marker.default is not None:
                d = marker.default
                setattr(obj, cname, d() if callable(d) else d)
            else:
                setattr(obj, cname, None)
        for key, value in kw.items():
            if key not in cls.__columns__:
                setattr(obj, key, value)
        return obj


class _MetaData:
    def create_all(self, engine):
        return None


class DeclarativeBase(metaclass=_DeclMeta):
    __tablename__ = None
    metadata = _MetaData()


class _Statement:
    def __init__(self, model):
        self.model = model
        self.conds = []

    def where(self, *conds):
        self.conds.extend(c for c in conds if isinstance(c, _Cond))
        return self

    def order_by(self, *a, **k):
        return self

    def outerjoin(self, *a, **k):
        return self

    def group_by(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def select_from(self, *a, **k):
        return self


def select(*entities):
    model = entities[0]
    return _Statement(model)


def _matches(obj, cond):
    value = getattr(obj, cond.key, None)
    if cond.op == "eq":
        return value == cond.value
    if cond.op == "like":
        import re
        # Translate SQL LIKE wildcards first, then regex-escape the literals
        # so % and _ are not consumed by re.escape before substitution.
        out = ["^"]
        for ch in cond.value:
            if ch == "%":
                out.append(".*")
            elif ch == "_":
                out.append(".")
            else:
                out.append(re.escape(ch))
        out.append("$")
        pattern = "".join(out)
        return isinstance(value, str) and re.match(pattern, value) is not None
    if cond.op == "in":
        return value in cond.value
    return False


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self):
        pass

    def all(self):
        return []

    def first(self):
        return None


class Session:
    registry = {}

    def __init__(self):
        self._staged = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if exc[0] is not None:
            self.rollback()
        return False

    def add(self, obj):
        self._staged.append(obj)

    def flush(self):
        for obj in self._staged:
            model = type(obj)
            store = Session.registry.setdefault(model, {})
            pk_markers = [m for m in model.__columns__.values() if m.pk]
            pk_name = pk_markers[0].name if pk_markers else "id"
            pk_value = getattr(obj, pk_name, None)
            if pk_value is None:
                pk_value = (max(store.keys(), default=0) + 1)
                setattr(obj, pk_name, pk_value)
            for cname, marker in model.__columns__.items():
                if marker.unique and getattr(obj, cname, None) is not None:
                    for existing in store.values():
                        if existing is not obj and getattr(existing, cname, None) == getattr(obj, cname):
                            raise IntegrityError()
            store[pk_value] = obj
        self._staged.clear()

    def commit(self):
        self.flush()

    def rollback(self):
        self._staged.clear()

    def refresh(self, obj):
        pass

    def expire_all(self):
        pass

    def get(self, model, pk):
        return Session.registry.get(model, {}).get(pk)

    def _query(self, stmt):
        store = Session.registry.get(stmt.model, {})
        rows = list(store.values())
        for cond in stmt.conds:
            rows = [o for o in rows if _matches(o, cond)]
        return rows

    def scalars(self, stmt):
        return _ScalarResult(self._query(stmt))

    def scalar(self, stmt):
        rows = self._query(stmt)
        return rows[0] if rows else None

    def execute(self, *a, **k):
        return _Result()


def sessionmaker(engine, **k):
    def factory():
        return Session()
    return factory


def create_engine(*a, **k):
    return object()


class func:
    def __getattr__(self, name):
        class _F:
            def __call__(self, *a, **k):
                return ("func", name, a)
        return _F()


func = func()


def text(s):
    return ("text", s)
