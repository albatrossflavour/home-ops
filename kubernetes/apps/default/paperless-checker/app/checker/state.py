"""What the checker has already looked at, kept as one JSON file on the PVC."""
import json
import os
import tempfile


class State:
    def __init__(self, path):
        self.path = path
        self.last_run = "1970-01-01T00:00:00Z"
        self.last_digest = ""
        self.stopped = None
        self.docs = {}

    def load(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                data = json.load(f)
            self.last_run = data.get("last_run", self.last_run)
            self.last_digest = data.get("last_digest", "")
            self.stopped = data.get("stopped")
            self.docs = data.get("docs", {})

    def save(self):
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path) or ".", prefix=".state-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"last_run": self.last_run, "last_digest": self.last_digest,
                           "stopped": self.stopped, "docs": self.docs}, f)
            os.replace(tmp, self.path)
        except BaseException:
            os.unlink(tmp)
            raise

    def doc(self, doc_id):
        return self.docs.get(str(doc_id), {"content_hash": None, "changed_fields": [],
                                           "decisions": [], "fields_hash": None})

    def mark_checked(self, doc_id, content_hash, fields_hash, changed_fields, decisions):
        self.docs[str(doc_id)] = {"content_hash": content_hash, "fields_hash": fields_hash,
                                  "changed_fields": changed_fields, "decisions": decisions}
