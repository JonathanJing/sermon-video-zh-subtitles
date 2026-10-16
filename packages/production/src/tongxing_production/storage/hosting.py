"""Firebase Hosting and Cloud Storage adapter: the defaults a publication uses.

An ADC-authorised session for the GCS lease object and the Hosting REST API, the
generation-fenced lease object, the public GET and the firebase CLI runner. The
publication rules (lease order, attempts, version receipts, propagation waits,
reconciliation) stay in tongxing_production.delivery.publication. google-auth is
the optional ``hosting`` extra and is imported only here, when a session opens.
"""
from __future__ import annotations
import json
import subprocess
from urllib.parse import quote
from urllib.request import Request, urlopen


def authenticated_transport():
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    session = AuthorizedSession(credentials)
    def request(method, url, *, data=None, headers=None, timeout=60):
        response = session.request(method, url, data=data, headers=headers, timeout=timeout)
        # Never return authentication headers or provider error bodies.
        if response.status_code not in (200, 201, 204):
            raise ValueError(f'Remote operation rejected: HTTP {response.status_code}')
        return response.json() if response.content else {}
    return request


class RemoteLease:
    def __init__(self, request, bucket, site):
        self.request = request
        self.name = 'sermon-publisher-leases/' + site + '.json'
        self.bucket = bucket
        self.object_url = 'https://storage.googleapis.com/storage/v1/b/' + quote(bucket, safe='') + '/o/' + quote(self.name, safe='')
        self.generation = None

    def acquire(self, attempt):
        url = 'https://storage.googleapis.com/upload/storage/v1/b/' + quote(self.bucket, safe='') + '/o?uploadType=media&ifGenerationMatch=0&name=' + quote(self.name, safe='')
        result = self.request('POST', url, data=json.dumps(attempt).encode(), headers={'Content-Type': 'application/json'})
        self.generation = str(result['generation'])
        return self.generation

    def check(self):
        result = self.request('GET', self.object_url)
        if str(result['generation']) != self.generation:
            raise ValueError('Publisher lease ownership changed')

    def release(self):
        if self.generation is None:
            raise ValueError('Lease is not held')
        self.request('DELETE', self.object_url + '?ifGenerationMatch=' + self.generation)


def public_reader(url, *, timeout=120):
    with urlopen(Request(url, headers={'Cache-Control': 'no-cache'}), timeout=timeout) as response:
        return response.status, response.read()


def run(*arguments, **options):
    """The firebase CLI runner; ``subprocess.run`` is looked up per call so patches apply."""
    return subprocess.run(*arguments, **options)
