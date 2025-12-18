"""
Web scraping module for fetching problem data from Codeforces.

Uses cloudscraper to bypass Cloudflare protection.
"""

import re
from typing import Dict, List, Tuple

import cloudscraper
from bs4 import BeautifulSoup

from cf.constants import REQUEST_TIMEOUT, URL_PATTERNS
from cf.utils import NetworkError, ParseError


class CodeforceScraper:
    """Scraper for Codeforces website."""

    def __init__(self):
        """Initialize scraper with cloudscraper to bypass Cloudflare."""
        # Create cloudscraper session - this handles Cloudflare challenges
        self.client = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'darwin',  # macOS
                'desktop': True,
            }
        )
        self.client.timeout = REQUEST_TIMEOUT

    def fetch_problem(
        self, contest_id: str, problem_id: str, contest_type: str = "contest"
    ) -> str:
        """
        Fetch problem page HTML.

        Args:
            contest_id: Contest ID
            problem_id: Problem ID (letter)
            contest_type: Type of contest (contest, gym, problemset)

        Returns:
            HTML content of the problem page

        Raises:
            NetworkError: If request fails
        """
        # Get URL pattern
        pattern = URL_PATTERNS.get(contest_type)
        if not pattern:
            raise ValueError(f"Unknown contest type: {contest_type}")

        url = pattern.format(cid=contest_id, pid=problem_id.upper())

        try:
            response = self.client.get(url)
            response.raise_for_status()
            return response.text

        except cloudscraper.exceptions.CloudflareChallengeError as e:
            raise NetworkError(f"Cloudflare challenge failed: {e}")
        except Exception as e:
            raise NetworkError(f"Failed to fetch problem: {e}")

    def extract_test_cases(self, html: str) -> List[Tuple[str, str]]:
        """
        Extract sample test cases from problem HTML.

        Args:
            html: Problem page HTML

        Returns:
            List of (input, output) tuples

        Raises:
            ParseError: If parsing fails
        """
        try:
            soup = BeautifulSoup(html, 'lxml')

            # Find sample tests section
            test_cases = []

            # Method 1: Look for divs with class 'sample-test'
            sample_test = soup.find('div', class_='sample-test')

            if sample_test:
                # Find all input divs
                inputs = sample_test.find_all('div', class_='input')
                outputs = sample_test.find_all('div', class_='output')

                for inp, out in zip(inputs, outputs):
                    # Get the <pre> tag content
                    input_pre = inp.find('pre')
                    output_pre = out.find('pre')

                    if input_pre and output_pre:
                        input_text = input_pre.get_text()
                        output_text = output_pre.get_text()

                        # Clean up the text (remove extra whitespace but preserve structure)
                        input_text = input_text.strip()
                        output_text = output_text.strip()

                        test_cases.append((input_text, output_text))

            if not test_cases:
                raise ParseError("No test cases found in problem page")

            return test_cases

        except Exception as e:
            raise ParseError(f"Failed to parse test cases: {e}")

    def extract_problem_metadata(self, html: str) -> Dict[str, str]:
        """
        Extract problem metadata (title, time limit, memory limit, etc.).

        Args:
            html: Problem page HTML

        Returns:
            Dictionary with metadata

        Raises:
            ParseError: If parsing fails
        """
        try:
            soup = BeautifulSoup(html, 'lxml')
            metadata = {}

            # Extract problem title
            title_div = soup.find('div', class_='title')
            if title_div:
                metadata['title'] = title_div.get_text().strip()

            # Extract time limit
            time_limit_div = soup.find('div', class_='time-limit')
            if time_limit_div:
                time_text = time_limit_div.get_text()
                # Extract number from text like "time limit per test2 seconds"
                match = re.search(r'(\d+(?:\.\d+)?)\s*second', time_text)
                if match:
                    metadata['time_limit'] = f"{match.group(1)}s"

            # Extract memory limit
            memory_limit_div = soup.find('div', class_='memory-limit')
            if memory_limit_div:
                memory_text = memory_limit_div.get_text()
                # Extract number from text like "memory limit per test256 megabytes"
                match = re.search(r'(\d+)\s*megabyte', memory_text)
                if match:
                    metadata['memory_limit'] = f"{match.group(1)}MB"

            # Extract input/output format
            input_div = soup.find('div', class_='input-file')
            if input_div:
                metadata['input_file'] = input_div.get_text().strip()

            output_div = soup.find('div', class_='output-file')
            if output_div:
                metadata['output_file'] = output_div.get_text().strip()

            return metadata

        except Exception as e:
            raise ParseError(f"Failed to parse metadata: {e}")

    def get_problem_data(
        self, contest_id: str, problem_id: str, contest_type: str = "contest"
    ) -> Dict:
        """
        Get complete problem data including test cases and metadata.

        Args:
            contest_id: Contest ID
            problem_id: Problem ID (letter)
            contest_type: Type of contest

        Returns:
            Dictionary with problem data

        Raises:
            NetworkError, ParseError: If fetching or parsing fails
        """
        html = self.fetch_problem(contest_id, problem_id, contest_type)
        test_cases = self.extract_test_cases(html)
        metadata = self.extract_problem_metadata(html)

        return {
            "contest_id": contest_id,
            "problem_id": problem_id.upper(),
            "contest_type": contest_type,
            "test_cases": test_cases,
            "metadata": metadata,
        }
