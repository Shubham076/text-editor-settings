"""Tests for the editor-independent logic. Run from sublime/packages:

    python3 -m unittest LeetCode.tests.test_core
"""

import http.client
import socket
import ssl
import unittest
import urllib.error

from LeetCode.core import problem_list, test_panel_html, testcases
from LeetCode.core.errors import explain
from LeetCode.core.html_text import html_to_text
from LeetCode.core.problem import (
    Question, SolutionInfo, extract_code, file_name, parse_header, render_template)

TWO_SUM = {
    "questionId": "1", "questionFrontendId": "1", "title": "Two Sum", "titleSlug": "two-sum",
    "difficulty": "Easy",
    "content": (
        '<p>Given <code>nums</code> where <code>2 &lt;= nums.length &lt;= 10<sup>4</sup></code>.</p>'
        '<p><strong class="example">Example 1:</strong></p>'
        '<pre>\n<strong>Input:</strong> nums = [2,7,11,15], target = 9\n'
        '<strong>Output:</strong> [0,1]\n<strong>Explanation:</strong> Because.\n</pre>'
        '<p><strong class="example">Example 2:</strong></p>'
        '<div class="example-block"><p><strong>Input:</strong> '
        '<span class="example-io">nums = [3,2,4], target = 6</span></p>'
        '<p><strong>Output:</strong> <span class="example-io">[1,2]</span></p></div>'),
    "exampleTestcaseList": ["[2,7,11,15]\n9", "[3,2,4]\n6"],
    "metaData": '{"name": "twoSum", "params": [{"name": "nums"}, {"name": "target"}]}',
    "topicTags": [{"name": "Array"}], "hints": ["Use a <b>map</b>."],
    "codeSnippets": [{"langSlug": "java", "code": "class Solution {\n}"}],
}


class InputParsing(unittest.TestCase):
    names = ["nums", "target"]

    def test_named_and_bare_values(self):
        self.assertEqual(testcases.parse_input("nums = [3,2,4], target = 6", self.names), ["[3,2,4]", "6"])
        self.assertEqual(testcases.parse_input("[3,2,4], 6", self.names), ["[3,2,4]", "6"])
        self.assertEqual(testcases.parse_input("[3,2,4]\n6", self.names), ["[3,2,4]", "6"])

    def test_commas_and_equals_inside_strings_and_nesting(self):
        self.assertEqual(
            testcases.parse_input('s = "a,b=c", grid = [[1,2],[3,4]]', ["s", "grid"]),
            ['"a,b=c"', "[[1,2],[3,4]]"])

    def test_single_parameter_takes_everything(self):
        self.assertEqual(testcases.parse_input("s = a, b", ["s"]), ["a, b"])

    def test_wrong_count_is_reported(self):
        with self.assertRaisesRegex(ValueError, r"Expected 2 values \(nums, target\), got 1"):
            testcases.parse_input("[3,2,4]", self.names)
        with self.assertRaises(ValueError):
            testcases.parse_input("  ", self.names)

    def test_round_trip(self):
        values = ["[3,2,4]", "6"]
        self.assertEqual(testcases.parse_input(testcases.format_input(values, self.names), self.names), values)


class Examples(unittest.TestCase):
    def test_cases_from_question(self):
        question = Question.from_graphql(TWO_SUM)
        self.assertEqual(question.param_names, ["nums", "target"])
        cases = testcases.example_cases(
            question.example_inputs, testcases.example_outputs(question.content), 2)
        self.assertEqual([case.values for case in cases], [["[2,7,11,15]", "9"], ["[3,2,4]", "6"]])
        self.assertEqual([case.expected for case in cases], ["[0,1]", "[1,2]"])
        self.assertEqual(testcases.data_input(cases), "[2,7,11,15]\n9\n[3,2,4]\n6")

    def test_design_problem_has_two_lines_per_case(self):
        question = Question.from_graphql({
            "metaData": '{"classname": "LRUCache", "methods": []}',
            "exampleTestcaseList": ['["LRUCache","get"]\n[[2],[1]]']})
        self.assertEqual(question.param_names, ["operations", "arguments"])

    def test_output_on_its_own_line(self):
        html = "<pre>\n<strong>Input</strong>\n[1]\n<strong>Output</strong>\n[null, 1]\n</pre>"
        self.assertEqual(testcases.example_outputs(html), ["[null, 1]"])


