#!/usr/bin/env python3
"""Render frozen per-speaker translated excerpts without reusing neutral auditions."""
import argparse
import hashlib
import json
from pathlib import Path
import types
import render_multilingual_voice_demos as renderer


def digest_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def validate_scripts(scripts):
    if scripts.get('schemaVersion') != 'sermon-speaker-clip-demo-scripts-v2':
        raise ValueError('Unsupported scripts')
    ids = set()
    for s in scripts['speakers']:
        if s['speakerId'] in ids:
            raise ValueError('Duplicate speaker')
        ids.add(s['speakerId'])
        source = s['source']
        if not 0 <= source['startSeconds'] < source['endSeconds']:
            raise ValueError('Invalid original-video interval')
        expected = digest_text(s['original']['text'])
        if source['englishTextSha256'] != expected:
            raise ValueError('English hash mismatch')
        if {x['locale'] for x in s['samples']} != {'zh-Hans', 'ko', 'es'} or len(s['samples']) != 3:
            raise ValueError('Three locales required')
        for x in s['samples']:
            if x['sourceEnglishTextSha256'] != expected or x['textSha256'] != digest_text(x['text']):
                raise ValueError('Cross-bound translation')
    if len(ids) != 6:
        raise ValueError('Six speakers required')


def validate_manifest(manifest, registry, script):
    expected={'registryJsonSha256':renderer.json_sha256(registry),
              'scriptJsonSha256':renderer.json_sha256(script),
              'rendererSha256':renderer.file_sha256(Path(renderer.__file__))}
    if any(manifest.get(k)!=v for k,v in expected.items()):
        raise ValueError('Cached generation manifest identity differs')
    tracks=manifest.get('tracks',[])
    if len(tracks)!=3 or {x['targetLocale'] for x in tracks}!={'zh-Hans','ko','es'}:
        raise ValueError('Incomplete cached three-language generation')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scripts', type=Path, required=True)
    p.add_argument('--registry', type=Path, required=True)
    p.add_argument('--checkpoint-map', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    scripts = json.loads(a.scripts.read_text()); validate_scripts(scripts)
    a.out.mkdir(parents=True, exist_ok=True)
    records = []
    for s in scripts['speakers']:
        work = a.out / s['speakerId']; work.mkdir(exist_ok=True)
        script = {'schemaVersion': renderer.SCRIPT_SCHEMA_VERSION, 'scope': scripts['sourceScope'],
                  'locales': [{'targetLocale': x['locale'], 'modelLanguage': x['modelLanguage'], 'text': x['text']} for x in s['samples']]}
        script_path = work / 'script.json'
        encoded = json.dumps(script, ensure_ascii=False, indent=2) + '\n'
        if script_path.exists() and script_path.read_text() != encoded:
            raise ValueError('Frozen per-speaker script changed')
        script_path.write_text(encoded)
        output = work / 'audio'
        if not (output / 'manifest.json').exists():
            renderer.render(types.SimpleNamespace(registry=a.registry, script=script_path,
                checkpoint_map=a.checkpoint_map, speakers=[s['speakerId']], locales=['zh-Hans','ko','es'],
                out=output, dtype='bfloat16', device='cuda:0', attention='sdpa', seed=42))
        m = json.loads((output / 'manifest.json').read_text())
        validate_manifest(m, json.loads(a.registry.read_text()), script)
        for track in m['tracks']:
            sample = next(x for x in s['samples'] if x['locale'] == track['targetLocale'])
            if track['textSha256'] != sample['textSha256']:
                raise ValueError('Generated receipt differs from frozen text')
            records.append({**track, 'sourceClipId': s['clipId'], 'englishTextSha256': s['source']['englishTextSha256'],
                'sourceScope': scripts['sourceScope'], 'humanListeningStatus': 'pending'})
    report = {'schemaVersion': 'sermon-speaker-clip-demo-generation-v2', 'status': 'generated_waveforms',
        'scriptsSha256': renderer.file_sha256(a.scripts), 'wrapperSha256': renderer.file_sha256(Path(__file__)),
        'baseRendererSha256': renderer.file_sha256(Path(renderer.__file__)), 'humanListeningStatus':'pending', 'tracks': records}
    (a.out / 'generation-manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

if __name__ == '__main__':
    main()
