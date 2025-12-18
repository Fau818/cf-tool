"""
Session and authentication management for Codeforces.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

import httpx
from bs4 import BeautifulSoup

from cf.constants import BASE_URL, LOGIN_URL, REQUEST_TIMEOUT, USER_AGENT
from cf.utils import AuthenticationError, get_config_dir


class Session:
    """Manages Codeforces session and authentication."""

    def __init__(self):
        """Initialize session."""
        self.session_file = get_config_dir() / "session"
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )
        self.csrf_token = None
        self.load_session()

    def load_session(self) -> bool:
        """
        Load session from file.

        Returns:
            True if session loaded successfully, False otherwise
        """
        if not self.session_file.exists():
            return False

        try:
            with open(self.session_file, 'r') as f:
                session_data = json.load(f)

            # Check if session expired
            expires_at = session_data.get("expires_at")
            if expires_at:
                expiry = datetime.fromisoformat(expires_at)
                if datetime.now() >= expiry:
                    return False

            # Restore cookies
            cookies = session_data.get("cookies", {})
            for name, value in cookies.items():
                self.client.cookies.set(name, value)

            self.csrf_token = session_data.get("csrf_token")

            return True

        except (json.JSONDecodeError, IOError):
            return False

    def save_session(self, username: str) -> None:
        """
        Save session to file.

        Args:
            username: Codeforces username
        """
        # Session expires in 30 days
        expires_at = datetime.now() + timedelta(days=30)

        session_data = {
            "cookies": dict(self.client.cookies),
            "csrf_token": self.csrf_token,
            "username": username,
            "expires_at": expires_at.isoformat(),
        }

        try:
            with open(self.session_file, 'w') as f:
                json.dump(session_data, f, indent=2)

            # Set restrictive permissions
            self.session_file.chmod(0o600)

        except IOError as e:
            print(f"Warning: Failed to save session: {e}")

    def extract_csrf_token(self, html: str) -> Optional[str]:
        """
        Extract CSRF token from HTML.

        Args:
            html: HTML content

        Returns:
            CSRF token or None
        """
        soup = BeautifulSoup(html, 'lxml')

        # Look for csrf token in meta tag
        csrf_meta = soup.find('meta', {'name': 'X-Csrf-Token'})
        if csrf_meta and csrf_meta.get('content'):
            return csrf_meta['content']

        # Look for csrf token in hidden input
        csrf_input = soup.find('input', {'name': 'csrf_token'})
        if csrf_input and csrf_input.get('value'):
            return csrf_input['value']

        # Try to find it in the HTML with regex as fallback
        match = re.search(r'csrf[\'"]?\s*[:=]\s*[\'"]([a-f0-9]+)[\'"]', html, re.I)
        if match:
            return match.group(1)

        return None

    def login(self, username: str, password: str) -> None:
        """
        Login to Codeforces.

        Args:
            username: Codeforces username or email
            password: Password

        Raises:
            AuthenticationError: If login fails
        """
        try:
            # First, get the login page to get CSRF token
            response = self.client.get(LOGIN_URL)
            response.raise_for_status()

            csrf_token = self.extract_csrf_token(response.text)

            if not csrf_token:
                raise AuthenticationError("Could not extract CSRF token from login page")

            self.csrf_token = csrf_token

            # Prepare login data
            login_data = {
                "csrf_token": csrf_token,
                "action": "enter",
                "handleOrEmail": username,
                "password": password,
                "remember": "on",
            }

            # Submit login
            response = self.client.post(LOGIN_URL, data=login_data)
            response.raise_for_status()

            # Check if login was successful
            # Codeforces redirects to home page on successful login
            # If we're still on /enter or see login form, login failed
            if "/enter" in str(response.url) or "handleOrEmail" in response.text:
                # Try to extract error message
                soup = BeautifulSoup(response.text, 'lxml')
                error_div = soup.find('div', class_='error')
                error_msg = "Invalid username or password"
                if error_div:
                    error_msg = error_div.get_text().strip()

                raise AuthenticationError(error_msg)

            # Update CSRF token from response
            new_csrf = self.extract_csrf_token(response.text)
            if new_csrf:
                self.csrf_token = new_csrf

            # Save session
            self.save_session(username)

        except httpx.HTTPError as e:
            raise AuthenticationError(f"Network error during login: {e}")

    def is_authenticated(self) -> bool:
        """
        Check if currently authenticated.

        Returns:
            True if authenticated, False otherwise
        """
        try:
            # Try to access a page that requires authentication
            response = self.client.get(f"{BASE_URL}/profile")
            # If redirected to login, not authenticated
            return "/enter" not in str(response.url)

        except httpx.HTTPError:
            return False

    def get_csrf_token(self, url: str) -> str:
        """
        Get CSRF token from a page.

        Args:
            url: URL to fetch

        Returns:
            CSRF token

        Raises:
            AuthenticationError: If token cannot be retrieved
        """
        try:
            response = self.client.get(url)
            response.raise_for_status()

            csrf_token = self.extract_csrf_token(response.text)

            if not csrf_token:
                raise AuthenticationError("Could not extract CSRF token")

            self.csrf_token = csrf_token
            return csrf_token

        except httpx.HTTPError as e:
            raise AuthenticationError(f"Failed to get CSRF token: {e}")

    def close(self) -> None:
        """Close the session."""
        self.client.close()
