"""GitHub App installation verification CLI.

App auth → list installations → print each installation's repository_selection
and accessible repos. Used to confirm an "All repositories" installation really
covers every repo.

Usage: uv run python -m app.identity.verify_install
"""

from loguru import logger

from app.clients.github_app import app_client, installation_client


def main() -> None:
    github = app_client()
    app_info = github.rest.apps.get_authenticated().parsed_data
    logger.info("App auth OK: {} (id={})", app_info.name, app_info.id)

    installations = github.rest.apps.list_installations().parsed_data
    if not installations:
        logger.warning("No installations found — install the App from its settings page first")
        return

    for inst in installations:
        account = getattr(inst.account, "login", None) or getattr(inst.account, "slug", "?")
        client = installation_client(github, inst.id)
        repos = client.rest.apps.list_repos_accessible_to_installation(per_page=100).parsed_data
        logger.info(
            "Installation {}: account={} selection={} repos={}",
            inst.id,
            account,
            inst.repository_selection,
            repos.total_count,
        )
        for repo in repos.repositories:
            logger.info("  - {}", repo.full_name)
        if repos.total_count > len(repos.repositories):
            logger.info("  … and {} more (first page only)", repos.total_count - len(repos.repositories))


if __name__ == "__main__":
    main()
