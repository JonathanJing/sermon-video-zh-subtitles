"""Safe selected-project binding; never persists or returns credential values."""
import os
import re
from urllib.parse import urlsplit


def safe_route(value):
    if not isinstance(value, dict) or set(value) != {'schemaVersion', 'environment', 'projectId', 'credentialAlias', 'identitySource'}:
        return None
    env = value.get('environment')
    if (env not in {'dev', 'prod'} or value.get('schemaVersion') != 'sermon-openai-runtime-route-v1' or
            value.get('identitySource') != 'configured_runtime' or
            not isinstance(value.get('projectId'), str) or len(value['projectId']) > 128 or
            not re.fullmatch(r'proj_[A-Za-z0-9_-]+', value['projectId']) or
            value.get('credentialAlias') != f'tongxing-{env}-runtime'):
        return None
    return dict(value)


def selected_route():
    environment = os.environ.get('SERMON_OPENAI_ENVIRONMENT')
    if environment is None:
        return None  # Legacy invocation, including existing cloud jobs.
    project = os.environ.get('OPENAI_PROJECT_ID', '')
    alias = os.environ.get('SERMON_OPENAI_CREDENTIAL_ALIAS')
    if (environment not in {'dev', 'prod'} or
            len(project) > 128 or not re.fullmatch(r'proj_[A-Za-z0-9_-]+', project) or
            alias != f'tongxing-{environment}-runtime' or not os.environ.get('OPENAI_API_KEY')):
        raise ValueError('invalid_selected_openai_runtime')
    return {'schemaVersion': 'sermon-openai-runtime-route-v1', 'environment': environment,
            'projectId': project, 'credentialAlias': alias, 'identitySource': 'configured_runtime'}


def project_headers(api_key):
    route = selected_route()
    if route is None:
        return {}
    if api_key != os.environ.get('OPENAI_API_KEY'):
        raise ValueError('selected_openai_credential_override')
    return {'OpenAI-Project': route['projectId']}


def reject_secret_override(secret_reference):
    if secret_reference and selected_route() is not None:
        raise ValueError('selected_openai_secret_override')


def bind_request(request):
    """Guard central transport, including callers constructing their own headers."""
    route = selected_route()
    if route is None:
        return
    origin = urlsplit(request.full_url)
    if origin.scheme != 'https' or origin.netloc != 'api.openai.com':
        raise ValueError('selected_openai_origin_mismatch')
    if request.get_header('Authorization') != 'Bearer ' + os.environ['OPENAI_API_KEY']:
        raise ValueError('selected_openai_credential_override')
    existing = request.get_header('Openai-project')
    if existing is not None and existing != route['projectId']:
        raise ValueError('selected_openai_project_override')
    request.add_header('OpenAI-Project', route['projectId'])
