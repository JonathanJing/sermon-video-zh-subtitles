"""Frozen-reference MFA timing adapter. No ASR, sentence invention, or network downloads.

The reference punctuation remains the semantic boundary authority. MFA times are
model estimates, never human-reviewed timing. Missing words/unknown phones fail.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

SCHEMA_VERSION = 1
WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*|\d+|[^\W\d_]+", re.UNICODE)
SMALL = 'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
TENS = 'zero ten twenty thirty forty fifty sixty seventy eighty ninety'.split()


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def _number(n):
    if n < 20:
        return [SMALL[n]]
    if n < 100:
        return [TENS[n // 10]] + (_number(n % 10) if n % 10 else [])
    if n < 1000:
        return _number(n // 100) + ['hundred'] + (_number(n % 100) if n % 100 else [])
    if n < 1000000:
        return _number(n // 1000) + ['thousand'] + (_number(n % 1000) if n % 1000 else [])
    raise ValueError('MFA numeric normalization supports integers below 1,000,000 only')


def _spoken_forms(path):
    if path is None:
        return {}
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError('MFA spoken forms must be a JSON object mapping tokens to word lists')
    for token, forms in value.items():
        if (not isinstance(token, str) or not token or re.search(r"\s", token)
                or not isinstance(forms, list) or not forms
                or any(not isinstance(word, str) or not re.fullmatch(r"[a-z]+(?:'[a-z]+)*", word)
                       for word in forms)):
            raise ValueError('MFA spoken forms require exact single tokens and nonempty lowercase word lists')
    return value


def _reference(text, spoken_forms=None):
    """Map original whitespace tokens, applying explicit spoken forms before heuristics."""
    text = ' '.join(str(text).split())
    spoken_forms = spoken_forms or {}
    mapping, spoken = [], []
    for match in re.finditer(r'\S+', text):
        token = match.group()
        forms = list(spoken_forms[token]) if token in spoken_forms else []
        if token not in spoken_forms:
            if re.search(r'\d[.,:/-]\d|\d(?:st|nd|rd|th)\b|[$€£%]', token, re.I):
                raise ValueError('Ambiguous numeric reference: configure its exact token in spoken forms before MFA')
            for part in WORD_RE.findall(token):
                if part.isdecimal():
                    if len(part) > 1 and part.startswith('0'):
                        raise ValueError('Ambiguous leading-zero number in MFA reference')
                    forms.extend(_number(int(part)))
                else:
                    forms.append(part.lower().replace('’', "'"))
        if not forms:
            continue
        mapping.append({'text': token, 'charStart': match.start(), 'charEnd': match.end(),
                        'spokenStart': len(spoken), 'spokenEnd': len(spoken) + len(forms),
                        'spokenForms': forms, 'explicitSpokenForm': token in spoken_forms})
        spoken.extend(forms)
    if not spoken:
        raise ValueError('MFA requires nonempty frozen reference text')
    return text, spoken, mapping


def _sentences(text):
    """Split reference punctuation while protecting titles and name initials."""
    start = 0
    for boundary in re.finditer(r'(?<=[.!?])\s+', text):
        preceding = text[:boundary.start()]
        token = preceding.split()[-1]
        if re.fullmatch(r'(?:Dr|Mr|Mrs|Ms|St|Rev|Prof|Jr|Sr)\.', token, re.I):
            continue
        if re.fullmatch(r'[A-Z]\.', token):
            continue
        yield text[start:boundary.start()]
        start = boundary.end()
    yield text[start:]


def _run(command, *, env, log, timeout):
    with Path(log).open('w') as stream:
        try:
            subprocess.run([str(x) for x in command], env=env, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=timeout)
        except (subprocess.SubprocessError, OSError) as exc:
            raise RuntimeError(f'MFA command failed; inspect {log}') from exc


def _local_file(value, kind):
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f'{kind} must be an existing local file (no automatic downloads): {path}')
    return path


def _dictionary_words(path):
    return {line.split()[0].lower() for line in Path(path).read_text().splitlines()
            if line.strip() and not line.lstrip().startswith('#')}


def _entries(raw, tier, duration):
    try:
        entries = raw['tiers'][tier]['entries']
    except (KeyError, TypeError) as exc:
        raise ValueError(f'MFA output missing {tier} tier') from exc
    validated = []
    previous = 0.0
    for entry in entries:
        if not isinstance(entry, list) or len(entry) != 3:
            raise ValueError(f'Invalid MFA {tier} interval')
        start, end, label = entry
        if (isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end)
                or start < previous - 1e-6 or end < start or start < 0 or end > duration + 0.025
                or not isinstance(label, str)):
            raise ValueError(f'Invalid MFA {tier} timing')
        previous = end
        if label in ('spn', '<unk>', '<UNK>'):
            raise ValueError('Unknown MFA word/phone: reference cannot be trusted')
        if label not in ('', '<eps>', 'sil', 'sp'):
            if end <= start:
                raise ValueError('Zero-duration MFA speech interval')
            validated.append((float(start), float(end), label))
    return validated


def _segments(raw, chunk, text, spoken, mapping):
    duration = float(chunk['end']) - float(chunk['start'])
    words = _entries(raw, 'words', duration)
    phones = _entries(raw, 'phones', duration)
    if [entry[2] for entry in words] != spoken:
        raise ValueError('MFA aligned words differ from frozen reference (missing, extra, or changed words)')
    assigned_phone_count = 0
    for start, end, word in words:
        assigned = [(s, e, p) for s, e, p in phones if s >= start - 1e-6 and e <= end + 1e-6]
        if not assigned:
            raise ValueError(f'MFA aligned word has no phones: {word}')
        assigned_phone_count += len(assigned)
    if assigned_phone_count != len(phones):
        raise ValueError('MFA phones do not map completely to frozen reference words')
    offset = float(chunk['start'])
    mapped = []
    for token in mapping:
        start = words[token['spokenStart']][0]
        end = words[token['spokenEnd'] - 1][1]
        token_phones = [{'start': round(s + offset, 6), 'end': round(e + offset, 6), 'phone': p}
                        for s, e, p in phones if s >= start - 1e-6 and e <= end + 1e-6]
        if not token_phones:
            raise ValueError(f'MFA word has no phones: {token["text"]}')
        mapped.append({**token, 'start': round(start + offset, 6), 'end': round(end + offset, 6),
                       'phones': token_phones})
    # Original punctuation determines sentences; no duration-based punctuation insertion.
    segments = []
    position = 0
    for sentence in _sentences(text):
        sentence_start = text.index(sentence, position)
        sentence_end = sentence_start + len(sentence)
        selected = [w for w in mapped if sentence_start <= w['charStart'] < sentence_end]
        if not selected:
            raise ValueError('Reference contains a sentence without aligned words')
        segments.append({'id': 0, 'start': selected[0]['start'], 'end': selected[-1]['end'],
                         'text': sentence, 'source': 'mfa-forced-alignment',
                         'timingQuality': 'mfa_word_aligned',
                         'timingKind': 'forced_alignment_estimate',
                         'requires_operator_review': True,
                         'sentenceBoundarySource': 'frozen_reference_punctuation',
                         'referenceChunkId': chunk.get('id'), 'wordTimes': selected,
                         'phones': [phone for word in selected for phone in word['phones']]})
        position = sentence_end
    if sum(len(s['wordTimes']) for s in segments) != len(mapping):
        raise ValueError('MFA sentence mapping lost reference tokens')
    return segments


def preflight(mfa_executable, dictionary_path, acoustic_model, g2p_model=None, spoken_forms_path=None):
    """Check local dependencies before any paid transcription stage."""
    executable = _local_file(shutil.which(str(mfa_executable)) or mfa_executable, 'MFA executable')
    if not os.access(executable, os.X_OK):
        raise ValueError(f'MFA executable is not executable: {executable}')
    if not shutil.which('ffmpeg'):
        raise ValueError('ffmpeg is required for MFA audio extraction')
    spoken_path = _local_file(spoken_forms_path, 'MFA spoken forms') if spoken_forms_path else None
    _spoken_forms(spoken_path)
    return {'spoken_forms_path': str(spoken_path) if spoken_path else None,
            'spoken_forms_sha256': _sha(spoken_path) if spoken_path else None,
            'mfa_executable': str(executable),
            'dictionary_path': str(_local_file(dictionary_path, 'MFA dictionary')),
            'acoustic_model': str(_local_file(acoustic_model, 'MFA acoustic model')),
            'g2p_model': str(_local_file(g2p_model, 'MFA G2P model')) if g2p_model else None}


def align_reference_chunks(chunks, clip_path, outdir, *, mfa_executable,
                           dictionary_path, acoustic_model, g2p_model=None, spoken_forms_path=None):
    """Return original-punctuation sentences with absolute clip-relative MFA times.

    Models and dictionaries must be local files. Cache reuse requires exact source,
    text, config, executable/version and output hashes. Changed inputs use a fresh
    content-addressed run; corrupted cached outputs fail instead of being accepted.
    Integer expansion is recorded as an unverified spoken-form assumption.
    """
    clip = _local_file(clip_path, 'Audio')
    executable = shutil.which(str(mfa_executable)) or str(mfa_executable)
    executable = _local_file(executable, 'MFA executable')
    dictionary = _local_file(dictionary_path, 'MFA dictionary')
    acoustic = _local_file(acoustic_model, 'MFA acoustic model')
    g2p = _local_file(g2p_model, 'MFA G2P model') if g2p_model else None
    spoken_path = _local_file(spoken_forms_path, 'MFA spoken forms') if spoken_forms_path else None
    spoken_forms = _spoken_forms(spoken_path)
    root = Path(outdir).resolve() / 'mfa_alignment'
    root.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['PATH'] = str(executable.parent) + os.pathsep + env.get('PATH', '')
    env['MFA_ROOT_DIR'] = str(root / 'version-runtime')
    try:
        version = subprocess.run([str(executable), 'version'], env=env, capture_output=True,
                                 text=True, check=True, timeout=60).stdout.strip()
    except (subprocess.SubprocessError, OSError) as exc:
        raise RuntimeError('Cannot identify local MFA executable version') from exc
    if not version:
        raise ValueError('MFA executable returned empty version')
    prepared, skipped_empty, previous_end = [], [], 0.0
    for chunk in chunks:
        start, end = float(chunk['start']), float(chunk['end'])
        if not math.isfinite(start) or not math.isfinite(end) or start < previous_end - 1e-6 or end <= start:
            raise ValueError('Reference chunks must have finite nonoverlapping positive durations')
        if not str(chunk.get('text', '')).strip():
            skipped_empty.append({'id': chunk.get('id'), 'start': start, 'end': end, 'text': ''})
            previous_end = end
            continue
        text, spoken, mapping = _reference(chunk.get('text', ''), spoken_forms)
        prepared.append((chunk, text, spoken, mapping))
        previous_end = end
    if not prepared:
        raise ValueError('No reference chunks for MFA')
    identity = {'schemaVersion': SCHEMA_VERSION, 'adapterSha256': _sha(__file__),
                'skippedEmptyReferenceChunks': skipped_empty, 'audioSha256': _sha(clip),
                'mfa': {'path': str(executable), 'sha256': _sha(executable), 'version': version},
                'dictionarySha256': _sha(dictionary), 'acousticSha256': _sha(acoustic),
                'g2pSha256': _sha(g2p) if g2p else None,
                'spokenFormsSha256': _sha(spoken_path) if spoken_path else None,
                'options': ['single_speaker', 'no_textgrid_cleanup', 'json', 'mono_16000_pcm16'],
                'chunks': [{'id': c.get('id'), 'start': c['start'], 'end': c['end'],
                            'text': t, 'spokenWords': s, 'mapping': m} for c, t, s, m in prepared]}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    run = root / key
    run.mkdir(exist_ok=True)
    manifest_path = run / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    if manifest and manifest.get('identity') != identity:
        raise ValueError('MFA cached identity mismatch')
    raw_paths = [run / 'aligned' / 'speaker' / f'chunk_{i:04d}.json' for i in range(len(prepared))]
    if manifest:
        cached_dictionary = run / 'dictionary.dict'
        if not cached_dictionary.is_file() or manifest.get('dictionaryUsedSha256') != _sha(cached_dictionary):
            raise ValueError('MFA cached pronunciation dictionary missing or changed')
        for path in raw_paths:
            if not path.is_file() or manifest.get('outputHashes', {}).get(str(path.relative_to(run))) != _sha(path):
                raise ValueError('MFA cached alignment output missing or changed')
    else:
        # Failed/interrupted attempts are retained in logs but never treated as a cache hit.
        corpus = run / 'corpus' / 'speaker'
        corpus.mkdir(parents=True, exist_ok=True)
        env['MFA_ROOT_DIR'] = str(run / 'runtime')
        lexicon = run / 'dictionary.dict'
        lexicon.write_bytes(dictionary.read_bytes())
        vocabulary = {w for _, _, spoken, _ in prepared for w in spoken}
        missing = sorted(vocabulary - _dictionary_words(lexicon))
        if missing:
            if not g2p:
                raise ValueError('MFA dictionary missing words; configure local G2P model: ' + ', '.join(missing))
            oov = run / 'oov.txt'
            oov.write_text('\n'.join(missing) + '\n')
            candidate = run / 'oov.dict'
            _run([executable, 'g2p', oov, g2p, candidate, '-n', '1'], env=env,
                 log=run / 'g2p.log', timeout=600)
            if not candidate.is_file() or set(missing) - _dictionary_words(candidate):
                raise ValueError('G2P did not produce pronunciations for every missing word')
            with lexicon.open('a') as stream:
                stream.write('\n' + candidate.read_text())
        for i, (chunk, text, spoken, mapping) in enumerate(prepared):
            stem = corpus / f'chunk_{i:04d}'
            stem.with_suffix('.lab').write_text(' '.join(spoken) + '\n')
            duration = float(chunk['end']) - float(chunk['start'])
            _run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-ss',
                  str(chunk['start']), '-i', clip, '-t', str(duration), '-vn', '-ac', '1',
                  '-ar', '16000', '-c:a', 'pcm_s16le', stem.with_suffix('.wav')],
                 env=env, log=run / f'ffmpeg_{i:04d}.log', timeout=300)
            import wave
            with wave.open(str(stem.with_suffix('.wav'))) as wav:
                actual = wav.getnframes() / wav.getframerate()
                if abs(actual - duration) > .05 or wav.getnchannels() != 1 or wav.getframerate() != 16000:
                    raise ValueError('Decoded MFA audio is truncated or incompatible with requested chunk')
        total_duration = sum(float(c['end']) - float(c['start']) for c, _, _, _ in prepared)
        _run([executable, 'align', corpus.parent, lexicon, acoustic, run / 'aligned',
              '--output_format', 'json', '--num_jobs', '2', '--single_speaker',
              '--no_textgrid_cleanup', '--clean', '--overwrite'], env=env,
             log=run / 'align.log', timeout=max(600, min(14400, int(total_duration * 6 + 300))))
    segments = []
    for path, (chunk, text, spoken, mapping) in zip(raw_paths, prepared):
        if not path.is_file():
            raise ValueError(f'MFA did not align required chunk: {path.name}')
        segments.extend(_segments(json.loads(path.read_text()), chunk, text, spoken, mapping))
    for i, segment in enumerate(segments):
        segment['id'] = i
        segment['mfaManifest'] = str(manifest_path)
    if not manifest:
        _write(manifest_path, {'schemaVersion': SCHEMA_VERSION, 'identity': identity,
                              'outputHashes': {str(p.relative_to(run)): _sha(p) for p in raw_paths},
                              'dictionaryUsedSha256': _sha(run / 'dictionary.dict'),
                              'requires_operator_review': True,
                              'limitations': ['Times are forced-alignment estimates, not human verified.',
                                              'Integer expansion and G2P pronunciations are unverified candidates.']})
    _write(run / 'segments.json', segments)
    return segments
