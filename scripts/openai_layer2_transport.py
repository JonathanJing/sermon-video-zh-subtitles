"""Single-attempt OpenAI API transport for new standalone Layer 2 runs."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from scripts import run_target_language_models as models
from scripts import sermon_pipeline
from scripts.sermon_openai_runtime import selected_route


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

    def __call__(self, api_key, payload):
        if api_key != self.key:
            raise ValueError("selected_openai_credential_override")
        from scripts.strict_budget_capability import admit
        decision = admit("standalone_api", payload=payload)
        if decision["decision"] != "reserved":
            raise ValueError(decision["reason"])
        return sermon_pipeline.json_request(sermon_pipeline.CHAT_URL, api_key, payload, retries=1)

    @staticmethod
    def completed_content(response, model, role):
        return models.completed_response_content(response, model, role)
