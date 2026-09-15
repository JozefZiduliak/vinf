"""Stage 1.1 — polite BFS crawler.

Reads:  nothing (start URL below)
Writes: data/raw/<slug>.html, checkpoints/crawler.json
"""

# --- site-specific config (swap domain by editing these) ---
START_URL = "https://animaldiversity.org/accounts/"
ALLOWED_URL_PATTERN = r"^https://animaldiversity\.org/accounts/[A-Z][a-z]+_[a-z]+/?$"
USER_AGENT = "vinf-crawler/0.1 (FIIT STU student project)"
DELAY_SECONDS = 1.0
# ------------------------------------------------------------


def main() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()
