import hashlib, json, time, threading
from pathlib import Path

class AuditLog:
    """Append-only JSONL log; each record hashes the previous one."""
    def __init__(self, path="data/audit.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self._prev = self._last_hash()

    def _last_hash(self):
        if not self.path.exists():
            return "GENESIS"
        last = None
        with self.path.open() as f:
            for last in f: pass
        return json.loads(last)["hash"] if last else "GENESIS"

    def record(self, actor, action, resource, outcome, **meta):
        with self._lock:
            body = {"ts": time.time(), "actor": actor, "action": action,
                    "resource": resource, "outcome": outcome,
                    "meta": meta, "prev": self._prev}
            digest = hashlib.sha256(
                json.dumps(body, sort_keys=True).encode()).hexdigest()
            with self.path.open("a") as f:
                f.write(json.dumps({**body, "hash": digest}) + "\n")
            self._prev = digest

    def verify(self):
        prev = "GENESIS"
        for line in self.path.read_text().splitlines():
            rec = json.loads(line)
            h = rec.pop("hash")
            if rec["prev"] != prev or h != hashlib.sha256(
                    json.dumps(rec, sort_keys=True).encode()).hexdigest():
                return False
            prev = h
        return True
