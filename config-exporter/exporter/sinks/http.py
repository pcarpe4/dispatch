import json
import logging

import requests

from . import register

log = logging.getLogger(__name__)


@register("http")
class HttpSink:
    """POSTs records as a JSON array in batches.

    cfg:
      url:        https://collector.example.com/ingest
      method:     POST (default)
      headers:    {Authorization: "Bearer ${API_TOKEN}"}
      batchSize:  500 (default)
      timeout:    30 (seconds)
      verify:     true | false | /path/to/ca.crt
    """

    def __init__(self, cfg):
        self.url = cfg["url"]
        self.method = cfg.get("method", "POST")
        self.headers = {"Content-Type": "application/json", **cfg.get("headers", {})}
        self.batch = int(cfg.get("batchSize", 500))
        self.timeout = int(cfg.get("timeout", 30))
        self.verify = cfg.get("verify", True)
        self.session = requests.Session()

    def send(self, records):
        for i in range(0, len(records), self.batch):
            chunk = records[i:i + self.batch]
            resp = self.session.request(
                self.method, self.url, headers=self.headers,
                data=json.dumps(chunk, default=str),
                timeout=self.timeout, verify=self.verify,
            )
            resp.raise_for_status()
            log.info("http sink: sent %d records -> %s (%d)", len(chunk), self.url, resp.status_code)
