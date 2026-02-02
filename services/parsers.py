import json
import re

from bs4 import BeautifulSoup
from jsonpath_ng import parse as jsonpath_parse


def parse_css(html_content: str, selector: str) -> str:
    soup = BeautifulSoup(html_content, 'lxml')
    element = soup.select_one(selector)
    if element is None:
        raise ValueError(f'No element found matching CSS selector: {selector}')
    return element.get_text(strip=True)


def parse_jsonpath(json_content: str, expression: str) -> str:
    data = json.loads(json_content)
    jsonpath_expr = jsonpath_parse(expression)
    matches = jsonpath_expr.find(data)
    if not matches:
        raise ValueError(f'No match found for JSONPath expression: {expression}')
    value = matches[0].value
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def parse_regex(content: str, pattern: str) -> str:
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        raise ValueError(f'No match found for regex pattern: {pattern}')
    if match.groups():
        return match.group(1)
    return match.group(0)
