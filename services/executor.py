import json
import re
import time
from dataclasses import dataclass, field
from http.cookies import SimpleCookie

import httpx

from services.parsers import parse_css, parse_jsonpath, parse_regex
from services.pipeline import (
    substitute_variables,
    substitute_in_dict,
    apply_transforms,
    validate_pipeline,
)


@dataclass
class StepResult:
    step_name: str
    step_type: str  # 'auth' or 'check'
    http_status: int = None
    duration_ms: int = 0
    extracted_vars: dict = field(default_factory=dict)
    response_body: str = None
    response_headers: dict = field(default_factory=dict)
    error: str = None
    skipped: bool = False


@dataclass
class ExecutionResult:
    step_results: list = field(default_factory=list)
    final_value: str = None
    previous_value: str = None
    value_changed: bool = False
    variables: dict = field(default_factory=dict)
    error: str = None
    reauth_triggered: bool = False


def execute_pipeline(pipeline_yaml, secrets, state_vars, previous_value=None):
    """Execute a full pipeline: auth steps (if needed) + check step.
    Returns ExecutionResult.
    """
    config, errors = validate_pipeline(pipeline_yaml)
    if errors:
        result = ExecutionResult()
        result.error = '; '.join(errors)
        return result

    variables = dict(state_vars or {})
    shared_headers = config.get('shared_headers') or {}
    auth_config = config.get('auth')
    check_config = config['check']
    result = ExecutionResult(previous_value=previous_value)

    # Run auth pipeline if auth section exists and no vars persisted yet
    if auth_config and auth_config.get('steps') and not variables:
        auth_result = _run_auth_steps(auth_config['steps'], shared_headers, variables, secrets)
        result.step_results.extend(auth_result['steps'])
        if auth_result['error']:
            result.error = auth_result['error']
            result.variables = variables
            return result
        variables.update(auth_result['variables'])

    # Run check step
    check_result = _run_check(check_config, shared_headers, variables, secrets)
    result.step_results.append(check_result)

    if check_result.error and not _should_reauth(check_config, check_result):
        result.error = check_result.error
        result.variables = variables
        return result

    # Check if reauth needed
    reauth_on = check_config.get('reauth_on')
    if reauth_on and auth_config and _should_reauth(check_config, check_result):
        max_retries = reauth_on.get('max_retries', 1)
        for attempt in range(max_retries):
            result.reauth_triggered = True
            # Clear auth-derived variables, re-run auth
            variables = {}
            auth_result = _run_auth_steps(auth_config['steps'], shared_headers, variables, secrets)
            result.step_results.extend(auth_result['steps'])
            if auth_result['error']:
                result.error = auth_result['error']
                result.variables = variables
                return result
            variables.update(auth_result['variables'])

            # Retry check
            check_result = _run_check(check_config, shared_headers, variables, secrets)
            result.step_results.append(check_result)

            if not _should_reauth(check_config, check_result):
                break
        else:
            if check_result.error:
                result.error = check_result.error
            else:
                result.error = 'Reauth exhausted: still failing after retries.'
            result.variables = variables
            return result

    if check_result.error:
        result.error = check_result.error
        result.variables = variables
        return result

    # Parse value from check response
    try:
        parsed_value = _parse_check_value(check_config, check_result.response_body)
        result.final_value = parsed_value
        if previous_value is not None and parsed_value != previous_value:
            result.value_changed = True
    except Exception as e:
        # If selector_missing triggers reauth, we already handled it above
        result.error = str(e)

    result.variables = variables
    return result


def execute_step_debug(step_config, step_type, shared_headers, variables, secrets):
    """Execute a single step for debugging. Returns StepResult."""
    if step_type == 'check':
        sr = _run_check(step_config, shared_headers, variables, secrets)
        # Also try parsing value for debug
        if not sr.error and sr.response_body:
            try:
                parsed = _parse_check_value(step_config, sr.response_body)
                sr.extracted_vars['__parsed_value__'] = parsed
            except Exception as e:
                sr.extracted_vars['__parse_error__'] = str(e)
        return sr
    else:
        return _execute_auth_step(step_config, shared_headers, variables, secrets)


