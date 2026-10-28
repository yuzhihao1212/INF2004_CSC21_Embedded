"""Append-only evidence log. Statistics and presentation, never fusion math."""
from datetime import datetime, timezone
import json
import uuid


class EventLog:
    """Each server instance is a separate session, even in an appended file.

    monotonic_ms supplies durations; wall_time is UTC ISO 8601 for people.
    Caller holds GatewayServer.lock. The file belongs to the caller.
    """
    def __init__(self, file):
        self.file = file
        self.session = uuid.uuid4().hex

    def write(self, event, now, **fields):
        record = {'schema_version': 1, 'session': self.session,
                  'wall_time': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                  'monotonic_ms': round(now * 1000), 'event': event, **fields}
        self.file.write(json.dumps(record, allow_nan=False, separators=(',', ':')) + '\n')
        self.file.flush()
