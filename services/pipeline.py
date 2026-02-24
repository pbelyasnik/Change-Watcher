import re
import base64
import json

import yaml


VALID_METHODS = {'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD'}
VALID_SELECTOR_TYPES = {'css', 'jsonpath', 'regex'}
VALID_EXTRACT_FROM = {'body', 'header', 'cookie', 'status'}
VALID_ACTIONS = {'fail', 'retry'}
VALID_TRANSFORMS = {
    'strip', 'lower', 'upper', 'base64_decode', 'base64_encode', 'json_parse',
    'prefix', 'suffix', 'regex', 'jsonpath', 'replace',
}

DEFAULT_YAML_TEMPLATE = """\
# shared_headers:
#   Accept: "application/json"

# auth:
#   steps:
#     - name: "Login"
#       url: "https://example.com/login"
#       method: POST
#       headers:
#         Content-Type: "application/json"
#       body: |
#         {"username": "{{username}}", "password": "{{password}}"}
#       on_status:
#         200:
#           extract:
#             - name: "auth_token"
#               from: body
#               jsonpath: "$.token"
#         default:
#           action: fail

check:
  url: ""
  method: GET
  selector_type: css
  selector: ""
  # reauth_on:
  #   status: [401, 403]
  #   max_retries: 1
"""


def parse_pipeline(yaml_string):
    """Parse YAML string into pipeline config dict. Returns (config, errors)."""
    errors = []
    if not yaml_string or not yaml_string.strip():
        return None, ['Pipeline config is empty.']

    try:
        config = yaml.safe_load(yaml_string)
    except yaml.YAMLError as e:
        msg = str(e)
        return None, [f'YAML syntax error: {msg}']

    if not isinstance(config, dict):
        return None, ['Pipeline config must be a YAML mapping.']

    return config, errors


def validate_pipeline(yaml_string):
    """Full validation. Returns (parsed_config, list_of_error_strings)."""
    config, errors = parse_pipeline(yaml_string)
    if errors:
        return config, errors

    allowed_top_keys = {'shared_headers', 'auth', 'check'}
    unknown = set(config.keys()) - allowed_top_keys
    if unknown:
        errors.append(f'Unknown top-level keys: {", ".join(sorted(unknown))}')

    # shared_headers
    shared = config.get('shared_headers')
    if shared is not None and not isinstance(shared, dict):
        errors.append('shared_headers must be a mapping.')

    # auth section
    auth = config.get('auth')
    if auth is not None:
        errors.extend(_validate_auth(auth))

    # check section
    check = config.get('check')
    if check is None:
        errors.append('Missing required "check" section.')
    else:
        errors.extend(_validate_check(check))

    return config, errors


def _validate_auth(auth):
    errors = []
    if not isinstance(auth, dict):
        return ['auth must be a mapping.']

    unknown = set(auth.keys()) - {'steps'}
    if unknown:
        errors.append(f'Unknown keys in auth: {", ".join(sorted(unknown))}')

    steps = auth.get('steps')
    if not steps or not isinstance(steps, list):
        errors.append('auth.steps must be a non-empty list.')
        return errors

    names = set()
    for i, step in enumerate(steps):
        prefix = f'auth.steps[{i}]'
        if not isinstance(step, dict):
            errors.append(f'{prefix} must be a mapping.')
            continue

        name = step.get('name')
        if not name or not isinstance(name, str):
            errors.append(f'{prefix}: "name" is required and must be a string.')
        elif name in names:
            errors.append(f'{prefix}: duplicate step name "{name}".')
        else:
            names.add(name)

        errors.extend(_validate_step(step, prefix))

    return errors


def _validate_step(step, prefix):
    errors = []
    allowed = {'name', 'url', 'method', 'headers', 'body', 'timeout', 'delay', 'on_status', 'skip_if'}
    unknown = set(step.keys()) - allowed
    if unknown:
        errors.append(f'{prefix}: unknown keys: {", ".join(sorted(unknown))}')

    if not step.get('url'):
        errors.append(f'{prefix}: "url" is required.')

    method = step.get('method', 'GET')
    if isinstance(method, str):
        method = method.upper()
    if method not in VALID_METHODS:
        errors.append(f'{prefix}: invalid method "{method}".')

    headers = step.get('headers')
    if headers is not None and not isinstance(headers, dict):
        errors.append(f'{prefix}: headers must be a mapping.')

    timeout = step.get('timeout')
    if timeout is not None:
        if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > 120:
            errors.append(f'{prefix}: timeout must be 1-120 seconds.')

    delay = step.get('delay')
    if delay is not None:
        if not isinstance(delay, (int, float)) or delay < 0 or delay > 60:
            errors.append(f'{prefix}: delay must be 0-60 seconds.')

    skip_if = step.get('skip_if')
    if skip_if is not None and not isinstance(skip_if, str):
        errors.append(f'{prefix}: skip_if must be a variable name string.')

    on_status = step.get('on_status')
    if not on_status or not isinstance(on_status, dict):
        errors.append(f'{prefix}: "on_status" is required and must be a mapping.')
    else:
        errors.extend(_validate_on_status(on_status, prefix))

    return errors


