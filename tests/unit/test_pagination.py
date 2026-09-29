"""Unit tests for pagination parameters and response building."""

from unittest.mock import MagicMock

import pytest

from src.core.pagination import (
    PageNumberPaginationParams,
    PageNumberPaginationResponse,
)


@pytest.mark.unit
class TestPagination:
    def test_pagination_params_offset_and_limit_calculation(self):
        # Page 1, size 10 -> offset 0
        p1 = PageNumberPaginationParams(page=1, page_size=10)
        assert p1.offset == 0
        assert p1.limit == 10

        # Page 3, size 25 -> offset 50
        p3 = PageNumberPaginationParams(page=3, page_size=25)
        assert p3.offset == 50
        assert p3.limit == 25

    def test_pagination_response_first_page_has_next_no_previous(self):
        mock_request = MagicMock()
        mock_request.query_params = {"status": "active"}
        mock_request.url.replace_query_params.side_effect = lambda **kwargs: (
            f"http://testserver/items?page={kwargs['page']}&page_size={kwargs['page_size']}"
        )

        response = PageNumberPaginationResponse.build(
            total=30,
            page=1,
            page_size=10,
            items=["item1", "item2"],
            request=mock_request,
        )

        assert response.total == 30
        assert response.previous is None
        assert response.next is not None
        assert "page=2" in response.next
        assert response.items == ["item1", "item2"]

    def test_pagination_response_last_page_has_previous_no_next(self):
        mock_request = MagicMock()
        mock_request.query_params = {}
        mock_request.url.replace_query_params.side_effect = lambda **kwargs: (
            f"http://testserver/items?page={kwargs['page']}&page_size={kwargs['page_size']}"
        )

        response = PageNumberPaginationResponse.build(
            total=30,
            page=3,
            page_size=10,
            items=["item21", "item22"],
            request=mock_request,
        )

        assert response.total == 30
        assert response.previous is not None
        assert "page=2" in response.previous
        assert response.next is None

    def test_pagination_response_middle_page_has_both_links(self):
        mock_request = MagicMock()
        mock_request.query_params = {}
        mock_request.url.replace_query_params.side_effect = lambda **kwargs: (
            f"http://testserver/items?page={kwargs['page']}&page_size={kwargs['page_size']}"
        )

        response = PageNumberPaginationResponse.build(
            total=50,
            page=3,
            page_size=10,
            items=["item25"],
            request=mock_request,
        )

        assert response.previous is not None
        assert "page=2" in response.previous
        assert response.next is not None
        assert "page=4" in response.next
