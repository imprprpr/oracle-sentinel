#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Static AST Analysis Test: Zero Dead References to sentinel_core
Scans all python files in the project to verify that every attribute access
and imported symbol from sentinel_core exists in sentinel_core.py.
Strictly zero emojis.
"""

import os
import ast
import unittest
import sentinel_core


class TestNoDeadReferences(unittest.TestCase):
    def setUp(self):
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_all_sentinel_core_references_valid(self):
        dead_references = []
        ignored_dirs = {'.venv', 'venv', 'env', '.git', '__pycache__', 'build', 'dist'}

        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            for file in files:
                if not file.endswith('.py'):
                    continue
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, self.project_root)

                with open(file_path, 'r', encoding='utf-8') as f:
                    try:
                        tree = ast.parse(f.read(), filename=rel_path)
                    except SyntaxError as e:
                        self.fail(f"Syntax error in {rel_path}: {e}")

                sentinel_aliases = set()

                for node in ast.walk(tree):
                    # Check 'import sentinel_core [as alias]'
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name == 'sentinel_core':
                                sentinel_aliases.add(alias.asname or 'sentinel_core')

                    # Check 'from sentinel_core import foo, bar'
                    elif isinstance(node, ast.ImportFrom):
                        if node.module == 'sentinel_core':
                            for alias in node.names:
                                attr_name = alias.name
                                if attr_name == '*':
                                    continue
                                if not hasattr(sentinel_core, attr_name):
                                    dead_references.append(
                                        f"{rel_path}:{node.lineno} - 'from sentinel_core import {attr_name}' "
                                        f"(attribute does not exist)"
                                    )

                # Check 'sentinel_core.foo' or '<alias>.foo'
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute):
                        if isinstance(node.value, ast.Name) and node.value.id in sentinel_aliases:
                            attr_name = node.attr
                            if not hasattr(sentinel_core, attr_name):
                                dead_references.append(
                                    f"{rel_path}:{node.lineno} - '{node.value.id}.{attr_name}' "
                                    f"(attribute does not exist in sentinel_core)"
                                )

        if dead_references:
            formatted_errors = "\n".join(dead_references)
            self.fail(f"Found {len(dead_references)} dead reference(s) to sentinel_core:\n{formatted_errors}")


if __name__ == '__main__':
    unittest.main()
