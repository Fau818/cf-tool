# cf-tool

A Codeforces CLI tool for competitive programming, written in Python. This is a rewrite of the archived [cf-tool](https://github.com/xalanq/cf-tool) originally written in Go.

## Features

- 🚀 **Parse Problems**: Download problem test cases and create directory structure
- ✅ **Local Testing**: Run your solutions against sample test cases before submitting
- 📤 **Submit Solutions**: Submit your code directly to Codeforces
- 📝 **Templates**: Generate code from customizable templates
- 🎨 **Beautiful Output**: Rich terminal output with colors and tables

## Installation

### From Source

```bash
cd cf_tool
pip install -e .
```

### Requirements

- Python 3.8 or higher
- For C++: g++ compiler
- For Python solutions: Python 3

## Quick Start

### 1. Configure (Optional)

Set your default language and other preferences:

```bash
cf config set default_language cpp
```

### 2. Login to Codeforces

```bash
cf config login
```

You'll be prompted for your Codeforces username and password.

### 3. Parse a Problem

Download problem test cases and create a solution file:

```bash
cf parse 1900 A
```

This creates the following structure:
```
1900/
└── A/
    ├── in1.txt
    ├── out1.txt
    ├── in2.txt
    ├── out2.txt
    ├── solution.cpp
    └── problem.json
```

### 4. Write Your Solution

Edit the generated `solution.cpp` (or `solution.py`) file.

### 5. Test Locally

```bash
cd 1900/A
cf test
```

The tool will compile your code and run it against all sample test cases, showing results in a table.

### 6. Submit

Once all tests pass:

```bash
cf submit 1900 A solution.cpp
```

## Commands

### Configuration

```bash
# Set configuration values
cf config set <key> <value>

# Get configuration values
cf config get <key>

# Show all configuration
cf config show

# Login to Codeforces
cf config login
```

### Problem Management

```bash
# Parse a problem (downloads test cases)
cf parse <contest_id> <problem_id> [--lang cpp|python]

# Parse from different contest types
cf parse 100001 A --contest-type gym

# Generate code from template
cf gen <contest_id> <problem_id> [--lang cpp|python]

# Open problem in browser
cf open <contest_id> <problem_id>
```

### Testing

```bash
# Test solution (auto-detects solution file)
cf test

# Test specific file
cf test --file solution.cpp
```

### Submission

```bash
# Submit solution
cf submit <contest_id> <problem_id> <file> [--lang cpp|python]

# Watch submission status (coming soon)
cf watch <submission_id>
```

## Configuration

Configuration is stored in `~/.cf/config` as JSON.

### Default Configuration

```json
{
  "username": "",
  "default_language": "cpp",
  "templates": {
    "cpp": "~/.cf/template.cpp",
    "python": "~/.cf/template.py"
  },
  "compiler": {
    "cpp": "g++ -std=c++17 -O2 -Wall"
  },
  "timeout": 2.0
}
```

### Custom Templates

You can create custom templates and configure them:

1. Create your template file (e.g., `~/my_template.cpp`)
2. Set the template path:
   ```bash
   cf config set templates.cpp ~/my_template.cpp
   ```

Templates support variable substitution:
- `$PROBLEM$` - Problem ID (e.g., A, B, C)
- `$CONTEST$` - Contest ID (e.g., 1900)

## Contest Types

The tool supports different Codeforces contest types:

- `contest` - Regular contests (default)
- `gym` - Gym problems
- `problemset` - Problemset
- `group` - Group contests

Example:
```bash
cf parse 100001 A --contest-type gym
```

## Supported Languages

- C++ (`.cpp`, `.cc`, `.cxx`)
- Python (`.py`)
- C (`.c`)
- Java (`.java`)

## Examples

### Typical Workflow

```bash
# 1. Parse problem
cf parse 1900 A

# 2. Navigate to problem directory
cd 1900/A

# 3. Edit solution.cpp
vim solution.cpp

# 4. Test
cf test

# 5. Submit when all tests pass
cf submit 1900 A solution.cpp
```

### Using Python

```bash
# Parse with Python template
cf parse 1900 A --lang python

# Test Python solution
cd 1900/A
cf test

# Submit Python solution
cf submit 1900 A solution.py
```

### Custom Test Cases

You can add custom test cases by creating `inN.txt` and `outN.txt` files:

```bash
cd 1900/A
echo "5 3" > in3.txt
echo "8" > out3.txt
cf test
```

## Troubleshooting

### Compilation Errors

If you get compilation errors, check your compiler configuration:

```bash
cf config get compiler.cpp
```

You can customize the compiler command:

```bash
cf config set compiler.cpp "g++ -std=c++20 -O2 -Wall"
```

### Authentication Issues

If you have trouble logging in:

1. Make sure you're using your Codeforces handle (username), not email
2. Check if your account is active
3. Try logging in through the website first

### Network Issues

If you get network errors:

- Check your internet connection
- Codeforces might be down (check [codeforces.com](https://codeforces.com))
- Try again in a few moments

## Development

### Setting Up Development Environment

```bash
cd cf_tool

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Install in editable mode
pip install -e .
```

### Running Tests

```bash
pytest
```

### Code Formatting

```bash
black cf/
flake8 cf/
```

## Differences from Original cf-tool

This Python rewrite focuses on the core features:

- ✅ Parse problems
- ✅ Local testing
- ✅ Submit solutions
- ✅ Configuration management
- ✅ Templates

Features not yet implemented:
- Race mode (contest timing)
- Standings viewer
- Pull/clone entire contests
- Advanced watch mode

## Contributing

Contributions are welcome! Feel free to:

- Report bugs
- Suggest features
- Submit pull requests

## License

MIT License

## Acknowledgments

- Original [cf-tool](https://github.com/xalanq/cf-tool) by xalanq
- Inspired by the competitive programming community

## Links

- [Codeforces](https://codeforces.com)
- [Original cf-tool](https://github.com/xalanq/cf-tool)
