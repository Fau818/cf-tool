"""
Constants for cf-tool including URLs, patterns, and language configurations.
"""

# Codeforces URLs
BASE_URL = "https://codeforces.com"
LOGIN_URL = f"{BASE_URL}/enter"

URL_PATTERNS = {
    "contest": f"{BASE_URL}/contest/{{cid}}/problem/{{pid}}",
    "gym": f"{BASE_URL}/gym/{{cid}}/problem/{{pid}}",
    "problemset": f"{BASE_URL}/problemset/problem/{{cid}}/{{pid}}",
    "group": f"{BASE_URL}/group/{{gid}}/contest/{{cid}}/problem/{{pid}}",
}

SUBMIT_URLS = {
    "contest": f"{BASE_URL}/contest/{{cid}}/submit",
    "gym": f"{BASE_URL}/gym/{{cid}}/submit",
    "problemset": f"{BASE_URL}/problemset/submit",
    "group": f"{BASE_URL}/group/{{gid}}/contest/{{cid}}/submit",
}

SUBMISSION_URL = f"{BASE_URL}/contest/{{cid}}/my"

# Language IDs for Codeforces submission
# These IDs correspond to the programming language selection on Codeforces
LANGUAGE_IDS = {
    "cpp": "89",  # GNU G++23 13.2
    "cpp17": "54",  # GNU G++17 7.3.0
    "cpp20": "73",  # GNU G++20 11.2.0
    "python": "31",  # Python 3.8.10
    "python3": "31",  # Python 3.8.10
    "py": "31",  # Python 3.8.10
    "java": "87",  # Java 21 64bit
    "c": "43",  # GNU GCC C11 5.1.0
}

# File extension to language mapping
EXTENSION_TO_LANGUAGE = {
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c++": "cpp",
    ".py": "python",
    ".java": "java",
    ".c": "c",
}

# Language to file extension mapping
LANGUAGE_TO_EXTENSION = {
    "cpp": ".cpp",
    "python": ".py",
    "py": ".py",
    "java": ".java",
    "c": ".c",
}

# Default compiler commands
DEFAULT_COMPILERS = {
    "cpp": "g++ -std=c++17 -O2 -Wall {source} -o {output}",
    "c": "gcc -std=c11 -O2 -Wall {source} -o {output}",
    "java": "javac {source}",
}

# Default execution commands
DEFAULT_RUNNERS = {
    "cpp": "{executable}",
    "python": "python3 {source}",
    "py": "python3 {source}",
    "java": "java {classname}",
    "c": "{executable}",
}

# Default configuration
DEFAULT_CONFIG = {
    "username": "",
    "default_language": "cpp",
    "templates": {
        "cpp": "~/.cf/template.cpp",
        "python": "~/.cf/template.py",
    },
    "compiler": {
        "cpp": "g++ -std=c++17 -O2 -Wall",
    },
    "timeout": 2.0,  # seconds
}

# Test case file patterns
TEST_INPUT_PATTERN = "in{}.txt"
TEST_OUTPUT_PATTERN = "out{}.txt"

# Solution file names
SOLUTION_FILE_NAMES = {
    "cpp": "solution.cpp",
    "python": "solution.py",
    "py": "solution.py",
    "java": "Solution.java",
    "c": "solution.c",
}

# Problem metadata file
PROBLEM_METADATA_FILE = "problem.json"

# User agent for HTTP requests
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Request timeout
REQUEST_TIMEOUT = 30.0  # seconds

# Maximum test case size (to prevent memory issues)
MAX_TEST_CASE_SIZE = 10 * 1024 * 1024  # 10 MB
