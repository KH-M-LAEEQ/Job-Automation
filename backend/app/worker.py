"""Standalone background worker: python -m app.worker

Runs discovery, enrichment, follow-up drafting and notifications outside the API process,
so scaling or restarting the API never starts or stops background work."""
from app.config import get_settings
from app.logging_config import configure_logging
from app.scheduler import run_forever


def main() -> None:
    configure_logging()
    get_settings().assert_secure()
    run_forever()


if __name__ == "__main__":
    main()
