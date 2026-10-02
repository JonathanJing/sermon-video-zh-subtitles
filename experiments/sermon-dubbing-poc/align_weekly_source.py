#!/usr/bin/env python3
"""Acoustic anchors for reviewed English blocks; layout timing is never read.

Local ASR is timing evidence only. It cannot replace the frozen English/Chinese
reading text. Unmatched boundaries are review items, never interpolated silently.
"""
import argparse
import difflib
import json
import hashlib
import math
from pathlib import Path
import re
import subprocess

from poc import sha256, write_json
from speech_backend import same_identity, SpeechModel, ASR, ALIGNER, accepted_model, add_batch_argument, bounded_batches, require_resolved_dispatches
from weekly_dubbing import read, validate_frozen


def tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower().replace("’", "'"))


def match_blocks(blocks, words):
    expected, ranges = [], []
    for block in blocks:
        start = len(expected)
        expected.extend(tokens(block["en"]))
        ranges.append((start, len(expected)))
    recognized, timed = [], []
    for word in words:
        for token in tokens(word["text"]):
            recognized.append(token)
            timed.append(word)
    matches = difflib.SequenceMatcher(None, expected, recognized, autojunk=False).get_matching_blocks()
    mapping = {m.a + i: m.b + i for m in matches for i in range(m.size)}
    anchors, issues = [], []
    previous = 0
    for block, (start, end) in zip(blocks, ranges):
        found = [i for i in range(start, end) if i in mapping]
        coverage = len(found) / max(1, end - start)
        problems = []
        if not found:
            issues.append({"blockId": block["id"], "reason": "no_acoustic_text_match"})
            continue
        first, last = timed[mapping[found[0]]], timed[mapping[found[-1]]]
        if coverage < .8:
            problems.append("low_english_match_coverage")
        if found[0] - start > 3 or end - 1 - found[-1] > 3:
            problems.append("unmatched_boundary_words")
        # Require several consecutive words at both ends of every block.
        for edge in [found[:5], found[-5:]]:
            if len(edge) < 3 or any(mapping[b] != mapping[a] + 1 for a, b in zip(edge, edge[1:])):
                problems.append("weak_boundary_anchor")
                break
        if not previous <= first["start"] < last["end"]:
            problems.append("nonmonotonic_or_empty_source_interval")
        previous = last["end"]
        anchors.append({"blockId": block["id"], "start": first["start"], "end": last["end"], "englishMatchCoverage": round(coverage, 4),
            "firstWords": " ".join(expected[found[0]:found[0] + 5]), "lastWords": " ".join(expected[max(start, found[-1] - 4):found[-1] + 1]), "issues": problems})
        issues.extend({"blockId": block["id"], "reason": problem} for problem in problems)
    return anchors, issues


def attach_timing_issues(anchors, issues, timing_issues):
    for issue in timing_issues:
        if anchors:
            anchor = min(anchors, key=lambda a: max(a["start"] - issue["time"], issue["time"] - a["end"], 0))
            issue["blockId"] = anchor["blockId"]
            if issue["reason"] not in anchor["issues"]:
                anchor["issues"].append(issue["reason"])
        issues.append(issue)


