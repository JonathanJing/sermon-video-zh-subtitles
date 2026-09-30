# Synthetic D1 contract fixtures

Every file here is a synthetic schema/developer fixture. No model was called,
no human approved these examples, and no Gate Decision authorizes execution.
`gate-waiting.json` deliberately remains waiting_human. The repair fixture binds
the separate failing review, not the passing one.

The byte and canonical hashes deliberately differ where pretty-printed JSON is
used. `receiptSha256` hashes the complete review object except that field itself.
References are opaque content identities, not paths to load or URLs to fetch.

Legacy policy file hashes and a v2 fixture freeze prior decoding behavior.
`legacy-editor-result.json` keeps the existing editable-text result shape and raw
boolean checks; normalization must copy it, never rewrite it as strict evidence.
