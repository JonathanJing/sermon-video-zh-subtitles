"""Deterministic evidence preflight; never substitutes for independent CUV review."""
from __future__ import annotations

POLICY = "cuv-evidence-preflight-v1"


class EvidenceBlocked(ValueError):
    """Valid pipeline execution blocked by unresolved or missing evidence."""

    def __init__(self, stage, findings):
        self.stage = stage
        self.findings = findings
        super().__init__(f"{stage}: {len(findings)} evidence finding(s) block continuation")

    def as_dict(self):
        return {"schemaVersion": POLICY, "status": "blocked", "stage": self.stage,
                "humanApproval": False, "findings": self.findings}


def preflight(manifest, mapping, blocks, library, *, validate_context, audit_content):
    """Collect reference/media defects before spending on any selection requests.

    Classification is a structural inventory of the proposed map, not a semantic
    verdict. Uncertainty is retained for independent quotation review.
    """
    if manifest.get("preflightPolicy") != POLICY:
        raise ValueError("Unknown CUV preflight policy")
    findings, inventory = [], []
    seen_context = set()
    pending = bool(mapping.get("issues"))
    for block, row in zip(blocks, mapping["blocks"]):
        quotes = row["quotes"]
        concerns = list(row.get("uncertainty", []))
        for item in [*quotes, *row["speakerReferences"]]:
            concerns.extend(item.get("uncertainty", []))
        pending = pending or bool(concerns)
        # Mixed means both mapped quotation and remaining spoken text. It does
        # not authorize treating the remaining text as verified paraphrase.
        remaining = block["en"]
        for quote in reversed(quotes):
            remaining = remaining[:quote["start"]] + remaining[quote["end"]:]
        classification = ("unresolved" if concerns else
                          "mixed" if quotes and remaining.strip(" \t\r\n.,;:!?—-\"'") else
                          "direct" if quotes else
                          "paraphrase" if row["speakerReferences"] else "narration")
        inventory.append({"blockId": block["id"], "classification": classification,
                          "classificationBasis": "proposed-map-structure",
                          "quoteIds": [q["quoteId"] for q in quotes],
                          "uncertainty": concerns, "requiresIndependentReview": True})
        for quote in quotes:
            refs = [quote["reference"]]
            shared = quote.get("sharedReferences")
            if shared is not None:
                if not isinstance(shared, list) or not shared or not all(isinstance(r, str) for r in shared):
                    findings.append({"blockId": block["id"], "quoteId": quote["quoteId"],
                                     "code": "invalid_shared_references"})
                else:
                    refs.extend(shared)
            for ref in dict.fromkeys(refs):
                try:
                    library.lookup(ref)
                except (ValueError, KeyError) as exc:
                    findings.append({"blockId": block["id"], "quoteId": quote["quoteId"],
                                     "code": "reference_lookup", "reference": ref, "detail": str(exc)})
        context = row.get("sourceContext")
        if context:
            if not manifest.get("auditSourceMediaPolicy"):
                findings.append({"blockId": block["id"], "code": "source_images_not_enabled",
                                 "detail": "Source context requires actual images in independent audits"})
            binding = context.get("evidenceBinding", {})
            key = (binding.get("path"), binding.get("sha256"))
            if key not in seen_context:
                seen_context.add(key)
                try:
                    validate_context(binding, manifest, mapping["blocks"])
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    findings.append({"blockId": block["id"], "code": "source_context", "detail": str(exc)})
        if any(q.get("sharedReferences") is not None for q in quotes) and not manifest.get("auditSourceMediaPolicy"):
            findings.append({"blockId": block["id"], "code": "shared_verse_evidence_not_enabled"})
    if manifest.get("auditSourceMediaPolicy"):
        try:
            # Build the actual multimodal envelope now: paths/hashes alone are
            # insufficient. This checks bytes, MIME and aggregate size locally.
            audit_content("audit-quotes", {}, manifest)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            findings.append({"code": "audit_payload", "detail": str(exc)})
    report = {"schemaVersion": POLICY, "status": "blocked" if findings else "ready_for_independent_review",
              "humanApproval": False, "inventory": inventory, "findings": findings,
              "hasPendingInterpretation": pending}
    return report


def require_ready(report):
    if report["findings"]:
        raise EvidenceBlocked("preflight", report["findings"])