def _validate_on_status(on_status, prefix):
    errors = []
    for key, handler in on_status.items():
        key_str = str(key)
        # validate key: integer, wildcard like "2xx", or "default"
        if key_str != 'default' and not re.match(r'^\d{3}$', key_str) and not re.match(r'^[1-5]xx$', key_str):
            errors.append(f'{prefix}.on_status: invalid status key "{key_str}". '
                          f'Use integer (200), wildcard (2xx), or "default".')

        if not isinstance(handler, dict):
            errors.append(f'{prefix}.on_status.{key_str}: handler must be a mapping.')
            continue

        allowed = {'extract', 'action', 'message', 'next'}
        unknown = set(handler.keys()) - allowed
        if unknown:
            errors.append(f'{prefix}.on_status.{key_str}: unknown keys: {", ".join(sorted(unknown))}')

        action = handler.get('action')
        if action and action not in VALID_ACTIONS:
            errors.append(f'{prefix}.on_status.{key_str}: invalid action "{action}".')

        extracts = handler.get('extract')
        if extracts is not None:
            if not isinstance(extracts, list):
                errors.append(f'{prefix}.on_status.{key_str}: extract must be a list.')
            else:
                for j, ext in enumerate(extracts):
                    errors.extend(_validate_extraction(ext, f'{prefix}.on_status.{key_str}.extract[{j}]'))

        if not action and not extracts:
            errors.append(f'{prefix}.on_status.{key_str}: must have "extract" or "action".')

    return errors


def _validate_extraction(ext, prefix):
    errors = []
    if not isinstance(ext, dict):
        return [f'{prefix}: extraction must be a mapping.']

    if not ext.get('name') or not isinstance(ext.get('name'), str):
        errors.append(f'{prefix}: "name" is required.')

    from_field = ext.get('from')
    if not from_field or from_field not in VALID_EXTRACT_FROM:
        errors.append(f'{prefix}: "from" must be one of: {", ".join(sorted(VALID_EXTRACT_FROM))}.')

    # must have an extraction method
    methods = {'jsonpath', 'css', 'regex', 'key'}
    found = [m for m in methods if m in ext]
    if not found and from_field != 'status':
        errors.append(f'{prefix}: must specify extraction method (jsonpath, css, regex, or key).')

    transform = ext.get('transform')
    if transform is not None:
        if not isinstance(transform, list):
            errors.append(f'{prefix}: transform must be a list.')
        else:
            for k, t in enumerate(transform):
                errors.extend(_validate_transform(t, f'{prefix}.transform[{k}]'))

    return errors


def _validate_transform(t, prefix):
    errors = []
    if isinstance(t, str):
        if t not in VALID_TRANSFORMS:
            errors.append(f'{prefix}: unknown transform "{t}".')
    elif isinstance(t, dict):
        for key in t:
            if key not in VALID_TRANSFORMS:
                errors.append(f'{prefix}: unknown transform "{key}".')
            if key == 'replace':
                val = t[key]
                if not isinstance(val, dict) or 'old' not in val or 'new' not in val:
                    errors.append(f'{prefix}: replace must have "old" and "new" keys.')
    else:
        errors.append(f'{prefix}: transform must be a string or mapping.')
    return errors


def _validate_check(check):
    errors = []
    if not isinstance(check, dict):
        return ['check must be a mapping.']

    allowed = {'url', 'method', 'headers', 'body', 'timeout', 'selector_type', 'selector', 'reauth_on'}
    unknown = set(check.keys()) - allowed
    if unknown:
        errors.append(f'check: unknown keys: {", ".join(sorted(unknown))}')

    if not check.get('url'):
        errors.append('check: "url" is required.')

    method = check.get('method', 'GET')
    if isinstance(method, str):
        method = method.upper()
    if method not in VALID_METHODS:
        errors.append(f'check: invalid method "{method}".')

    selector_type = check.get('selector_type')
    if not selector_type or selector_type not in VALID_SELECTOR_TYPES:
        errors.append(f'check: "selector_type" must be one of: {", ".join(sorted(VALID_SELECTOR_TYPES))}.')

    if not check.get('selector'):
        errors.append('check: "selector" is required.')

    headers = check.get('headers')
    if headers is not None and not isinstance(headers, dict):
        errors.append('check: headers must be a mapping.')

    timeout = check.get('timeout')
    if timeout is not None:
        if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > 120:
            errors.append('check: timeout must be 1-120 seconds.')

    reauth = check.get('reauth_on')
    if reauth is not None:
        errors.extend(_validate_reauth(reauth))

    return errors


