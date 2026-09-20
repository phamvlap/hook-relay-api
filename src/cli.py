import argparse
import asyncio

from src.models.api_key import APIKeyEnvironment
from src.schemas.api_key import APIKeyCreateResponse
from src.schemas.owner import OwnerCreateResponse
from src.services.api_key import APIKeyService
from src.services.owner import OwnerService


def _print_owner(owner: OwnerCreateResponse) -> None:
    print("Owner created:")
    print(f"  Owner ID: {owner.id}")
    print(f"  Created At: {owner.created_at}")


def _print_api_key(api_key: APIKeyCreateResponse) -> None:
    print("API Key created:")
    print(f"  Key ID: {api_key.key_id}")

    box_line = "-" * (len(api_key.api_key) + 4)
    print(f"\n{box_line}\n| {api_key.api_key} |\n{box_line}\n")
    print("*Please copy and store this API key securely. It will not be shown again.")


async def cmd_create_owner(args: argparse.Namespace) -> None:
    owner_service = OwnerService()
    api_key_service = APIKeyService()

    owner = await owner_service.create()
    api_key = await api_key_service.create(
        owner_id=str(owner.id),
        name=args.name,
        environment=APIKeyEnvironment(args.env),
    )
    _print_owner(owner)
    _print_api_key(api_key)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hook Relay API CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Create owner command
    create_owner_parser = subparsers.add_parser(
        "create-owner",
        help="Create a new owner and generate an API key",
    )
    create_owner_parser.add_argument("--name", required=True, help="Name for the API key")
    create_owner_parser.add_argument(
        "--env",
        choices=["test", "live"],
        default="test",
        help="Environment for the API key (default: test)",
    )
    create_owner_parser.set_defaults(func=cmd_create_owner)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        return

    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
