# Security policy

## Supported versions

Only the latest release on the `main` branch receives fixes.

## Reporting a vulnerability

Please don't open a public issue for security problems. Use GitHub's private vulnerability reporting ("Report a vulnerability" on the repository's **Security** tab). If that option isn't available, open an issue that only asks for a private contact, without details, and the maintainer will follow up.

Useful reports include the robotspec version, the input that triggers the problem, and its impact.

## Scope

robotspec reads local files and, only when given a URL, fetches that site's `/robots.txt` (read limit about 500 KiB, 15-second timeout, at most five redirects). Issues such as crashes or excessive resource use on crafted robots.txt input are in scope.

Note that robots.txt itself is not a security mechanism; a robots.txt that allows or blocks a crawler is not a vulnerability in robotspec.