def validate_alignment_receipt(row, wav, text, source_sha):
    if row.get('audioSha256') != sha256(wav) or not accepted_model(row.get('model'), row.get('revision'), 'aligner'):
        raise ValueError('Stale acoustic alignment cache')
    if ('sourceSha256' in row and row['sourceSha256'] != source_sha) or (
            text is not None and 'textSha256' in row and row['textSha256'] != hashlib.sha256(text.encode()).hexdigest()):
        raise ValueError('Changed frozen alignment text/source')
    segments = row.get('words')
    if not isinstance(segments, list):
        raise ValueError('Invalid cached aligned words')
    previous = 0
    for word in segments:
        start, end = word['start'], word['end']
        if (not all(type(value) in (int, float) and math.isfinite(value) for value in (start, end))
                or not previous <= start <= end or not isinstance(word['text'], str)):
            raise ValueError('Invalid cached alignment timing')
        previous = end
    # Legacy receipts have no text hash; exact normalized word coverage binds
    # them to the unchanged cached ASR text rather than overwriting them.
    if text is not None and tokens(' '.join(word['text'] for word in segments)) != tokens(text):
        raise ValueError('Aligned words differ from frozen ASR text')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    add_batch_argument(parser)
    args = parser.parse_args()
    work = args.work.resolve()
    job = read(work / "job.json")
    validate_frozen(job)
    folder = work / "source-alignment"
    folder.mkdir(exist_ok=True)
    dispatch_dir = folder / 'speech-dispatch'
    require_resolved_dispatches(dispatch_dir)
    if (folder / "report.json").exists():
        raise ValueError("Preserve completed alignment")
    job_sha = sha256(work / 'job.json')
    windows, asr_models, pending = [], [], []
    duration = job['sourceDurationSeconds']
    for offset in range(0, int(duration), 50):
        wav = folder / f'window-{offset:04d}.wav'
        if not wav.exists():
            subprocess.run(['ffmpeg', '-v', 'error', '-n', '-ss', str(offset), '-i', job['inputs']['sourceAudio']['path'],
                            '-t', str(min(60, duration - offset)), '-ar', '16000', '-ac', '1', str(wav)], check=True)
        receipt = wav.with_suffix('.asr.json')
        identity = {'audioSha256': sha256(wav), 'sourceSha256': job['inputs']['sourceAudio']['sha256'],
                    'model': ASR[0], 'revision': ASR[1]}
        row = None
        if receipt.exists():
            row = read(receipt)
            if not same_identity(row['identity'], identity) or not isinstance(row.get('text'), str):
                raise ValueError('Stale acoustic timing cache')
        else:
            pending.append({'unitId': offset, 'path': wav, 'language': 'English', 'max_tokens': 2048, 'locale': 'en'})
        aligned = wav.with_suffix('.alignment.json')
        if aligned.exists():
            if row is None:
                raise ValueError('Alignment cache has no matching frozen ASR receipt')
            validate_alignment_receipt(read(aligned), wav, row['text'], job['inputs']['sourceAudio']['sha256'])
        windows.append({'offset': offset, 'wav': wav, 'row': row})
    by_offset = {window['offset']: window for window in windows}

    def save_asr(unit_id, result, inference):
        if sha256(work / 'job.json') != job_sha:
            raise ValueError('Frozen alignment job changed')
        window = by_offset[unit_id]
        wav = window['wav']
        row = {'identity': {'audioSha256': sha256(wav), 'sourceSha256': job['inputs']['sourceAudio']['sha256'],
                           'model': inference['model'], 'revision': inference['revision']},
               'text': result.text, 'inferenceReceipt': inference}
        if wav.with_suffix('.asr.json').exists():
            raise ValueError('Acoustic ASR receipt appeared during inference; preserve it')
        write_json(wav.with_suffix('.asr.json'), row)
        window['row'] = row

    if pending:
        model = SpeechModel(ASR)
        for batch in bounded_batches(pending, args.speech_batch_size):
            model.generate_batch(batch, on_result=save_asr, dispatch_dir=dispatch_dir, job_sha256=job_sha)
        del model
    for window in windows:
        row = window['row']
        if row is None:
            raise ValueError('Incomplete ASR window coverage')
        actual_model = [row['identity']['model'], row['identity']['revision']]
        if actual_model not in asr_models:
            asr_models.append(actual_model)
        print(f"Timing evidence {window['offset']}s / {duration}s", flush=True)
    if not asr_models:
        raise ValueError('No acoustic source windows')
    windows_models = asr_models[0]
    words, timing_issues, aligner_models, pending = [], [], [], []
    # A resume reuses matching alignment receipts instead of re-running every
    # already aligned window. Validate the entire cache before model startup.
    for window in windows:
        wav, text = window['wav'], window['row']['text']
        path = wav.with_suffix('.alignment.json')
        if path.exists():
            row = read(path)
            validate_alignment_receipt(row, wav, text, job['inputs']['sourceAudio']['sha256'])
            window['aligned'] = row
        else:
            window['aligned'] = None
            pending.append({'unitId': window['offset'], 'path': wav, 'text': text,
                            'language': 'English', 'max_tokens': 2048, 'locale': 'en'})

    def save_alignment(unit_id, result, inference):
        if sha256(work / 'job.json') != job_sha:
            raise ValueError('Frozen alignment job changed')
        window = by_offset[unit_id]
        row = {'audioSha256': sha256(window['wav']), 'sourceSha256': job['inputs']['sourceAudio']['sha256'],
               'textSha256': hashlib.sha256(window['row']['text'].encode()).hexdigest(),
               'model': inference['model'], 'revision': inference['revision'],
               'words': result.segments, 'inferenceReceipt': inference}
        validate_alignment_receipt(row, window['wav'], window['row']['text'], job['inputs']['sourceAudio']['sha256'])
        path = window['wav'].with_suffix('.alignment.json')
        if path.exists():
            raise ValueError('Alignment receipt appeared during inference; preserve it')
        write_json(path, row)
        window['aligned'] = row

    if pending:
        aligner = SpeechModel(ALIGNER)
        for batch in bounded_batches(pending, args.speech_batch_size):
            aligner.generate_batch(batch, on_result=save_alignment, dispatch_dir=dispatch_dir, job_sha256=job_sha)
        del aligner
    if sha256(work / 'job.json') != job_sha:
        raise ValueError('Frozen alignment job changed')
    for window in windows:
        offset, row = window['offset'], window['aligned']
        if row is None:
            raise ValueError('Incomplete forced-alignment coverage')
        model_id = [row['model'], row['revision']]
        if model_id not in aligner_models:
            aligner_models.append(model_id)
        segments = row['words']
        timing_issues.extend({'reason': 'zero_duration_alignment_word', 'windowStart': offset,
                              'word': word['text'], 'time': offset + word['start']}
                             for word in segments if word['start'] == word['end'])
        left = 0 if offset == 0 else 5
        right = min(55, duration - offset) if offset + 60 < duration else duration - offset
        for word in segments:
            if left <= word['start'] < right and word['start'] < word['end'] <= min(60, duration - offset) + .1:
                words.append({**word, 'start': offset + word['start'], 'end': offset + word['end']})
    anchors, issues = match_blocks(job["blocks"], words)
    attach_timing_issues(anchors, issues, timing_issues)
    write_json(folder / "words.json", words)
    write_json(folder / "report.json", {"schemaVersion": "sermon-acoustic-anchors-v1", "jobSha256": sha256(work / "job.json"),
        "status": "machine_anchors_ready" if not issues else "anchor_review_required", "sourceAudioSha256": job["inputs"]["sourceAudio"]["sha256"],
        "timeOrigin": "approved_sermon_clip_start", "fullVideoOffsetSeconds": job["sourceStartSeconds"], "blocks": anchors, "issues": issues,
        "asr": windows_models, "aligner": aligner_models[0], "asrModels": asr_models, "alignerModels": aligner_models, "modelIdentityScope": "representative_first_result_with_complete_model_lists", "humanReview": "pending", "readingTextReplaced": False})
    print(json.dumps({"blocks": len(anchors), "issues": len(issues)}), flush=True)


if __name__ == "__main__":
    main()
