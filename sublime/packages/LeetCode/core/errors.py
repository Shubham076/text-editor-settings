"""Turning a failed request into a message that says what went wrong and what to do.
Pure Python: no Sublime imports."""

import http.client
import socket
import ssl
import urllib.error


class LeetCodeError(Exception):
    """A failure worth showing to the user as-is."""


_HTTP = {
    400: "LeetCode rejected the request. The code or test input may be malformed.",
    401: "You are signed out of LeetCode. Copy a fresh Cookie header into cookie_string "
         "(Preferences > Package Settings > LeetCode > Settings).",
    403: "LeetCode refused the request. Your session has probably expired: copy a fresh Cookie "
         "header into cookie_string (Preferences > Package Settings > LeetCode > Settings). "
         "If the cookie is new, LeetCode's bot protection is blocking requests from outside a browser.",
    404: "LeetCode has no such problem or submission.",
    429: "LeetCode is rate limiting you. Wait a minute and try again.",
    499: "LeetCode's bot protection turned the request away (HTTP 499). It only accepts requests "
         "that look like the browser you signed in with:\n"
         "1. In that browser, open leetcode.com, then Developer Tools > Network, and pick any "
         "leetcode.com request.\n"
         "2. Copy its whole Cookie header into cookie_string (it should include cf_clearance, "
         "csrftoken and LEETCODE_SESSION).\n"
         "3. Copy its User-Agent header into user_agent.\n"
         "Both are in Preferences > Package Settings > LeetCode > Settings.",
}


def explain(error, action):
    """A LeetCodeError for a failure raised while doing ``action`` (e.g. "load the problem list")."""
    return LeetCodeError("Could not {}.\n\n{}".format(action, _reason(error)))


def _reason(error):
    if isinstance(error, urllib.error.HTTPError):
        if error.code in _HTTP:
            return _HTTP[error.code]
        if error.code >= 500:
            return "LeetCode is having trouble (HTTP {}). Try again in a moment.".format(error.code)
        return "LeetCode answered HTTP {}{}.".format(
            error.code, " ({})".format(error.reason) if error.reason else "")

    cause = getattr(error, "reason", error)  # URLError wraps the real error
    if isinstance(cause, ssl.SSLCertVerificationError):
        return ("The secure connection to leetcode.com could not be verified: the certificate it "
                "presented is not signed by an authority this computer trusts. This usually means "
                "a company proxy or security tool is inspecting HTTPS traffic. Export its root "
                "certificate as a .pem file and set ca_bundle in the LeetCode settings to its path."
                "\n\nDetails: {}".format(cause.verify_message or cause))
    if isinstance(cause, ssl.SSLError):
        return "The secure connection to leetcode.com failed: {}".format(cause)
    if isinstance(cause, (socket.timeout, TimeoutError)):
        return "LeetCode did not answer in time. Check your connection and try again."
    if isinstance(cause, socket.gaierror):
        return "leetcode.com could not be found. You appear to be offline, or DNS is failing."
    if isinstance(cause, (ConnectionError, http.client.HTTPException)):
        return ("The connection to leetcode.com was refused or dropped before the answer "
                "arrived. Check your network or proxy and try again.")
    if isinstance(error, ValueError):
        return ("LeetCode sent a page instead of data. This is usually its bot protection "
                "or a sign-in page: refresh cookie_string in the LeetCode settings.")
    return "Unexpected network error: {}".format(cause)
