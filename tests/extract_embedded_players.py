import ast
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
tree = ast.parse((root / 'app.py').read_text(encoding='utf-8'))
players = []
for node in ast.walk(tree):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if 'function djVoiceNext()' in node.value or 'function voiceNext()' in node.value:
            players.append({'line': node.lineno, 'html': node.value})
assert len(players) == 2, f'Expected panel and listener HTML, found {len(players)}'
print(json.dumps(players))