def execute_pipeline_debug(pipeline_yaml, secrets):
    """Run all steps for debugging. Returns list of StepResult. Stops on failure."""
    config, errors = validate_pipeline(pipeline_yaml)
    if errors:
        sr = StepResult(step_name='validation', step_type='error', error='; '.join(errors))
        return [sr]

    variables = {}
    shared_headers = config.get('shared_headers') or {}
    results = []

    auth = config.get('auth')
    if auth and auth.get('steps'):
        for step in auth['steps']:
            sr = _execute_auth_step(step, shared_headers, variables, secrets)
            results.append(sr)
            if sr.error:
                return results
            variables.update(sr.extracted_vars)

    check = config.get('check')
    if check:
        sr = _run_check(check, shared_headers, variables, secrets)
        if not sr.error and sr.response_body:
            try:
                parsed = _parse_check_value(check, sr.response_body)
                sr.extracted_vars['__parsed_value__'] = parsed
            except Exception as e:
                sr.extracted_vars['__parse_error__'] = str(e)
        results.append(sr)

    return results


# --- Internal helpers ---

def _run_auth_steps(steps, shared_headers, variables, secrets):
    """Run all auth steps. Returns dict with 'steps', 'variables', 'error'."""
    result = {'steps': [], 'variables': {}, 'error': None}

    for step in steps:
        sr = _execute_auth_step(step, shared_headers, variables, secrets)
        result['steps'].append(sr)

        if sr.error:
            result['error'] = sr.error
            return result

        if sr.extracted_vars:
            result['variables'].update(sr.extracted_vars)
            variables.update(sr.extracted_vars)

    return result


def _execute_auth_step(step, shared_headers, variables, secrets):
    """Execute a single auth step. Returns StepResult."""
    name = step.get('name', 'unnamed')
    sr = StepResult(step_name=name, step_type='auth')

    # Check skip_if
    skip_if = step.get('skip_if')
    if skip_if and variables.get(skip_if):
        sr.skipped = True
        return sr

    # Delay before request
    delay = step.get('delay')
    if delay and delay > 0:
        time.sleep(delay)

    # Build request
    url, missing = substitute_variables(step.get('url', ''), variables, secrets)
    if missing:
        sr.error = f'Missing variables: {", ".join(missing)}'
        return sr

    method = (step.get('method') or 'GET').upper()
    headers = dict(shared_headers)
    step_headers = step.get('headers') or {}
    step_headers_sub, missing = substitute_in_dict(step_headers, variables, secrets)
    if missing:
        sr.error = f'Missing variables in headers: {", ".join(missing)}'
        return sr
    headers.update(step_headers_sub)

    body = step.get('body') or ''
    if body:
        body, missing = substitute_variables(body, variables, secrets)
        if missing:
            sr.error = f'Missing variables in body: {", ".join(missing)}'
            return sr

    timeout = step.get('timeout', 30)

    # Execute request
    start = time.time()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.request(method, url, headers=headers, content=body if body else None)
        sr.http_status = resp.status_code
        sr.response_body = resp.text
        sr.response_headers = dict(resp.headers)
        sr.duration_ms = int((time.time() - start) * 1000)
    except Exception as e:
        sr.duration_ms = int((time.time() - start) * 1000)
        sr.error = str(e)
        return sr

    # Match status handler
    on_status = step.get('on_status', {})
    handler = _match_status_handler(sr.http_status, on_status)

    if handler is None:
        sr.error = f'No handler for HTTP {sr.http_status}'
        return sr

    action = handler.get('action')
    if action == 'fail':
        sr.error = handler.get('message', f'Step failed with HTTP {sr.http_status}')
        return sr

    # Extract variables
    extracts = handler.get('extract') or []
    for ext in extracts:
        try:
            value = _extract_value(ext, sr.response_body, sr.response_headers, sr.http_status)
            transforms = ext.get('transform')
            if transforms:
                value = apply_transforms(value, transforms)
            sr.extracted_vars[ext['name']] = value
        except Exception as e:
            sr.error = f'Extraction "{ext["name"]}" failed: {e}'
            return sr

    return sr


