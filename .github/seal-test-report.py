#!/usr/bin/env python3
# Prints the surefire totals of this build and every skipped test with its reason,
# grouped one line per reason, so the test summary is the last output of the job.
# Tests skipped without a reported message get the @Disabled/@Ignore/@Enabled*/
# assumption text found in their test source.
import glob
import os
import re
import xml.etree.ElementTree as ET
from collections import OrderedDict

totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
per_module = OrderedDict()
reasons = OrderedDict()
source_cache = {}


def find_source(classname):
    if classname in source_cache:
        return source_cache[classname]
    rel = classname.split("$")[0].replace(".", "/") + ".java"
    hits = glob.glob("**/src/test/java/" + rel, recursive=True)
    text = ""
    if hits:
        with open(hits[0], encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    source_cache[classname] = text
    return text


ANNOT = re.compile(r"@(Disabled\w*|Ignore|Enabled\w*|DisabledIf\w*|EnabledIf\w*|Tag)\b(\([^)]*\))?")


def comment_before(text, pos, skip_code=0):
    """Comment and annotation lines directly above `pos`, flattened to one line."""
    lines = text[:pos].splitlines()[:-1] if not text[:pos].endswith("\n") else text[:pos].splitlines()
    out = []
    for line in reversed(lines):
        t = line.strip()
        if t.startswith(("//", "/*", "*", "*/", "@")) or t.endswith((")", ",")):
            out.append(t)
            continue
        if not out and (not t or skip_code > 0):
            skip_code -= 1 if t else 0
            continue
        break
    body = " ".join(reversed(out))
    body = re.sub(r"/\*+|\*+/|^\*|\s\*\s|//", " ", body)
    return re.sub(r"\s+", " ", body).strip()


def source_reason(classname, method, message):
    """Explanation of a skip taken from the test source: the comment/annotations above
    the assumption, the test method, or the test class."""
    text = find_source(classname)
    if not text:
        return ""
    mm = re.search(r"\bvoid\s+" + re.escape(method) + r"\s*\(", text) if method else None
    if mm and "Assumption" in message:
        a = re.compile(r"\bassume\w*\s*\(").search(text, mm.end())
        if a:
            line_start = text.rfind("\n", 0, a.start()) + 1
            line_end = text.find("\n", a.start())
            ctx = comment_before(text, line_start, skip_code=2)
            return (ctx + " -> " + text[line_start:line_end].strip())[:400]
    if mm:
        line_start = text.rfind("\n", 0, mm.start()) + 1
        ctx = comment_before(text, line_start)
        if ANNOT.search(ctx):
            return ctx[:400]
    cls = re.search(r"\bclass\s+" + re.escape(classname.split(".")[-1].split("$")[0]) + r"\b", text)
    if cls:
        line_start = text.rfind("\n", 0, cls.start()) + 1
        return comment_before(text, line_start)[:400]
    return ""


for path in sorted(glob.glob("**/target/surefire-reports/TEST-*.xml", recursive=True)):
    module = path.replace("\\", "/").split("/target/")[0]
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        continue
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    mod = per_module.setdefault(module, {"tests": 0, "failures": 0, "errors": 0, "skipped": 0})
    for suite in suites:
        for key in totals:
            v = int(float(suite.get(key, "0") or 0))
            totals[key] += v
            mod[key] += v
        for case in suite.findall("testcase"):
            sk = case.find("skipped")
            if sk is None:
                continue
            cls = case.get("classname", "")
            name = case.get("name", "")
            msg = (sk.get("message") or (sk.text or "")).strip()
            msg = re.split(r"\s+at\s+[\w$.]+\(", msg)[0].replace("\n", " ").strip()
            meth = re.sub(r"[\[(].*$", "", name)
            ctx = source_reason(cls, meth, msg)
            if not msg:
                msg = "no message reported by the runner"
            if ctx:
                msg = msg[:200] + " || test source: " + ctx
            reasons.setdefault(msg[:600], []).append(cls.split(".")[-1] + "#" + name)

print("=" * 72)
print("SUREFIRE RESULTS PER MODULE (tests / failures / errors / skipped)")
for module, c in per_module.items():
    print("  %-50s %6d / %d / %d / %d" % (module, c["tests"], c["failures"], c["errors"], c["skipped"]))
print("=" * 72)
print("SKIPPED TESTS BY REASON (%d skipped in total)" % totals["skipped"])
for msg, tests in reasons.items():
    shown = ", ".join(tests[:6]) + (" ... (+%d more)" % (len(tests) - 6) if len(tests) > 6 else "")
    print("  SKIPPED x%d | reason: %s | %s" % (len(tests), msg, shown))
print("=" * 72)
passed = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
print(
    "TEST SUMMARY: %d tests run, %d passed, %d failures, %d errors, %d skipped"
    % (totals["tests"], passed, totals["failures"], totals["errors"], totals["skipped"])
)
