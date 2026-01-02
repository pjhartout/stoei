#!/usr/bin/env python3
"""Script to automate version bumping, tagging, and GitHub releases.

Usage:
    python scripts/release.py patch   # Bump patch version (0.2.2 -> 0.2.3)
    python scripts/release.py minor   # Bump minor version (0.2.2 -> 0.3.0)
    python scripts/release.py major   # Bump major version (0.2.2 -> 1.0.0)
    python scripts/release.py 0.2.3  # Set specific version
"""

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
PYPROJECT_TOML = PROJECT_ROOT / "pyproject.toml"
INIT_PY = PROJECT_ROOT / "stoei" / "__init__.py"
VERSION_PARTS_COUNT = 3
MIN_ARGS_COUNT = 2


class VersionError(Exception):
    """Base exception for version-related errors."""


class VersionNotFoundError(VersionError):
    """Raised when version cannot be found in pyproject.toml."""

    def __init__(self) -> None:
        """Initialize the VersionNotFoundError."""
        super().__init__("Could not find version in pyproject.toml")


class InvalidVersionFormatError(VersionError):
    """Raised when version format is invalid."""

    def __init__(self, version: str) -> None:
        """Initialize the InvalidVersionFormatError.

        Args:
            version: The invalid version string.
        """
        super().__init__(f"Invalid version format: {version}")
        self.version = version


class InvalidBumpTypeError(VersionError):
    """Raised when bump type is invalid."""

    def __init__(self, bump_type: str) -> None:
        """Initialize the InvalidBumpTypeError.

        Args:
            bump_type: The invalid bump type string.
        """
        super().__init__(f"Invalid bump type: {bump_type}. Use patch, minor, or major")
        self.bump_type = bump_type


class TagExistsError(Exception):
    """Raised when a tag already exists."""

    def __init__(self, tag_name: str) -> None:
        """Initialize the TagExistsError.

        Args:
            tag_name: The tag name that already exists.
        """
        super().__init__(f"Tag {tag_name} already exists")
        self.tag_name = tag_name


def get_current_version() -> str:
    """Get the current version from pyproject.toml."""
    content = PYPROJECT_TOML.read_text()
    match = re.search(r'version = "([^"]+)"', content)
    if not match:
        raise VersionNotFoundError()
    return match.group(1)


def bump_version(current: str, bump_type: str) -> str:
    """Bump version based on type (patch, minor, major)."""
    parts = [int(x) for x in current.split(".")]

    if len(parts) != VERSION_PARTS_COUNT:
        raise InvalidVersionFormatError(current)

    if bump_type == "patch":
        parts[2] += 1
    elif bump_type == "minor":
        parts[1] += 1
        parts[2] = 0
    elif bump_type == "major":
        parts[0] += 1
        parts[1] = 0
        parts[2] = 0
    else:
        raise InvalidBumpTypeError(bump_type)

    return ".".join(str(x) for x in parts)


def update_version_in_file(file_path: Path, old_version: str, new_version: str) -> None:
    """Update version string in a file."""
    content = file_path.read_text()

    # Update version in pyproject.toml
    if file_path.name == "pyproject.toml":
        content = re.sub(rf'version = "{re.escape(old_version)}"', f'version = "{new_version}"', content)
    # Update version in __init__.py
    elif file_path.name == "__init__.py":
        content = re.sub(rf'__version__ = "{re.escape(old_version)}"', f'__version__ = "{new_version}"', content)

    file_path.write_text(content)


def update_all_versions(old_version: str, new_version: str) -> None:
    """Update version in all relevant files."""
    update_version_in_file(PYPROJECT_TOML, old_version, new_version)
    update_version_in_file(INIT_PY, old_version, new_version)


