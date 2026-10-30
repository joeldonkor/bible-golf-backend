"""Pagination envelopes matching the client's `Paginated<T>` type."""

from collections import OrderedDict

from rest_framework.pagination import CursorPagination, PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """
    `{count, next, previous, results}` -- exactly `Paginated<T>` on the client.

    The client sends `pageSize`; the camelCase parser only touches bodies, not
    query strings, so both spellings are accepted.
    """

    page_size_query_param = "pageSize"
    max_page_size = 100

    def get_page_size(self, request):
        if "page_size" in request.query_params and "pageSize" not in request.query_params:
            request.query_params._mutable = True  # type: ignore[attr-defined]
            request.query_params["pageSize"] = request.query_params["page_size"]
            request.query_params._mutable = False  # type: ignore[attr-defined]
        return super().get_page_size(request)


class TimelinePagination(CursorPagination):
    """
    Keyset pagination for append-only feeds (game events, activity).

    OFFSET grows linearly more expensive as a table does; a cursor stays flat,
    which is what keeps event history cheap once sessions pile up.
    """

    ordering = "-created_at"
    page_size = 50
    max_page_size = 200
    page_size_query_param = "pageSize"

    def get_paginated_response(self, data):
        return Response(
            OrderedDict(
                [
                    ("count", None),  # unknowable with keyset paging
                    ("next", self.get_next_link()),
                    ("previous", self.get_previous_link()),
                    ("results", data),
                ]
            )
        )
