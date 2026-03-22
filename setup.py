setup_py = '''from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="hopefx-ai-trading",
    version="2.0.0",
    author="HOPEFX Team",
    description="Advanced AI-powered trading framework with real-time analysis",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/HACKLOVE340/HOPEFX-AI-TRADING",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Financial and Insurance Industry",
        "Topic :: Office/Business :: Financial :: Investment",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "hopefx=cli:main",
            "hopefx-server=app:run_server",
        ],
    },
)
'''

with open(project_root / "setup.py", "w") as f:
    f.write(setup_py)
