"""[vcrfx] desktop/renderer/index.html: the shell loads pine-vcr.js, first of
the picture code (every consumer looks it up when it runs, so order is only
tidiness). One-line anchor: a staged wave may edit this file too.
TARGET: desktop/renderer/index.html
"""
from _vcrlib import Edit, main

EDITS = [
    Edit("script", '<script src="./pine-vcr.js"></script>',
         """  <script src="./pine-icons.js"></script>
""",
         """  <script src="./pine-vcr.js"></script>
  <script src="./pine-icons.js"></script>
"""),
]

if __name__ == "__main__":
    raise SystemExit(main(EDITS))
