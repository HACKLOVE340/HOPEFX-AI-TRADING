"""
HOPEFX AI Trading Framework - Setup Configuration
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text(encoding='utf-8') if readme_file.exists() else ""

# Read requirements
requirements_file = Path(__file__).parent / "requirements.txt"
if requirements_file.exists():
    with open(requirements_file, 'r', encoding='utf-8') as f:
        requirements = [
            line.strip() for line in f 
            if line.strip() and not line.startswith('#')
        ]
else:
    requirements = []

setup(
    name="hopefx-ai-trading",
    version="1.0.0",
    author="HOPEFX Team",
    author_email="team@hopefx.ai",
    description="Advanced AI-powered XAUUSD trading framework with machine learning",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/HACKLOVE340/HOPEFX-AI-TRADING",
    packages=find_packages(exclude=['tests', 'docs', 'examples']),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Financial and Insurance Industry",
        "Intended Audience :: Developers",
        "Topic :: Office/Business :: Financial :: Investment",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    extras_require={
        'dev': [
            'pytest>=7.4.3',
            'pytest-cov>=4.1.0',
            'black>=23.12.0',
            'flake8>=6.1.0',
            'pylint>=3.0.3',
        ],
        'docs': [
            'sphinx>=7.2.6',
            'sphinx-rtd-theme>=2.0.0',
        ],
    },
    entry_points={
        'console_scripts': [
            'hopefx=cli:main',
            'hopefx-server=app:run_server',
        ],
    },
    include_package_data=True,
    zip_safe=False,
    keywords='trading ai machine-learning xauusd forex cryptocurrency bitcoin',
    project_urls={
        'Bug Reports': 'https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/issues',
        'Source': 'https://github.com/HACKLOVE340/HOPEFX-AI-TRADING',
        'Documentation': 'https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/blob/main/README.md',
    },
)
