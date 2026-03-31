"""
Session and authentication management for Codeforces.

Uses DrissionPage (real browser) for login to bypass Cloudflare Turnstile,
and cloudscraper for subsequent requests.
"""

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import sys

import cloudscraper
from bs4 import BeautifulSoup

from cf.constants import BASE_URL, LOGIN_URL, REQUEST_TIMEOUT
from rich.console import Console

from cf.utils import AuthenticationError, get_config_dir

console = Console()


def _get_platform() -> str:
    """Detect platform for cloudscraper browser config."""
    if sys.platform == "darwin":
        return "darwin"
    elif sys.platform == "win32":
        return "windows"
    return "linux"


class Session:
    """Manages Codeforces session and authentication."""

    def __init__(self):
        """Initialize session."""
        self.session_file = get_config_dir() / "session"
        self.client = None
        self.csrf_token = None
        self._init_client()

    def _init_client(self):
        """Initialize HTTP client with saved cookies if available."""
        # Create cloudscraper session for HTTP requests
        self.client = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': _get_platform(),
                'desktop': True,
            }
        )
        self.client.timeout = REQUEST_TIMEOUT
        self.client.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })

        # Load saved session
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

            # Restore cookies to HTTP client
            cookies = session_data.get("cookies", {})
            for name, value in cookies.items():
                self.client.cookies.set(name, value)

            self.csrf_token = session_data.get("csrf_token")

            return True

        except (json.JSONDecodeError, IOError):
            return False

    def save_session(self, username: str, cookies: dict) -> None:
        """
        Save session to file.

        Args:
            username: Codeforces username
            cookies: Dictionary of cookies
        """
        expires_at = datetime.now() + timedelta(days=30)

        session_data = {
            "cookies": cookies,
            "csrf_token": self.csrf_token,
            "username": username,
            "expires_at": expires_at.isoformat(),
        }

        try:
            with open(self.session_file, 'w') as f:
                json.dump(session_data, f, indent=2)

            self.session_file.chmod(0o600)

        except IOError as e:
            console.print(f"[yellow]Warning: Failed to save session: {e}[/yellow]")

    def extract_csrf_token(self, html: str) -> Optional[str]:
        """Extract CSRF token from HTML."""
        # Method 1: data-csrf attribute
        match = re.search(r'data-csrf=[\'"]([a-f0-9]+)[\'"]', html)
        if match:
            return match.group(1)

        # Method 2: Hidden input
        match = re.search(r"name=['\"]csrf_token['\"].*?value=['\"]([a-f0-9]+)['\"]", html, re.DOTALL)
        if match:
            return match.group(1)

        # Method 3: BeautifulSoup
        soup = BeautifulSoup(html, 'lxml')
        elem = soup.find(attrs={'data-csrf': True})
        if elem:
            return elem.get('data-csrf')

        csrf_input = soup.find('input', {'name': 'csrf_token'})
        if csrf_input and csrf_input.get('value'):
            return csrf_input['value']

        return None

    def login(self, username: str, password: str) -> None:
        """
        Login to Codeforces using browser automation.

        Opens a real Chrome browser to handle Cloudflare Turnstile.

        Args:
            username: Codeforces username or email
            password: Password

        Raises:
            AuthenticationError: If login fails
        """
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
        except ImportError:
            raise AuthenticationError(
                "DrissionPage is required for login. Install it with: pip install DrissionPage"
            )

        console.print("[cyan]Opening browser for Codeforces login...[/cyan]")
        console.print("[dim](This is needed to bypass Cloudflare protection)[/dim]")

        page = None
        try:
            # Configure browser options
            options = ChromiumOptions()
            options.set_argument('--no-first-run')
            options.set_argument('--no-default-browser-check')
            options.set_argument('--disable-infobars')

            # Create browser instance
            page = ChromiumPage(options)

            # Navigate to Codeforces
            page.get(BASE_URL)

            # Wait for page to load (handles Cloudflare challenge automatically)
            time.sleep(2)

            # Navigate to login page
            page.get(LOGIN_URL)

            # Wait for login page to load
            time.sleep(2)

            # Check if already logged in (redirected away from /enter) or on login page
            on_login_page = False
            for _ in range(10):
                if '/enter' not in page.url:
                    # Redirected away - already logged in
                    break
                # Check if login form exists
                if page.ele('#handleOrEmail'):
                    on_login_page = True
                    break
                time.sleep(1)

            if on_login_page:
                # Fill in login form
                self._fill_login_form(page, username, password)

                # Wait for login to complete
                console.print("[cyan]Logging in...[/cyan]")
                time.sleep(3)

                # Check if login succeeded (should redirect away from /enter)
                for _ in range(15):
                    if '/enter' not in page.url:
                        break
                    time.sleep(1)

                # Verify login success
                if '/enter' in page.url:
                    error_elem = page.ele('.error') or page.ele('xpath://*[contains(@class, "error")]')
                    error_msg = "Login failed - please check your credentials"
                    if error_elem:
                        error_msg = error_elem.text or error_msg
                    raise AuthenticationError(error_msg)
            else:
                console.print("[green]Already logged in, extracting session...[/green]")

            # Extract cookies from browser
            cookies = {cookie['name']: cookie['value'] for cookie in page.cookies()}

            # Get CSRF token from page
            self.csrf_token = self.extract_csrf_token(page.html)

            # Save session
            self.save_session(username, cookies)

            # Update HTTP client with cookies
            for name, value in cookies.items():
                self.client.cookies.set(name, value)

            console.print("[green]Login successful![/green]")

        except AuthenticationError:
            raise
        except Exception as e:
            raise AuthenticationError(f"Browser login failed: {e}")
        finally:
            if page is not None:
                try:
                    page.quit()
                except Exception:
                    pass

    def _fill_login_form(self, page, username: str, password: str) -> None:
        """Fill in the login form fields."""
        # Find and fill username field
        handle_input = page.ele('#handleOrEmail') or page.ele('@name=handleOrEmail')
        if not handle_input:
            raise AuthenticationError("Could not find username field")
        handle_input.clear()
        handle_input.input(username)

        # Find and fill password field
        password_input = page.ele('#password') or page.ele('@name=password')
        if not password_input:
            raise AuthenticationError("Could not find password field")
        password_input.clear()
        password_input.input(password)

        # Check "Remember me"
        remember = page.ele('#remember') or page.ele('@name=remember')
        if remember and not remember.attr('checked'):
            remember.click()

        # Find and click submit button
        submit_btn = page.ele('@value=Login') or page.ele('xpath://input[@type="submit"]') or page.ele('.submit')
        if submit_btn:
            submit_btn.click()
        else:
            password_input.input('\n')

    def is_authenticated(self) -> bool:
        """Check if currently authenticated."""
        try:
            response = self.client.get(f"{BASE_URL}/profile")
            return "/enter" not in str(response.url) and "handleOrEmail" not in response.text
        except Exception:
            return False

    def get_csrf_token(self, url: str) -> str:
        """Get CSRF token from a page."""
        try:
            response = self.client.get(url)
            response.raise_for_status()

            csrf_token = self.extract_csrf_token(response.text)

            if not csrf_token:
                raise AuthenticationError("Could not extract CSRF token")

            self.csrf_token = csrf_token
            return csrf_token

        except Exception as e:
            raise AuthenticationError(f"Failed to get CSRF token: {e}")

    def get(self, url: str, **kwargs):
        """Make a GET request."""
        return self.client.get(url, **kwargs)

    def post(self, url: str, **kwargs):
        """Make a POST request."""
        return self.client.post(url, **kwargs)

    def close(self) -> None:
        """Close the session."""
        if self.client:
            self.client.close()
