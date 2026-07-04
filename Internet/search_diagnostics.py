"""Safe command-line diagnostics for live public-search providers."""

from __future__ import annotations

import argparse
from typing import Sequence

from .search import BaseSearchProvider, BingSearchProvider, DuckDuckGoSearchProvider, execute_search


def _providers() -> tuple[BaseSearchProvider, ...]:
    """Return the provider set checked by the standalone diagnostic command."""

    return (
        DuckDuckGoSearchProvider(),
        BingSearchProvider(),
    )


def _print_provider_result(provider: BaseSearchProvider, query: str, limit: int) -> bool:
    """Run one provider check and print only safe structured details."""

    outcome = execute_search(provider, query, limit=limit)
    diagnostic = outcome.attempts[-1] if outcome.attempts else None
    provider_name = diagnostic.provider_name if diagnostic is not None else type(provider).__name__
    succeeded = outcome.succeeded

    print(f"Provider: {provider_name}")
    print(f"Status: {'success' if succeeded else 'failure'}")
    if diagnostic is not None and not diagnostic.succeeded:
        print(f"Failure category: {diagnostic.status}")
    print(f"Result count: {len(outcome.results)}")
    if outcome.results:
        first = outcome.results[0]
        print(f"First result title: {first.title}")
        print(f"First result URL: {first.url}")
    print("")
    return succeeded


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone provider diagnostic entrypoint."""

    parser = argparse.ArgumentParser(description="Run safe live-search diagnostics without launching full NARVIS.")
    parser.add_argument("--query", required=True, help="Search query to test.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum results to request from each provider.")
    args = parser.parse_args(argv)

    success = False
    for provider in _providers():
        success = _print_provider_result(provider, args.query, max(args.limit, 1)) or success
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
