import json
from datetime import datetime

class Recorder:
    def __init__(self, file):
        self.file = open(file, "a")

    def write(self, payload):
        entry = {
            "ts": datetime.utcnow().isoformat(),
            "payload": payload
        }
        self.file.write(json.dumps(entry) + "\n")
        self.file.flush()