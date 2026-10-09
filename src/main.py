"""Scheduled Azure DevOps activity sync entry point."""

import argparse
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .azure_client import AzureClient
from .commit_filter import normalize, unique_sorted
from .git_publisher import Publisher
from .state_manager import load_state


LOG = logging.getLogger(__name__)


def allowed(name, rules):
    included = rules.get("include", [])
    return (not included or name in included) and name not in rules.get("exclude", [])


def read_config(path: Path):
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    azure = config["azure_devops"]
    organization_override = os.environ.get("AZURE_DEVOPS_ORGANIZATION")
    authors_override = os.environ.get("AZURE_AUTHOR_EMAILS")
    if organization_override:
        azure["organization"] = organization_override.strip()
    if authors_override:
        azure["authors"]["emails"] = authors_override.split(",")
    organization = azure["organization"]
    emails = {value.strip().casefold() for value in azure["authors"]["emails"]}
    if not organization or organization == "CHANGE_ME" or not emails or any("CHANGE_ME" in x for x in emails):
        raise ValueError("Set the Azure organization and author emails in config.yaml")
    if int(config["sync"]["lookback_days"]) < 1:
        raise ValueError("lookback_days must be positive")
    if not 1 <= int(config["output"]["hash_length"]) <= 40:
        raise ValueError("hash_length must be between 1 and 40")
    output = Path(config["output"]["directory"])
    if output.is_absolute() or ".." in output.parts or not output.parts:
        raise ValueError("output.directory must be inside the repository")
    return config, emails


def collect(client, config, emails, *, earliest):
    azure = config["azure_devops"]
    found = []
    for project in client.projects():
        if not allowed(project["name"], azure.get("projects", {})):
            continue
        for repository in client.repositories(project["id"]):
            if repository.get("isDisabled") or not allowed(repository["name"], azure.get("repositories", {})):
                continue
            for branch in client.branches(project["id"], repository["id"]):
                if not allowed(branch, azure.get("branches", {})):
                    continue
                for raw in client.commits(project["id"], repository["id"], branch, earliest.isoformat()):
                    # Azure can truncate a long first line in list responses.
                    if raw.get("commentTruncated"):
                        raw = client.commit(project["id"], repository["id"], raw["commitId"])
                    commit = normalize(raw, organization_id=azure["organization"],
                                       project_id=project["id"], project_name=project["name"],
                                       repository_id=repository["id"], emails=emails, earliest=earliest)
                    if commit:
                        found.append(commit)
    return unique_sorted(found)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--destination", type=Path, required=True,
                        help="Checkout of the separate private GitHub destination repository")
    parser.add_argument("--dry-run", action="store_true", help="List candidates without writing or pushing")
    parser.add_argument("--show-details", action="store_true",
                        help="Show commit details in local dry-run output; do not use in public CI")
    parser.add_argument("--repair-format", action="store_true",
                        help="Repair existing activity Markdown in a maintenance commit without querying Azure")
    parser.add_argument("--since", help="Historical backfill start date (YYYY-MM-DD, UTC)")
    args = parser.parse_args()
    if args.repair_format and (args.dry_run or args.since or args.show_details):
        parser.error("--repair-format cannot be combined with sync options")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    source_root = Path(__file__).resolve().parents[1]
    destination = args.destination.resolve()
    if destination == source_root or not (destination / ".git").exists():
        parser.error("--destination must be a separate Git checkout")
    if args.repair_format:
        config = yaml.safe_load((source_root / args.config).read_text(encoding="utf-8"))
        email = os.environ.get("GITHUB_COMMIT_EMAIL")
        name = os.environ.get("GITHUB_COMMIT_NAME")
        branch = os.environ.get("GITHUB_DEFAULT_BRANCH")
        if not email or not name or not branch:
            parser.error("GITHUB_COMMIT_EMAIL, GITHUB_COMMIT_NAME and GITHUB_DEFAULT_BRANCH are required")
        publisher = Publisher(destination, branch=branch, email=email, name=name,
                              output_dir=config["output"]["directory"],
                              hash_length=int(config["output"]["hash_length"]),
                              timezone=config["sync"]["timezone"])
        publisher.repair_format()
        return
    config, emails = read_config(source_root / args.config)
    pat = os.environ.get("AZURE_DEVOPS_PAT")
    if not pat:
        parser.error("AZURE_DEVOPS_PAT is required")
    if args.since:
        earliest = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    else:
        earliest = datetime.now(timezone.utc) - timedelta(days=int(config["sync"]["lookback_days"]))
    client = AzureClient(config["azure_devops"]["organization"], pat)
    commits = collect(client, config, emails, earliest=earliest)
    state = load_state(destination / "state/synced_commits.json")
    pending = [commit for commit in commits if commit.key not in state["synced"]]
    LOG.info("Scan completed")
    if args.dry_run:
        if args.show_details:
            LOG.info("Found %s unique commits; %s pending", len(commits), len(pending))
            for commit in pending:
                LOG.info("Would publish %s %s %s", commit.project_name, commit.sha, commit.message)
        else:
            LOG.info("Dry run completed without publishing")
        return
    if not pending:
        return
    email = os.environ.get("GITHUB_COMMIT_EMAIL")
    name = os.environ.get("GITHUB_COMMIT_NAME")
    branch = os.environ.get("GITHUB_DEFAULT_BRANCH")
    if not email or not name or not branch:
        parser.error("GITHUB_COMMIT_EMAIL, GITHUB_COMMIT_NAME and GITHUB_DEFAULT_BRANCH are required")
    publisher = Publisher(destination, branch=branch, email=email, name=name,
                          output_dir=config["output"]["directory"],
                          hash_length=int(config["output"]["hash_length"]),
                          timezone=config["sync"]["timezone"])
    for commit in pending:
        publisher.publish(commit)


if __name__ == "__main__":
    main()
