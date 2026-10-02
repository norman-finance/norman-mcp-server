"""An optional, request-bound company assertion for bookkeeping tools."""

import inspect
from functools import wraps
from typing import Annotated, Optional, get_type_hints
from uuid import UUID

from mcp.types import CallToolResult
from pydantic import Field

from norman_mcp.context import bind_company


ExpectedCompany = Annotated[Optional[str], Field(description=(
    "Company ID this task belongs to, from Norman Inbox context or a company lookup. "
    "Always pass it for an Inbox task and keep it unchanged across that task's calls. "
    "A different active company returns an error before reading or changing records. "
    "Keep IDs out of user-facing text. Omit only for legacy active-company behavior."
))]
COMPANY_SCOPE_DESCRIPTION = (
    "\nFor an Inbox task, pass expected_company_id from its hidden company context on every call. "
    "Never combine results from another company or continue after company_context_changed."
)


def company_scoped(fn):
    """Add an optional schema argument without changing existing positional calls."""
    # The SDK resolves annotations on this wrapper's module, which does not
    # contain the original tool's Pydantic input models. Resolve forward refs
    # in the original module before exposing the wrapped signature.
    annotations = get_type_hints(fn, include_extras=True)
    signature = inspect.signature(fn)
    signature = signature.replace(
        parameters=[
            item.replace(annotation=annotations.get(name, item.annotation))
            for name, item in signature.parameters.items()
        ],
        return_annotation=annotations.get("return", signature.return_annotation),
    )

    @wraps(fn)
    async def scoped(*args, expected_company_id=None, **kwargs):
        if expected_company_id is None:
            return await fn(*args, **kwargs)
        try:
            expected = str(UUID(expected_company_id))
        except (ValueError, TypeError, AttributeError):
            return {"error": "Invalid expected company.", "code": "invalid_company_context"}
        ctx = signature.bind(*args, **kwargs).arguments["ctx"]
        api = ctx.request_context.lifespan_context["api"]
        company = api.company_id
        if not company or expected != str(company):
            return {
                "error": "The active company changed. Refresh Norman Inbox or explicitly select the task's company before continuing. Do not combine results from different companies.",
                "code": "company_context_changed",
            }
        with bind_company(str(company)):
            result = await fn(*args, **kwargs)
        # Preserve legacy payloads; scoped calls also carry explicit provenance
        # so the model can keep consecutive results from different companies apart.
        if isinstance(result, dict):
            result = {**result, "company_context": {"company_id": str(company)}}
        elif isinstance(result, CallToolResult):
            result = result.model_copy(update={
                "meta": {**(result.meta or {}), "norman/companyId": str(company)},
            })
        return result

    parameter = inspect.Parameter(
        "expected_company_id", kind=inspect.Parameter.KEYWORD_ONLY,
        default=None, annotation=ExpectedCompany,
    )
    parameters = list(signature.parameters.values())
    index = next((i for i, item in enumerate(parameters) if item.kind == inspect.Parameter.VAR_KEYWORD), len(parameters))
    parameters.insert(index, parameter)
    scoped.__signature__ = signature.replace(parameters=parameters)
    scoped.__annotations__ = {**annotations, "expected_company_id": ExpectedCompany}
    scoped.__doc__ = (fn.__doc__ or "") + COMPANY_SCOPE_DESCRIPTION
    return scoped
