"""
Configuration management for cf-tool.

Manages ~/.cf/config file for storing user preferences.
"""

import json
from pathlib import Path
from typing import Any, Optional

from cf.constants import DEFAULT_CONFIG
from cf.utils import get_config_dir


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries, with override taking precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    """Configuration manager for cf-tool."""

    def __init__(self):
        """Initialize configuration."""
        self.config_dir = get_config_dir()
        self.config_file = self.config_dir / "config"
        self.data = self.load()

    def load(self) -> dict:
        """
        Load configuration from file.

        Returns:
            Configuration dictionary
        """
        if not self.config_file.exists():
            return DEFAULT_CONFIG.copy()

        try:
            loaded_config = json.loads(self.config_file.read_text())
            # Deep merge with defaults (in case new keys were added)
            return _deep_merge(DEFAULT_CONFIG, loaded_config)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load config file: {e}")
            return DEFAULT_CONFIG.copy()

    def save(self) -> None:
        """Save configuration to file."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            self.config_file.write_text(json.dumps(self.data, indent=2))
        except IOError as e:
            print(f"Error: Failed to save config file: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value.

        Args:
            key: Configuration key (supports dot notation like "compiler.cpp")
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        # Support dot notation for nested keys
        keys = key.split('.')
        value = self.data

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """
        Set configuration value.

        Args:
            key: Configuration key (supports dot notation like "compiler.cpp")
            value: Value to set
        """
        # Support dot notation for nested keys
        keys = key.split('.')

        if len(keys) == 1:
            self.data[key] = value
        else:
            # Navigate to the parent dict and set the value
            current = self.data
            for k in keys[:-1]:
                if k not in current or not isinstance(current[k], dict):
                    current[k] = {}
                current = current[k]
            current[keys[-1]] = value

    def get_template_path(self, language: str) -> Optional[Path]:
        """
        Get template file path for a language.

        Args:
            language: Programming language

        Returns:
            Path to template file or None
        """
        templates = self.data.get("templates", {})
        template_path = templates.get(language)

        if not template_path:
            return None

        # Expand ~ to home directory
        path = Path(template_path).expanduser()

        # If path doesn't exist, check in package templates directory
        if not path.exists():
            # Try package templates directory
            import cf
            package_dir = Path(cf.__file__).parent.parent
            package_template = package_dir / "templates" / f"template.{language}"
            if package_template.exists():
                return package_template

        return path if path.exists() else None

    def get_compiler_command(self, language: str) -> Optional[str]:
        """
        Get compiler command for a language.

        Args:
            language: Programming language

        Returns:
            Compiler command or None
        """
        compilers = self.data.get("compiler", {})
        return compilers.get(language)