def _validate_reauth(reauth):
    errors = []
    if not isinstance(reauth, dict):
        return ['check.reauth_on must be a mapping.']

    allowed = {'status', 'selector_missing', 'max_retries'}
    unknown = set(reauth.keys()) - allowed
    if unknown:
        errors.append(f'check.reauth_on: unknown keys: {", ".join(sorted(unknown))}')

    status = reauth.get('status')
    if status is not None:
        if not isinstance(status, list):
            errors.append('check.reauth_on.status must be a list of integers.')
        else:
            for s in status:
                if not isinstance(s, int):
                    errors.append(f'check.reauth_on.status: "{s}" is not an integer.')

    sm = reauth.get('selector_missing')
    if sm is not None and not isinstance(sm, bool):
        errors.append('check.reauth_on.selector_missing must be true or false.')

    mr = reauth.get('max_retries')
    if mr is not None:
        if not isinstance(mr, int) or mr < 1:
            errors.append('check.reauth_on.max_retries must be an integer >= 1.')

    return errors


# --- Variable substitution ---

_VAR_PATTERN = re.compile(r'\{\{(\w+)\}\}')


def substitute_variables(template, variables, secrets=None):
    """Replace {{var}} placeholders. Returns (result, list_of_missing_vars)."""
    if not template:
        return template, []

    if not isinstance(template, str):
        template = str(template)

    combined = dict(variables)
    if secrets:
        combined.update(secrets)

    missing = []

    def replacer(match):
        name = match.group(1)
        if name in combined:
            return str(combined[name])
        missing.append(name)
        return match.group(0)

    result = _VAR_PATTERN.sub(replacer, template)
    return result, missing


def substitute_in_dict(d, variables, secrets=None):
    """Substitute variables in all string values of a dict (keys and values)."""
    if not d:
        return {}, []
    all_missing = []
    result = {}
    for k, v in d.items():
        new_k, m = substitute_variables(str(k), variables, secrets)
        all_missing.extend(m)
        if isinstance(v, str):
            new_v, m = substitute_variables(v, variables, secrets)
            all_missing.extend(m)
        else:
            new_v = v
        result[new_k] = new_v
    return result, all_missing


# --- Transforms ---

def apply_transforms(value, transforms):
    """Apply a list of transforms to a value. Returns transformed string."""
    from services.parsers import parse_jsonpath

    for t in transforms:
        if isinstance(t, str):
            value = _apply_single_transform(value, t)
        elif isinstance(t, dict):
            for op, arg in t.items():
                value = _apply_single_transform(value, op, arg)
    return value


def _apply_single_transform(value, op, arg=None):
    from services.parsers import parse_jsonpath

    if op == 'strip':
        return value.strip()
    elif op == 'lower':
        return value.lower()
    elif op == 'upper':
        return value.upper()
    elif op == 'base64_decode':
        return base64.b64decode(value.encode()).decode()
    elif op == 'base64_encode':
        return base64.b64encode(value.encode()).decode()
    elif op == 'json_parse':
        return value  # keep as string, but validate it's JSON
    elif op == 'prefix':
        return str(arg) + value
    elif op == 'suffix':
        return value + str(arg)
    elif op == 'regex':
        m = re.search(str(arg), value, re.DOTALL)
        if m:
            return m.group(1) if m.groups() else m.group(0)
        raise ValueError(f'Transform regex "{arg}" did not match.')
    elif op == 'jsonpath':
        return parse_jsonpath(value, str(arg))
    elif op == 'replace':
        return value.replace(str(arg['old']), str(arg['new']))
    else:
        raise ValueError(f'Unknown transform: {op}')


def get_steps_from_config(config):
    """Return list of (step_type, step_dict) for display/debugging.
    step_type is 'auth' or 'check'.
    """
    steps = []
    auth = config.get('auth')
    if auth and auth.get('steps'):
        for s in auth['steps']:
            steps.append(('auth', s))
    check = config.get('check')
    if check:
        steps.append(('check', check))
    return steps
