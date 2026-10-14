"""Completed fake CLI failures are terminal; uncertain process outcomes stay fenced."""
import base64
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import api_cli_outcomes as outcomes
from scripts import build_sermon_reading_edition_with_openai as reading
from scripts import sermon_codex_transport as transport


class ReadingCliTerminalTests(unittest.TestCase):
    maxDiff = None
    def exercise(self, branch, failure):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cli=root/'codex';cli.write_text('#!/bin/sh\nexit 0\n');cli.chmod(0o700)
            home=root/'home';home.mkdir();(home/'auth.json').write_text(json.dumps({'auth_mode':'chatgpt'}))
            schema=root/'schema.json';schema.write_text(json.dumps({'type':'object','required':['blocks'],'properties':{'blocks':{'type':'array'}}}))
            calls=[];mode=[failure]
            def fake_run(command,**kwargs):
                calls.append(command)
                if mode[0]=='timeout':raise subprocess.TimeoutExpired(command,1,output='partial stdout',stderr='partial stderr')
                content='not JSON' if mode[0]=='invalid_json' else ('{}' if mode[0]=='schema' else '{"blocks":[]}')
                self.assertIs(kwargs['text'],False);self.assertIsInstance(kwargs['input'],bytes)
                path=Path(command[command.index('-o' if branch=='sol' else '--output-last-message')+1])
                if mode[0]!='missing_output':path.write_bytes(b'\xffinvalid output' if mode[0]=='invalid_output_utf8' else content.encode())
                stdout='not JSONL' if mode[0]=='invalid_events' else '\n'.join(json.dumps(row) for row in [
                    {'type':'thread.started','thread_id':'synthetic-thread'},
                    {'type':'item.completed','item':{'type':'agent_message','text':content}},
                    {'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}])
                return subprocess.CompletedProcess(command,2 if mode[0]=='nonzero' else 0,b'\xffinvalid events' if mode[0]=='invalid_stdout_utf8' else stdout.encode(),b'synthetic stderr')
            real_call=transport._call
            def private_call(prompt,**kwargs):
                return real_call(prompt,output_dir=root/'transport'/hashlib.sha256(prompt.encode()).hexdigest(),**kwargs)
            def invoke(text):
                return reading.codex_json({'model':'gpt-6.1-sol' if branch=='sol' else 'gpt-6-sol','reasoning_effort':'high','messages':[{'role':'system','content':'synthetic system'},{'role':'user','content':text}]},codex_cli=cli,model='gpt-6.1-sol' if branch=='sol' else 'gpt-6-sol',reasoning_effort='high',schema_path=schema,output_path=root/'last-message.json')
            with patch.dict(os.environ,{'CODEX_HOME':str(home),'SERMON_ACCOUNTING_DIR':str(root/'accounting')},clear=True),patch.object(subprocess,'run',side_effect=fake_run),patch.object(subprocess,'check_output',return_value='codex synthetic\n'),patch.object(transport,'_call',side_effect=private_call):
                with self.assertRaises(Exception):invoke('first request')
                receipts=list((root/'accounting'/'api-cli-outcomes').glob('*/outcome.json'))
                self.assertEqual(len(receipts),1);row=json.loads(receipts[0].read_text())
                if failure=='timeout':
                    self.assertEqual(row['status'],'unknown');self.assertNotIn('cliTerminal',row)
                    mode[0]='success'
                    with self.assertRaisesRegex(ValueError,'api_cli_outcome_reconciliation_required'):invoke('different request')
                    self.assertEqual(len(calls),1)
                    return
                self.assertEqual(row['status'],'terminal_failure');self.assertNotIn('httpStatus',row)
                terminal=row['cliTerminal'];self.assertEqual(terminal['schemaVersion'],'sermon-cli-terminal-v1')
                self.assertEqual(terminal['returncode'],2 if failure=='nonzero' else 0)
                for name in ['stdout','stderr','output']:
                    value=terminal[name]
                    if name=='output' and failure=='missing_output':
                        self.assertIsNone(value);continue
                    self.assertIsNotNone(value)
                    raw=base64.b64decode(value['rawBodyBase64'],validate=True)
                    self.assertEqual(value['rawBodySha256'],hashlib.sha256(raw).hexdigest())
                self.assertEqual(base64.b64decode(terminal['stderr']['rawBodyBase64']),b'synthetic stderr')
                if failure=='invalid_json':self.assertEqual(base64.b64decode(terminal['output']['rawBodyBase64']),b'not JSON')
                if failure=='invalid_output_utf8':self.assertEqual(base64.b64decode(terminal['output']['rawBodyBase64']),b'\xffinvalid output')
                if failure=='invalid_stdout_utf8':self.assertEqual(base64.b64decode(terminal['stdout']['rawBodyBase64']),b'\xffinvalid events')
                current=outcomes.execution_binding(reading._codex_json, {'payload':{},'codex_cli':cli})
                self.assertEqual(row['executionBinding'],current)
                with self.assertRaises(outcomes.TerminalOutcomeError):invoke('first request')
                self.assertEqual(len(calls),1)
                mode[0]='success';self.assertEqual(invoke('different request'),{'blocks':[]})
                self.assertEqual(len(calls),2)
                self.assertEqual(sorted(json.loads(p.read_text())['status'] for p in (root/'accounting'/'api-cli-outcomes').glob('*/outcome.json')),['returned','terminal_failure'])

    def test_completed_direct_process_failures_are_terminal_and_not_redispatched(self):
        for failure in ['nonzero','invalid_json','invalid_output_utf8','missing_output']:
            with self.subTest(failure=failure):self.exercise('direct',failure)

    def test_completed_sol_transport_failures_are_terminal_before_parse_or_schema(self):
        for failure in ['nonzero','invalid_events','invalid_json','schema','invalid_stdout_utf8','invalid_output_utf8','missing_output']:
            with self.subTest(failure=failure):self.exercise('sol',failure)

    def test_actual_timeouts_remain_unknown_in_both_paths(self):
        for branch in ['direct','sol']:
            with self.subTest(branch=branch):self.exercise(branch,'timeout')
