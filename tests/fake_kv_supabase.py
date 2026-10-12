"""core/storage.py のテスト用の、bot_kv テーブルだけを持つ偽の Supabase クライアント。"""


class APIError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.message, self.code = message, code


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.op, self.payload, self.filters, self.window = db, table, "select", None, [], None

    def select(self, columns="*"):
        self.op = "select"
        return self

    def upsert(self, row, on_conflict=None):
        self.op, self.payload = "upsert", row
        assert on_conflict == "namespace,key"
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def _match(self, row):
        return all(row.get(c) == v for c, v in self.filters)

    def execute(self):
        self.db.calls.append((self.op, self.table))
        if self.db.error is not None:
            raise self.db.error
        if self.table != "bot_kv":
            raise APIError(f"Could not find the table 'public.{self.table}'", code="PGRST205")
        rows = self.db.rows
        if self.op == "select":
            found = [dict(r) for r in rows if self._match(r)]
            if self.window:
                found = found[self.window[0]:self.window[1] + 1]
            return _Result(found)
        if self.op == "upsert":
            key = (self.payload["namespace"], self.payload["key"])
            self.db.rows = [r for r in rows if (r["namespace"], r["key"]) != key] + [dict(self.payload)]
            return _Result([self.payload])
        if self.op == "delete":
            self.db.rows = [r for r in rows if not self._match(r)]
            return _Result([])
        raise AssertionError(self.op)


class FakeKVSupabase:
    def __init__(self, rows=None, error=None):
        self.rows = list(rows or [])
        self.error = error
        self.calls = []

    def table(self, name):
        return _Query(self, name)

    def value(self, namespace, key):
        for r in self.rows:
            if (r["namespace"], r["key"]) == (namespace, key):
                return r["value"]
        return None


def missing_table_error():
    return APIError("Could not find the table 'public.bot_kv' in the schema cache", code="PGRST205")
