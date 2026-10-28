"""Shared test environment constants that outlived the retired machine-QC driver."""

from scripts import tongxing_host  # noqa: F401  binds the production package ports

OPENAI_ENV = {"SERMON_OPENAI_ENVIRONMENT": "dev", "OPENAI_PROJECT_ID": "proj_test",
              "SERMON_OPENAI_CREDENTIAL_ALIAS": "tongxing-dev-runtime", "OPENAI_API_KEY": "sk-test-not-real"}
