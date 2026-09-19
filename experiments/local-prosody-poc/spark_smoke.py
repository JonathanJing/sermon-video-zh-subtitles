"""Verify the current Mac can dispatch a small inference to Spark over SSH."""
import argparse
import json
import socket
import subprocess
import time
from pathlib import Path
from run import local_api


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    model = local_api('/models')['data'][0]['id']
    started = time.monotonic()
    response = local_api('/chat/completions', {
        'model': model, 'messages': [{'role': 'user', 'content': 'Reply with exactly SPARK_OK'}],
        'temperature': 0, 'max_tokens': 32,
        'chat_template_kwargs': {'enable_thinking': False}})
    choice = response['choices'][0]
    passed = (choice['message']['content'].strip() == 'SPARK_OK'
              and choice['finish_reason'] == 'stop' and response.get('model') == model)
    receipt = {'origin_host': socket.gethostname(), 'model': model,
               'git_commit': subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
               'elapsed_seconds': round(time.monotonic()-started,3),
               'passed': passed, 'response': response}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps(receipt, ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
