"""
Cloudflare bypass for py-clob-client.

Monkey-patches the HTTP helpers to use browser-like headers.
Must be imported BEFORE py_clob_client.
"""

import httpx

# Browser-like headers to bypass Cloudflare
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Content-Type": "application/json",
    "Origin": "https://polymarket.com",
    "Referer": "https://polymarket.com/",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


def patch_clob_client():
    """Patch py-clob-client to use browser headers."""
    try:
        import py_clob_client.http_helpers.helpers as helpers

        # Store original function
        original_overloadHeaders = helpers.overloadHeaders

        def patched_overloadHeaders(method: str, headers: dict) -> dict:
            """Patched version with browser headers."""
            if headers is None:
                headers = dict()

            # Use browser headers instead of py_clob_client
            headers.update(BROWSER_HEADERS)

            return headers

        # Apply patch
        helpers.overloadHeaders = patched_overloadHeaders

        # Also create a new HTTP client with longer timeout
        helpers._http_client = httpx.Client(
            http2=True,
            timeout=30.0,
            follow_redirects=True,
        )

        print("✓ Cloudflare bypass patch applied")
        return True

    except Exception as e:
        print(f"✗ Failed to apply patch: {e}")
        return False


# Auto-apply patch on import
patch_clob_client()