def _run_check(check_config, shared_headers, variables, secrets):
    """Execute the check step HTTP request. Returns StepResult (without parsing)."""
    sr = StepResult(step_name='check', step_type='check')

    url, missing = substitute_variables(check_config.get('url', ''), variables, secrets)
    if missing:
        sr.error = f'Missing variables: {", ".join(missing)}'
        return sr

    method = (check_config.get('method') or 'GET').upper()
    headers = dict(shared_headers)
    check_headers = check_config.get('headers') or {}
    check_headers_sub, missing = substitute_in_dict(check_headers, variables, secrets)
    if missing:
        sr.error = f'Missing variables in headers: {", ".join(missing)}'
        return sr
    headers.update(check_headers_sub)

    body = check_config.get('body') or ''
    if body:
        body, missing = substitute_variables(body, variables, secrets)
        if missing:
            sr.error = f'Missing variables in body: {", ".join(missing)}'
            return sr

    timeout = check_config.get('timeout', 30)

    start = time.time()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.request(method, url, headers=headers, content=body if body else None)
        sr.http_status = resp.status_code
        sr.response_body = resp.text
        sr.response_headers = dict(resp.headers)
        sr.duration_ms = int((time.time() - start) * 1000)
    except Exception as e:
        sr.duration_ms = int((time.time() - start) * 1000)
        sr.error = str(e)

    return sr


def _parse_check_value(check_config, response_body):
    """Parse value from check response body using selector."""
    selector_type = check_config['selector_type']
    selector = check_config['selector']

    if selector_type == 'css':
        return parse_css(response_body, selector)
    elif selector_type == 'jsonpath':
        return parse_jsonpath(response_body, selector)
    elif selector_type == 'regex':
        return parse_regex(response_body, selector)
    else:
        raise ValueError(f'Unknown selector type: {selector_type}')


def _should_reauth(check_config, check_result):
    """Check if reauth is needed based on check result."""
    reauth_on = check_config.get('reauth_on')
    if not reauth_on:
        return False

    # Status code match
    status_codes = reauth_on.get('status', [])
    if check_result.http_status in status_codes:
        return True

    # Selector missing
    if reauth_on.get('selector_missing') and check_result.response_body:
        try:
            _parse_check_value(check_config, check_result.response_body)
        except (ValueError, Exception):
            return True

    return False


def _match_status_handler(status_code, on_status):
    """Find matching handler for a status code."""
    # Exact match first
    if status_code in on_status:
        return on_status[status_code]
    if str(status_code) in on_status:
        return on_status[str(status_code)]

    # Wildcard match (e.g., "2xx")
    wildcard = f'{status_code // 100}xx'
    if wildcard in on_status:
        return on_status[wildcard]

    # Default
    if 'default' in on_status:
        return on_status['default']

    return None


def _extract_value(ext, response_body, response_headers, http_status):
    """Extract a single value from response."""
    from_field = ext['from']

    if from_field == 'status':
        return str(http_status)

    if from_field == 'body':
        if 'jsonpath' in ext:
            return parse_jsonpath(response_body, ext['jsonpath'])
        elif 'css' in ext:
            return parse_css(response_body, ext['css'])
        elif 'regex' in ext:
            return parse_regex(response_body, ext['regex'])
        elif 'key' in ext:
            # treat body as JSON, get key directly
            data = json.loads(response_body)
            value = data.get(ext['key'])
            if value is None:
                raise ValueError(f'Key "{ext["key"]}" not found in response body.')
            return str(value) if not isinstance(value, str) else value
        else:
            raise ValueError('No extraction method specified for body.')

    if from_field == 'header':
        key = ext.get('key')
        if not key:
            raise ValueError('Header extraction requires "key".')
        value = response_headers.get(key) or response_headers.get(key.lower())
        if value is None:
            raise ValueError(f'Header "{key}" not found in response.')
        if 'regex' in ext:
            return parse_regex(value, ext['regex'])
        return value

    if from_field == 'cookie':
        key = ext.get('key')
        if not key:
            raise ValueError('Cookie extraction requires "key".')
        set_cookie = response_headers.get('set-cookie', '')
        cookie = SimpleCookie()
        cookie.load(set_cookie)
        if key not in cookie:
            raise ValueError(f'Cookie "{key}" not found.')
        return cookie[key].value

    raise ValueError(f'Unknown extraction source: {from_field}')
