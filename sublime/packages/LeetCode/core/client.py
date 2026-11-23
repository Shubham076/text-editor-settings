"""Blocking calls to LeetCode. Call these from a worker thread (see ui/tasks.py)."""

import http.client
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

from . import config
from .errors import LeetCodeError, explain
from .problem import Question

BASE_URL = "https://leetcode.com"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
POLL_INTERVAL = 1.0
RUN_TIMEOUT = 30
SUBMIT_TIMEOUT = 90

QUESTION_QUERY = """
query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionId questionFrontendId title titleSlug difficulty content hints
    exampleTestcaseList metaData
    topicTags { name }
    codeSnippets { langSlug code }
  }
}
"""


MACOS_KEYCHAINS = ["/System/Library/Keychains/SystemRootCertificates.keychain",
                   "/Library/Keychains/System.keychain"]
_ssl_contexts = {}  # ca_bundle setting -> context, built once per value


def _ssl_context():
    """A context that trusts what the operating system trusts.

    Sublime's bundled Python ships without a certificate store, so on its own it cannot verify
    any HTTPS site. On macOS the roots are read from the keychains, which also covers a company
    proxy's certificate installed there. ``ca_bundle`` adds a PEM file on top.
    """
    bundle = config.get("ca_bundle", "") or ""
    if bundle not in _ssl_contexts:
        context = ssl.create_default_context()
        if sys.platform == "darwin":
            try:
                pem = subprocess.run(["/usr/bin/security", "find-certificate", "-a", "-p"] + MACOS_KEYCHAINS,
                                     capture_output=True, text=True, timeout=15).stdout
                if pem:
                    context.load_verify_locations(cadata=pem)
            except (OSError, subprocess.SubprocessError, ssl.SSLError) as error:
                print("[LeetCode] Could not read the system keychains: {}".format(error))
        if bundle:
            try:
                context.load_verify_locations(cafile=bundle)
            except (OSError, ssl.SSLError) as error:
                raise LeetCodeError("ca_bundle in the LeetCode settings points to '{}', which "
                                    "could not be read as a PEM certificate file: {}".format(bundle, error))
        _ssl_contexts[bundle] = context
    return _ssl_contexts[bundle]


def _request(path, action, payload=None, referer=BASE_URL + "/", timeout=30):
    """Call LeetCode; ``action`` names what is being done, for the error message."""
    headers = {
        "User-Agent": config.get("user_agent", "") or USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": BASE_URL,
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
    }
    cookie = config.get("cookie_string", "")
    if cookie:
        headers["Cookie"] = cookie
        csrf = re.search(r"csrftoken=([^;\s]+)", cookie)
        if csrf:
            headers["X-CSRFToken"] = csrf.group(1)
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(BASE_URL + path, data=body, headers=headers)
    config.debug("{} {}", "POST" if body else "GET", path)
    context = _ssl_context()
    attempts = 1 if body else 2  # a read is safe to repeat; a run or submission is not
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                return json.loads(response.read().decode("utf-8"))
        except (http.client.HTTPException, ConnectionError) as error:  # dropped mid-response
            config.debug("{} dropped: {!r}", path, error)
            if attempt == attempts - 1:
                raise explain(error, action)
        except (OSError, ValueError) as error:  # URLError and HTTPError are OSErrors
            config.debug("{} failed: {!r} {}", path, error, _error_body(error))
            raise explain(error, action)


def _error_body(error):
    """The start of an HTTP error's body, for the debug log: it usually says who refused."""
    try:
        return error.read(300).decode("utf-8", "replace") if hasattr(error, "read") else ""
    except (OSError, ValueError):
        return ""


def _require_login(action):
    if not config.get("cookie_string", ""):
        raise LeetCodeError(
            "Could not {}.\n\nRunning and submitting need your LeetCode session. Sign in to "
            "leetcode.com in a browser, copy the Cookie header of any request there, and set it as "
            "cookie_string (Preferences > Package Settings > LeetCode > Settings).".format(action))


def fetch_problem_list():
    """Every problem, as the ``stat_status_pairs`` entries of LeetCode's list API."""
    return _request("/api/problems/all/", "load the problem list",
                    referer=BASE_URL + "/problemset/")["stat_status_pairs"]


def fetch_question(slug, use_cache=True):
    cache_name = "question_" + slug
    data = config.read_cache(cache_name, config.get("cache_expiry", 86400)) if use_cache else None
    if data is None:
        response = _request("/graphql", "open '{}'".format(slug), {
            "operationName": "questionData", "variables": {"titleSlug": slug}, "query": QUESTION_QUERY})
        data = (response.get("data") or {}).get("question")
        if not data:
            raise LeetCodeError("LeetCode has no problem named '{}'.".format(slug))
        config.write_cache(cache_name, data)
    return Question.from_graphql(data)


def run_code(question, language, code, data_input):
    """Run code against ``data_input`` on LeetCode's judge; returns the finished check response."""
    action = "run the tests"
    _require_login(action)
    referer = "{}/problems/{}/".format(BASE_URL, question.slug)
    started = _request("/problems/{}/interpret_solution/".format(question.slug), action, {
        "question_id": question.id, "lang": language, "typed_code": code,
        "data_input": data_input, "judge_type": "large"}, referer)
    if "interpret_id" not in started:
        raise LeetCodeError("Could not run the tests.\n\nLeetCode said: {}".format(
            started.get("error") or "nothing useful"))
    return _wait_for(started["interpret_id"], action, referer, RUN_TIMEOUT)


def submit(question, language, code):
    """Submit code; returns the finished check response."""
    action = "submit the solution"
    _require_login(action)
    referer = "{}/problems/{}/".format(BASE_URL, question.slug)
    started = _request("/problems/{}/submit/".format(question.slug), action, {
        "question_id": question.id, "lang": language, "typed_code": code}, referer)
    if "submission_id" not in started:
        raise LeetCodeError("Could not submit the solution.\n\nLeetCode said: {}".format(
            started.get("error") or "nothing useful"))
    return _wait_for(started["submission_id"], action, referer, SUBMIT_TIMEOUT)


def _wait_for(check_id, action, referer, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        response = _request("/submissions/detail/{}/check/".format(check_id), action, referer=referer)
        if response.get("state") == "SUCCESS":
            return response
        if response.get("state") == "FAILURE":
            raise LeetCodeError("Could not {}.\n\nLeetCode's judge failed: {}".format(
                action, response.get("status_msg") or "no reason given"))
    raise LeetCodeError("Could not {}.\n\nLeetCode's judge did not finish within {} seconds. "
                        "It may be busy; try again.".format(action, timeout))