class RunResults(unittest.TestCase):
    def test_pass_and_fail(self):
        result = testcases.parse_run_result({
            "run_success": True, "code_answer": ["[0,1]", "[0,2]", ""],
            "expected_code_answer": ["[0,1]", "[1,2]", ""], "compare_result": "10",
            "std_output_list": ["", "dbg\n", ""], "status_runtime": "0 ms"}, 2)
        self.assertEqual([case["status"] for case in result.cases], ["pass", "fail"])
        self.assertEqual(result.cases[1], {"status": "fail", "actual": "[0,2]", "expected": "[1,2]", "stdout": "dbg"})
        self.assertEqual(result.error, "")

    def test_compile_error_marks_every_case(self):
        result = testcases.parse_run_result({
            "run_success": False, "status_msg": "Compile Error", "full_compile_error": "Line 3: ';' expected"}, 2)
        self.assertEqual([case["status"] for case in result.cases], ["error", "error"])
        self.assertEqual(result.error, "Compile Error\nLine 3: ';' expected")

    def test_runtime_error_keeps_finished_cases(self):
        result = testcases.parse_run_result({
            "run_success": False, "status_msg": "Runtime Error", "runtime_error": "boom",
            "code_answer": ["[0,1]"], "expected_code_answer": ["[0,1]", "[1,2]"], "compare_result": "1"}, 2)
        self.assertEqual([case["status"] for case in result.cases], ["pass", "error"])

    def test_apply_and_summary(self):
        cases = [testcases.TestCase(["1"]), testcases.TestCase(["2"], custom=True)]
        testcases.apply_run_result(cases, testcases.parse_run_result({
            "run_success": True, "code_answer": ["1", "3"], "expected_code_answer": ["1", "2"],
            "compare_result": "10"}, 2))
        self.assertEqual(cases[1].expected, "2")
        self.assertEqual(testcases.summary(cases), "1 of 2 passed")

    def test_submission_report(self):
        accepted = testcases.format_submission({
            "status_msg": "Accepted", "total_correct": 63, "total_testcases": 63,
            "status_runtime": "2 ms", "status_memory": "44 MB", "runtime_percentile": 98.123})
        self.assertIn("Test cases: 63/63 passed", accepted)
        self.assertIn("Runtime: 2 ms  (beats 98.1%)", accepted)
        wrong = testcases.format_submission({
            "status_msg": "Wrong Answer", "last_testcase": "[3,3]\n6", "expected_output": "[0,1]", "code_output": "[]"})
        self.assertIn("Last input: [3,3], 6", wrong)
        self.assertIn("Expected: [0,1]", wrong)


class FailureMessages(unittest.TestCase):
    def message(self, error):
        return str(explain(error, "load the problem list"))

    def test_names_the_action(self):
        self.assertTrue(self.message(socket.timeout()).startswith("Could not load the problem list.\n\n"))

    def test_untrusted_certificate(self):
        error = ssl.SSLCertVerificationError(1, "certificate verify failed")
        error.verify_message = "unable to get local issuer certificate"
        text = self.message(urllib.error.URLError(error))
        self.assertIn("ca_bundle", text)
        self.assertIn("unable to get local issuer certificate", text)

    def test_expired_session_and_rate_limit(self):
        def http(code):
            return urllib.error.HTTPError("https://leetcode.com/x", code, "x", {}, None)
        self.assertIn("cookie_string", self.message(http(403)))
        self.assertIn("rate limiting", self.message(http(429)))
        self.assertIn("HTTP 503", self.message(http(503)))
        self.assertIn("user_agent", self.message(http(499)))
        self.assertTrue(self.message(urllib.error.HTTPError("u", 418, "", {}, None)).endswith("HTTP 418."))

    def test_offline_timeout_and_html(self):
        self.assertIn("offline", self.message(urllib.error.URLError(socket.gaierror(8, "nodename"))))
        self.assertIn("did not answer in time", self.message(urllib.error.URLError(socket.timeout())))
        self.assertIn("bot protection", self.message(ValueError("Expecting value")))
        self.assertIn("dropped before the answer", self.message(http.client.IncompleteRead(b"x", 10)))


class ProblemList(unittest.TestCase):
    def setUp(self):
        self.problems = problem_list.problems_from_api([
            {"stat": {"frontend_question_id": n, "question__title": "P{} <b>".format(n), "question__title_slug": "p-{}".format(n)},
             "difficulty": {"level": 1 + n % 3}, "status": "ac" if n % 2 else None, "paid_only": n == 2}
            for n in range(120, 0, -1)])

    def test_sorted_and_filtered(self):
        self.assertEqual([p.number for p in self.problems[:3]], [1, 2, 3])
        hard_solved = problem_list.matching(self.problems, problem_list.ListState("Hard", "Solved"))
        self.assertTrue(hard_solved and all(p.difficulty == "Hard" and p.solved for p in hard_solved))
        todo = problem_list.matching(self.problems, problem_list.ListState(status="Todo"))
        self.assertEqual(len(todo), 60)

    def test_rows_are_links_and_pages(self):
        html = problem_list.render(self.problems, problem_list.ListState())
        self.assertEqual(html.count('class="row'), 50)
        self.assertIn('href="open:p-1"', html)
        self.assertIn("P1 &lt;b&gt;", html)
        self.assertIn("Page 1 of 3", html)
        self.assertIn('href="page:1"', html)
        self.assertNotIn('href="page:-1"', html)
        self.assertIn('class="chip on" href="difficulty:All"', html)
        last = problem_list.render(self.problems, problem_list.ListState(page=99))
        self.assertIn("Page 3 of 3", last)
        self.assertEqual(last.count('class="row'), 20)

    def test_no_matches(self):
        html = problem_list.render([], problem_list.ListState("Hard"))
        self.assertIn("No problems match", html)
        self.assertIn("Page 1 of 1", html)


