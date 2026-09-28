"""[pinelive-req] pinelive.py's routes lost their Request annotation at runtime.

The module carries `from __future__ import annotations`, so every annotation is
a STRING, and FastAPI resolves those strings against the MODULE's globals - but
`Request` (and Header/HTTPException and the response classes) were imported
inside install(). The ForwardRef never resolves, FastAPI falls back to treating
`request` as a required QUERY parameter, and the popup's Test button got:
  {"type":"missing","loc":["query","request"],"msg":"Field required"}
The cure: import the fastapi names at module level (guarded, so importing
pinelive.py without fastapi still works for the pure tests); install()'s local
imports stay and simply shadow the same objects.

Usage: python edit_pinelive_request_fix.py <pinelive.py>   (idempotent)
"""
import sys

MARK = "[pinelive-req]"
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
if MARK in s:
    print("already applied: %s" % p)
    sys.exit(0)
old = "from __future__ import annotations\n"
assert s.count(old) == 1, s.count(old)
new = old + (
    "\n"
    "# " + MARK + " With string annotations (the future import above), FastAPI\n"
    "# resolves 'Request'/'Header' against THIS module's globals - so the names\n"
    "# must live here, not only inside install(). Guarded: the pure tests\n"
    "# import this module without fastapi installed.\n"
    "try:\n"
    "    from fastapi import Header, HTTPException, Request\n"
    "    from fastapi.responses import HTMLResponse, StreamingResponse\n"
    "except ImportError:                                       # pragma: no cover\n"
    "    Header = HTTPException = Request = None  # type: ignore[assignment]\n"
    "    HTMLResponse = StreamingResponse = None  # type: ignore[assignment]\n"
)
s = s.replace(old, new, 1)
open(p, "w", encoding="utf-8", newline="\n").write(s)
print("applied: module-level fastapi names for string annotations")
