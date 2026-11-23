# LeetCode

Browse LeetCode problems, write the solution in Sublime Text, run it against LeetCode's own
judge and submit it.

## Commands

| Command palette | Does |
| :--- | :--- |
| LeetCode: Search Problems | Fuzzy-pick a problem and open it. |
| LeetCode: Show Problems Panel | Paged list in a bottom panel with difficulty and solved/todo filters; click a row to open it. |
| LeetCode: Refresh Problems | Re-downloads the problem list. |
| LeetCode: Show Test Cases | Opens the test panel beside the solution. |
| LeetCode: Add Test Case | Adds a custom case to the panel. |
| LeetCode: Run Tests | Runs every case in one request (`ctrl+shift+r` in a solution file). |
| LeetCode: Submit Solution | Submits the code and shows the verdict in a bottom panel. |

Opening a problem writes a solution file: a comment header, the description, and the starter
code between two marker lines. Only the code between `Do not remove code start` and
`Do not remove code end` is sent to LeetCode. The first line identifies the problem:

```
// @leetcode id=1 slug=two-sum lang=java
```

Files written before that line existed (`// LeetCode Problem: Two Sum`) still work.

## Test cases

- The default cases are the problem's own examples, taken from LeetCode's `exampleTestcaseList`
  rather than scraped from the description. `metaData` gives the parameter names and how many
  values a case has.
- A custom case is typed as `nums = [3,2,4], target = 6` or just `[3,2,4], 6`. The prompt is
  prefilled with the first example, and a wrong number of values is reported before anything
  is sent. Custom cases are saved per problem and come back the next time it is opened.
- Expected output of a custom case is filled in by the judge when the case runs.
- Stdout (`print`, `System.out`) of each case is shown under it.

## Setup

Browsing and opening problems works without signing in. Running tests and submitting need your
leetcode.com session, which you give the package as two settings: `cookie_string` and
`user_agent`. Both must come from the same browser, because LeetCode's bot protection ties the
cookie to the browser it was issued to.

### Add the cookie and user agent