def run_command(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a shell command."""
    print(f"Running: {' '.join(cmd)}")
    # Security: This script is intended to run trusted git/gh commands only
    result = subprocess.run(cmd, check=check, capture_output=True, text=True, cwd=PROJECT_ROOT)  # noqa: S603
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result


def create_tag(version: str) -> None:
    """Create a git tag for the version."""
    tag_name = f"v{version}"

    # Check if tag already exists
    result = run_command(["git", "tag", "-l", tag_name], check=False)
    if tag_name in result.stdout:
        raise TagExistsError(tag_name)

    # Check if GPG signing is configured
    result = run_command(["git", "config", "--get", "user.signingkey"], check=False)
    use_signing = result.returncode == 0

    if use_signing:
        run_command(["git", "tag", "-a", tag_name, "-m", f"Release {tag_name}"])
    else:
        run_command(["git", "tag", "--no-sign", tag_name, "-m", f"Release {tag_name}"])
    print(f"✓ Created tag {tag_name}")


def create_github_release(version: str, draft: bool = False) -> None:
    """Create a GitHub release using gh CLI."""
    tag_name = f"v{version}"

    # Check if gh CLI is available
    result = run_command(["which", "gh"], check=False)
    if result.returncode != 0:
        print("⚠ GitHub CLI (gh) not found. Skipping GitHub release creation.")
        print("  Install it from https://cli.github.com/ or create the release manually.")
        return

    # Check if user is authenticated
    result = run_command(["gh", "auth", "status"], check=False)
    if result.returncode != 0:
        print("⚠ Not authenticated with GitHub CLI. Skipping GitHub release creation.")
        print("  Run 'gh auth login' to authenticate.")
        return

    # Get the latest commit message as release notes
    result = run_command(["git", "log", "-1", "--pretty=%B"])
    release_notes = result.stdout.strip() if result.stdout else f"Release {tag_name}"

    cmd = ["gh", "release", "create", tag_name, "--title", tag_name, "--notes", release_notes]
    if draft:
        cmd.append("--draft")

    run_command(cmd)
    print(f"✓ Created GitHub release {tag_name}")


def determine_new_version(version_arg: str, current_version: str) -> str:
    """Determine the new version based on user input."""
    if version_arg in ("patch", "minor", "major"):
        new_version = bump_version(current_version, version_arg)
        print(f"Bumping {version_arg} version: {current_version} -> {new_version}")
        return new_version
    if re.match(r"^\d+\.\d+\.\d+$", version_arg):
        print(f"Setting version to: {version_arg}")
        return version_arg
    print(f"Invalid version or bump type: {version_arg}")
    print(__doc__)
    sys.exit(1)


def confirm_release(current_version: str, new_version: str, skip_prompt: bool = False) -> bool:
    """Ask user to confirm the release."""
    print("\nThis will:")
    print(f"  1. Update version from {current_version} to {new_version}")
    print("  2. Commit the changes")
    print(f"  3. Create tag v{new_version}")
    print("  4. Push commits and tag to origin")
    print("  5. Create GitHub release (if gh CLI is available)")

    if skip_prompt:
        return True

    response = input("\nProceed? [y/N]: ").strip().lower()
    return response == "y"


def perform_release(current_version: str, new_version: str) -> None:
    """Perform the actual release steps."""
    # Update version files
    print("\n📝 Updating version files...")
    update_all_versions(current_version, new_version)
    print("✓ Version files updated")

    # Stage changes
    print("\n📦 Staging changes...")
    run_command(["git", "add", str(PYPROJECT_TOML), str(INIT_PY)])

    # Commit
    print("\n💾 Committing changes...")
    run_command(["git", "commit", "-m", f"Bump version to {new_version}"])
    print("✓ Changes committed")

    # Create tag
    print("\n🏷️  Creating tag...")
    create_tag(new_version)

    # Push commits and tag
    print("\n📤 Pushing to origin...")
    run_command(["git", "push", "origin", "main"])
    run_command(["git", "push", "origin", f"v{new_version}"])
    print("✓ Pushed to origin")

    # Create GitHub release
    print("\n🚀 Creating GitHub release...")
    create_github_release(new_version)

    print(f"\n✅ Release {new_version} completed successfully!")
    print("\nNote: The release workflow will automatically create a GitHub release.")


def main() -> None:
    """Main release workflow."""
    if len(sys.argv) < MIN_ARGS_COUNT:
        print(__doc__)
        sys.exit(1)

    version_arg = sys.argv[1].lower()
    skip_prompt = "--yes" in sys.argv or "-y" in sys.argv

    current_version = get_current_version()
    new_version = determine_new_version(version_arg, current_version)

    if new_version == current_version:
        print(f"Version is already {current_version}")
        sys.exit(1)

    if not confirm_release(current_version, new_version, skip_prompt=skip_prompt):
        print("Aborted.")
        sys.exit(0)

    try:
        perform_release(current_version, new_version)
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error during release: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