class TestPanelHtml(unittest.TestCase):
    def setUp(self):
        self.question = Question.from_graphql(TWO_SUM)
        self.cases = [testcases.TestCase(["[2,7,11,15]", "9"], "[0,1]"),
                      testcases.TestCase(["[1,<2>]", "3"], custom=True)]

    def html(self, message="", running=False):
        return test_panel_html.render(self.question, self.cases, message, running)

    def test_cards_and_actions(self):
        html = self.html()
        self.assertEqual(html.count('class="card '), 2)
        self.assertNotIn("border:", html)
        self.assertIn("▶\u00a0Run\u00a0all</a>", html)  # a label never wraps mid-button
        self.assertEqual(test_panel_html.title(self.question, "java"), "1. Two Sum  (java)")
        self.assertIn(">nums = [2,7,11,15]</div>", html)
        self.assertIn(">target = 9</div>", html)
        self.assertIn("nums = [1,&lt;2&gt;]", html)
        self.assertIn('href="run:0"', html)
        self.assertNotIn('href="edit:0"', html)  # examples cannot be edited or deleted
        self.assertIn('href="delete:1"', html)
        self.assertNotIn('class="banner', html)

    def test_banner_is_above_the_cards(self):
        self.cases[0].status = "running"
        running = self.html(running=True)
        self.assertIn("Running 1 test on LeetCode", running)
        self.assertLess(running.index('class="banner'), running.index('class="card'))
        self.cases[0].status, self.cases[0].actual = "fail", "[0,2]"
        failed = self.html()
        self.assertIn('class="banner bad"><div class="headline">0 of 1 passed', failed)
        self.assertIn('class="wrong">[0,2]', failed)
        self.cases[0].status = "pass"
        self.assertIn('class="banner ok"><div class="headline">All 1 passed', self.html())

    def test_error_banner_keeps_lines_and_indentation(self):
        html = self.html("Compile Error\nLine 3: error\n    int x = <y>;")
        self.assertIn('class="banner bad"><div class="headline">Compile Error</div><div class="detail">', html)
        self.assertIn("<div>Line 3: error</div>", html)
        self.assertIn("<div>\u00a0\u00a0\u00a0\u00a0int x = &lt;y&gt;;</div>", html)
        self.assertLess(html.index("Compile Error"), html.index('class="card'))


class SolutionFiles(unittest.TestCase):
    def test_html_keeps_comparisons(self):
        self.assertEqual(html_to_text("<p>1 &lt;= n &lt;= 10<sup>4</sup> &amp; <code>a&nbsp;b</code></p>"),
                         "1 <= n <= 10^4 & a b")

    def test_template_round_trips(self):
        question = Question.from_graphql(TWO_SUM)
        text = render_template(question, "java")
        self.assertTrue(text.startswith("/*\n * @leetcode id=1 slug=two-sum lang=java\n *\n * 1. Two Sum (Easy)\n"))
        self.assertIn("\n * Hint 1: Use a map.\n */\n\n// Do not remove code start\n", text)
        self.assertEqual(parse_header(text), SolutionInfo("two-sum", "java"))
        self.assertEqual(extract_code(text), "class Solution {\n}")
        self.assertEqual(file_name(question, "java"), "leetcode_1_two_sum.java")

    def test_block_comment_per_language_wraps_and_cannot_end_early(self):
        quotes = '"' * 3
        data = dict(TWO_SUM, content="<p>" + "word " * 60 + "</p><p>ends */ and " + quotes + " here</p>",
                    codeSnippets=[{"langSlug": "python3", "code": "class Solution:\n    pass"}])
        question = Question.from_graphql(data)
        python = render_template(question, "python3")
        self.assertTrue(python.startswith(quotes + "\n@leetcode id=1 slug=two-sum lang=python3\n"))
        self.assertEqual(python.count(quotes), 2)
        self.assertIn("\n# Do not remove code start\nclass Solution:", python)
        compile(python, "solution.py", "exec")  # the header is a valid docstring
        java = render_template(question, "java")
        self.assertEqual(java.count("*/"), 1)
        self.assertLessEqual(max(len(line) for line in java.splitlines()), 104)
        self.assertEqual(parse_header(python), SolutionInfo("two-sum", "python3"))

    def test_files_written_by_the_old_plugin(self):
        text = ("# LeetCode Problem: Two Sum\n# Difficulty: Easy\n\n"
                "# Do not remove code start\nclass Solution:\n    pass\n\n\n# Do not remove code end")
        self.assertEqual(parse_header(text), SolutionInfo("two-sum", ""))
        self.assertEqual(parse_header(text, lambda title: "from-list"), SolutionInfo("from-list", ""))
        self.assertEqual(extract_code(text), "class Solution:\n    pass")

    def test_other_files_are_not_solutions(self):
        self.assertIsNone(parse_header("import os\n"))
        self.assertEqual(extract_code("print(1)\n"), "print(1)")


if __name__ == "__main__":
    unittest.main()
