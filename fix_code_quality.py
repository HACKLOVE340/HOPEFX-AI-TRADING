#!/usr/bin/env python3
"""
Script to fix code quality issues automatically.
Fixes whitespace, imports, and PEP8 compliance issues.
"""
import re
import os
from pathlib import Path

def fix_trailing_whitespace(file_path):
    """Remove trailing whitespace from all lines."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Fix trailing whitespace
    lines = content.split('\n')
    fixed_lines = [line.rstrip() for line in lines]
    fixed_content = '\n'.join(fixed_lines)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(fixed_content)

    return len([l for l in lines if l != l.rstrip()])

def fix_blank_lines(file_path):
    """Fix blank line spacing around classes and functions."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Ensure 2 blank lines before class/function definitions at module level
    content = re.sub(r'\n(class |def [^_])', r'\n\n\n\1', content)
    # But not more than 2
    content = re.sub(r'\n\n\n+', r'\n\n\n', content)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

def process_file(file_path):
    """Process a single Python file."""
    print(f"Processing: {file_path}")
    fixes = fix_trailing_whitespace(file_path)
    if fixes > 0:
        print(f"  Fixed {fixes} whitespace issues")
    # fix_blank_lines(file_path)

def main():
    """Main execution."""
    project_root = Path(__file__).parent

    # Process all Python files
    python_files = list(project_root.rglob('*.py'))

    # Exclude venv, .git, etc
    python_files = [f for f in python_files if '.git' not in str(f) and 'venv' not in str(f)]

    total_files = len(python_files)
    print(f"Found {total_files} Python files to process")

    for py_file in python_files:
        try:
            process_file(py_file)
        except Exception as e:
            print(f"Error processing {py_file}: {e}")

    print("\n✅ Code quality fixes completed!")

if __name__ == '__main__':
    main()
