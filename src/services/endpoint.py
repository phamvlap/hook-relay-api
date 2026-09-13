from src.repositories.endpoint import EndpointRepository
from src.schemas.endpoint import (
    EndpointCreateRequest,
    EndpointCreateResponse,
    EndpointRetrieveResponse,
)
from src.utils.endpoint import validate_url


class EndpointService:
    def __init__(self, endpoint_repository: EndpointRepository):
        self.endpoint_repository = endpoint_repository

    async def create(self, data: EndpointCreateRequest) -> EndpointCreateResponse:
        url = str(data.url)

        is_valid_url = validate_url(url)
        if not is_valid_url:
            raise ValueError("Invalid URL provided.")

        endpoint = await self.endpoint_repository.create(
            name=data.name,
            url=url,
            max_retries=data.max_retries,
        )

        return EndpointCreateResponse.model_validate(endpoint)

    async def retrieve(self, endpoint_id: str) -> EndpointRetrieveResponse:
        endpoint = await self.endpoint_repository.get_by_id(id=endpoint_id)
        if not endpoint:
            raise ValueError(f"Endpoint with ID {endpoint_id} not found.")

        return EndpointRetrieveResponse.model_validate(endpoint)
