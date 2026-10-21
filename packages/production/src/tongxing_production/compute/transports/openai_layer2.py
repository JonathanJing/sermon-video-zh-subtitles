"""Single-attempt OpenAI API transport for new standalone Layer 2 runs."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .. import legacy_openai
from ..openai_runtime import selected_route


class OpenAILayer2Transport:
    billing = "api"

    def __init__(self):
        route = selected_route()
        if route is None:
            raise ValueError("openai_layer2_requires_explicit_dev_or_prod_launcher")
        self.key = os.environ["OPENAI_API_KEY"]
        self.execution_identity = {
            "schemaVersion": "openai-layer2-transport-identity-v1",
            "backend": "openai_api",
            "provider": "openai",
            "authMode": "project_api_key",
            "route": route,
            "adapterSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }

    def admit_resource(self, payload):
        """Reject unsupported calls before the runner records an unknown dispatch."""
        from ..budget_capability import admit
        decision = admit("standalone_api", payload=payload)
        if decision["decision"] != "reserved":
            raise ValueError(decision["reason"])
        return decision

    def __call__(self, api_key, payload):
        if api_key != self.key:
            raise ValueError("selected_openai_credential_override")
        self.admit_resource(payload)
        return legacy_openai.json_request(legacy_openai.CHAT_URL, api_key, payload, retries=1)