1. In Chrome, Edge, Firefox or Safari, sign in to [leetcode.com](https://leetcode.com) and open
   any problem page.
2. Open the developer tools (`Cmd+Option+I` on macOS, `F12` or `Ctrl+Shift+I` elsewhere) and
   switch to the **Network** tab. In Safari, first turn on
   `Settings > Advanced > Show features for web developers`.
3. Reload the page so the tab fills with requests.
4. Type `graphql` in the Network tab's filter box and click any request to `leetcode.com/graphql`.
5. In the **Headers** pane, scroll to **Request Headers**.
6. Find `Cookie` (`cookie` in some browsers). Right-click its value and choose **Copy value**.
   Copy the whole value: it is one long line of `name=value;` pairs.
7. Find `User-Agent` in the same list and copy its value too. It starts with `Mozilla/5.0`.
8. In Sublime Text, open `Preferences > Package Settings > LeetCode > Settings`. The right-hand
   pane is your User settings; put both values there:

   ```json
   {
       "cookie_string": "csrftoken=...; LEETCODE_SESSION=...; cf_clearance=...",
       "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ..."
   }
   ```

9. Save. The next run uses the new values; no restart is needed.

### Check it worked

- The cookie should contain `csrftoken` and `LEETCODE_SESSION`. `cf_clearance` is present when
  LeetCode's bot protection has checked your browser; include it if it is there.
- If the cookie value contains a double quote, write it as `\"` so the settings file stays valid JSON.
- Run **LeetCode: Refresh Problems**, then **LeetCode: Show Problems Panel**. Problems you have
  solved show a green ✓ once the session is accepted.
- Open a problem and press **Run all** in the test panel.

### When it stops working

The session expires after a while, and `cf_clearance` expires sooner. Repeat steps 1 to 9 when
you see one of these:

| Message | Cause |
| :--- | :--- |
| HTTP 401 or 403 | The session has expired, or you signed out in the browser. |
| HTTP 499, or "LeetCode sent a page instead of data" | Bot protection refused the request: the cookie and `user_agent` do not match, or `cf_clearance` is missing or expired. |
| "Running and submitting need your LeetCode session" | `cookie_string` is empty. |

### Keep it private

The cookie is your login. Anyone who has it can act as you on LeetCode.

- Put it only in the User settings (`Packages/User/LeetCode.sublime-settings`), never in the
  package's own `LeetCode.sublime-settings`, which is tracked in git.
- Do not commit or share the User settings file.
- The package never writes the cookie to the console, even with `"debug": true`.

### Other settings

The remaining settings (language, where files are saved, cache lifetime, `ca_bundle`) are
documented in [LeetCode.sublime-settings](LeetCode.sublime-settings).

Requires the Python 3.14 plugin host (`.python-version`; Sublime Text build 4200 or later).

## LeetCode API

LeetCode has no public, documented API. These are the same endpoints its website calls, so they
can change without notice. All of them are on `https://leetcode.com` and all calls are made in
[core/client.py](core/client.py).

| # | Purpose | Method and path | Needs sign-in |
| :--- | :--- | :--- | :--- |
| 1 | Problem list | `GET /api/problems/all/` | No (solved marks need it) |
| 2 | One problem | `POST /graphql` | No (premium problems need it) |
| 3 | Run test cases | `POST /problems/<slug>/interpret_solution/` | Yes |
| 4 | Submit | `POST /problems/<slug>/submit/` | Yes |
| 5 | Poll a run or submission | `GET /submissions/detail/<id>/check/` | Yes |

**How far each is verified.** The shapes for 1 and 2 are copied from real responses. The shapes
for 3, 4 and 5 are what the code is written against and what other LeetCode clients read; they
have not yet been observed from a signed-in run of this package.

### Headers sent on every request

| Header | Value |
| :--- | :--- |
| `User-Agent` | The `user_agent` setting, or a built-in Chrome string. |
| `Accept`, `Content-Type` | `application/json` |
| `Origin` | `https://leetcode.com` |
| `Referer` | The problem page for 3, 4 and 5; the site root or problem set otherwise. |
| `X-Requested-With` | `XMLHttpRequest` |
| `Cookie` | The `cookie_string` setting, when set. |
| `X-CSRFToken` | The `csrftoken` value found inside `cookie_string`. |

### 1. Problem list: `GET /api/problems/all/`

No request body. The response is one object; the package reads only `stat_status_pairs`.

```json
{
  "user_name": "",
  "num_solved": 0,
  "num_total": 4123,
  "stat_status_pairs": [
    {
      "stat": {
        "question_id": 1,
        "frontend_question_id": 1,
        "question__title": "Two Sum",
        "question__title_slug": "two-sum",
        "total_acs": 24189353,
        "total_submitted": 41600353
      },
      "status": null,
      "difficulty": { "level": 1 },
      "paid_only": false
    }
  ]
}
```

| Field | Used for |
| :--- | :--- |
| `stat.frontend_question_id` | The number shown in the list and in the file name. |
| `stat.question__title` | The title. |
| `stat.question__title_slug` | The slug, which every other call is keyed by. |
| `difficulty.level` | `1` Easy, `2` Medium, `3` Hard. |
| `status` | `"ac"` means solved. It is `null` for everything when not signed in. |
| `paid_only` | Marks premium problems. |

The response is about 2 MB. It is cached for `cache_expiry` seconds.

### 2. One problem: `POST /graphql`

Request body:

```json
{
  "operationName": "questionData",
  "variables": { "titleSlug": "two-sum" },
  "query": "query questionData($titleSlug: String!) { question(titleSlug: $titleSlug) { questionId questionFrontendId title titleSlug difficulty content hints exampleTestcaseList metaData topicTags { name } codeSnippets { langSlug code } } }"
}
```

Response (`data.question`, shortened):

```json
{
  "data": {
    "question": {
      "questionId": "1",
      "questionFrontendId": "1",
      "title": "Two Sum",
      "titleSlug": "two-sum",
      "difficulty": "Easy",
      "content": "<p>Given an array of integers ...</p>",
      "hints": ["A really brute force way would be ..."],
      "exampleTestcaseList": ["[2,7,11,15]\n9", "[3,2,4]\n6", "[3,3]\n6"],
      "metaData": "{\"name\": \"twoSum\", \"params\": [{\"name\": \"nums\", \"type\": \"integer[]\"}, {\"name\": \"target\", \"type\": \"integer\"}], \"return\": {\"type\": \"integer[]\"}}",
      "topicTags": [{ "name": "Array" }, { "name": "Hash Table" }],
      "codeSnippets": [{ "langSlug": "java", "code": "class Solution {\n ..." }]
    }
  }
}
```

| Field | Used for |
| :--- | :--- |
| `questionId` | The internal id. Runs and submissions must send this one, not the number shown on the site; the two differ for many problems (`3617` vs `3330`, for example). |
| `questionFrontendId` | The number shown on the site. |
| `content` | Description HTML, turned into the header comment. `null` for a premium problem the account cannot open. |
| `exampleTestcaseList` | One string per example, one parameter value per line. These become the default test cases. |
| `metaData` | A JSON string. `params[].name` gives the parameter names and how many values a case has. Design problems have `classname` instead of `params`; their cases are two lines, the operations and their arguments. |
| `codeSnippets` | Starter code per language; `langSlug` matches the `default_language` setting. |

`data.question` is `null` when the slug does not exist. The response is cached per problem for
`cache_expiry` seconds.

### 3. Run test cases: `POST /problems/<slug>/interpret_solution/`

Request body:

```json
{
  "question_id": "1",
  "lang": "java",
  "typed_code": "class Solution { ... }",
  "data_input": "[2,7,11,15]\n9\n[3,2,4]\n6",
  "judge_type": "large"
}
```

`data_input` holds every case of the batch, one parameter value per line, cases simply joined.
Two cases of a two-parameter problem are four lines. All cases run in this one request.

Response: an id to poll with call 5.

```json
{ "interpret_id": "runcode_1700000000.123_abcdef", "test_case": "[2,7,11,15]\n9\n[3,2,4]\n6" }
```

Without `interpret_id` the run did not start; an `error` field, when present, says why.

### 4. Submit: `POST /problems/<slug>/submit/`

Request body:

```json
{ "question_id": "1", "lang": "java", "typed_code": "class Solution { ... }" }
```

Response: an id to poll with call 5.

```json
{ "submission_id": 1234567890 }
```

### 5. Poll: `GET /submissions/detail/<id>/check/`

`<id>` is the `interpret_id` or `submission_id`. It is polled once a second until `state` is
`SUCCESS`, for at most 30 seconds for a run and 90 for a submission.

While the judge is working:

```json
{ "state": "PENDING" }
```

`state` moves through `PENDING` and `STARTED` to `SUCCESS`. `FAILURE` means the judge itself
failed.

**Finished run** (from call 3):

```json
{
  "state": "SUCCESS",
  "run_success": true,
  "status_msg": "Accepted",
  "code_answer": ["[0,1]", "[0,2]", ""],
  "expected_code_answer": ["[0,1]", "[1,2]", ""],
  "compare_result": "10",
  "std_output_list": ["", "debug line\n", ""],
  "status_runtime": "0 ms"
}
```

| Field | Meaning |
| :--- | :--- |
| `run_success` | `false` when the code did not compile or crashed. |
| `code_answer` | Your output per case, in order. A trailing empty entry is padding. |
| `expected_code_answer` | The reference solution's output per case. This is where a custom case gets its expected value. |
| `compare_result` | One character per case: `1` passed, `0` failed. This is the verdict; `status_msg` says `Accepted` even when a case failed. |
| `std_output_list` | What the code printed, per case. |
| `status_msg` | `Compile Error`, `Runtime Error`, `Time Limit Exceeded` and so on when `run_success` is `false`. |
| `full_compile_error`, `compile_error` | The compiler's message. |
| `full_runtime_error`, `runtime_error` | The crash message. Cases before the crash still have answers. |

**Finished submission** (from call 4):

```json
{
  "state": "SUCCESS",
  "status_msg": "Wrong Answer",
  "total_correct": 61,
  "total_testcases": 63,
  "last_testcase": "[3,3]\n6",
  "expected_output": "[0,1]",
  "code_output": "[]",
  "std_output": "",
  "status_runtime": "N/A",
  "status_memory": "N/A"
}
```

| Field | Meaning |
| :--- | :--- |
| `status_msg` | The verdict: `Accepted`, `Wrong Answer`, `Time Limit Exceeded`, `Compile Error`, ... |
| `total_correct`, `total_testcases` | How many hidden tests passed. |
| `last_testcase`, `expected_output`, `code_output` | The first failing test, when not accepted. |
| `status_runtime`, `status_memory` | Shown when accepted. |
| `runtime_percentile`, `memory_percentile` | "Beats N%", when accepted. |

### Failures

A request is retried once only when it is a read (1, 2, 5) and the connection dropped
mid-response. Runs and submissions are never retried, so nothing is sent twice. Every failure is
turned into a message by [core/errors.py](core/errors.py):

| What happened | What it usually means |
| :--- | :--- |
| HTTP 401 or 403 | The session in `cookie_string` has expired. |
| HTTP 499, or an HTML page ("Just a moment...") instead of JSON | LeetCode's bot protection refused the request. It ties the cookie to a browser: re-copy the whole `Cookie` header (including `cf_clearance`) and set `user_agent` to that browser's `User-Agent`. |
| HTTP 429 | Rate limited. |
| HTTP 5xx | LeetCode is having trouble. |
| Certificate verify failed | A proxy re-signs HTTPS and its root certificate is not trusted. Roots are read from the macOS keychains; `ca_bundle` adds a `.pem` file. |
| Timeout, DNS failure, dropped connection | Network trouble. |

With `"debug": true` each request is logged to the console, and a failed one logs the first 300
characters of LeetCode's reply. The cookie is never logged.

## Layout

| Path | Holds |
| :--- | :--- |
| `plugin.py` | Entry point; imports every command and listener. |
| `core/testcases.py` | Parsing test inputs, building the judge's `data_input`, reading results. |
| `core/problem.py` | The question model, the solution file header, markers and template. |
| `core/html_text.py` | Description HTML to plain text. |
| `core/problem_list.py` | Filtering, paging and the HTML of the problem list panel. |
| `core/test_panel_html.py` | The HTML of the test panel: actions, run banner and one card per test. |
| `core/client.py` | The LeetCode HTTP calls (blocking). |
| `core/errors.py` | Turns a failed request into a message that says what went wrong and what to do. |
| `core/config.py` | Settings and the on-disk cache. |
| `ui/` | Sublime commands, the test panel and the problem list. |
| `tests/` | Tests for `core`, runnable without Sublime. |

`core` (except `config` and `client`) imports nothing from Sublime. Run its tests from
`sublime/packages`:

```sh
python3 -m unittest LeetCode.tests.test_core
```
