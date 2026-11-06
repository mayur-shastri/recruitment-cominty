"""Job and pipeline-stage tools for the Recruiter Agent (M2.1: reads + writes)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from services.harly import HarlyError, get_harly_client

_JOB_STATUSES = ("draft", "open", "closed")
_EMPLOYMENT_TYPES = ("full_time", "part_time", "contract", "internship")
_WORKPLACE_TYPES = ("remote", "hybrid", "onsite")
_SALARY_PERIODS = ("annual", "monthly")
_STAGE_KINDS = (
    "applied",
    "screening",
    "interview",
    "offer",
    "hired",
    "rejected",
    "withdrawn",
    "custom",
)


def _require_enum(value: str | None, allowed: tuple[str, ...], field: str) -> None:
    if value is not None and value not in allowed:
        raise ToolError(f"unknown {field} {value!r}: expected one of {', '.join(allowed)}")


def _require_non_blank(value: str | None, field: str) -> None:
    if value is not None and not value.strip():
        raise ToolError(f"{field} must not be blank.")


def _require_confirmation(confirmation: str, tool: str) -> None:
    if not confirmation or not confirmation.strip():
        raise ToolError(f"{tool} needs confirmation quoting the Hiring Manager's instruction.")


async def list_jobs(
    status: str | None = None, limit: int = 20, cursor: str | None = None
) -> dict[str, Any]:
    """List Harly jobs with cursor pagination (see tool description)."""
    if status is not None and status not in _JOB_STATUSES:
        raise ToolError(f"unknown status {status!r}: expected one of {', '.join(_JOB_STATUSES)}")
    if not 1 <= limit <= 100:
        raise ToolError(f"limit must be 1-100, got {limit}")
    client = get_harly_client()
    try:
        return await client.list_jobs(status=status, limit=limit, cursor=cursor)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def get_job(job_id: str) -> dict[str, Any]:
    """Get full details of one Harly job (see tool description)."""
    client = get_harly_client()
    try:
        return await client.get_job(job_id)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def list_job_stages(job_id: str) -> dict[str, Any]:
    """List a job's ordered pipeline stages (see tool description)."""
    client = get_harly_client()
    try:
        return await client.list_job_stages(job_id)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def create_job(
    title: str,
    description: str,
    employment_type: str,
    workplace_type: str,
    department: str | None = None,
    location: str | None = None,
    requirements: str | None = None,
    benefits: str | None = None,
    keywords: list[str] | None = None,
    salary_min: int | None = None,
    salary_max: int | None = None,
    currency: str | None = None,
    salary_period: str | None = None,
) -> dict[str, Any]:
    """Create a Harly job as DRAFT (see tool description)."""
    _require_non_blank(title, "title")
    _require_non_blank(description, "description")
    _require_enum(employment_type, _EMPLOYMENT_TYPES, "employment_type")
    _require_enum(workplace_type, _WORKPLACE_TYPES, "workplace_type")
    _require_enum(salary_period, _SALARY_PERIODS, "salary_period")
    if keywords is not None and len(keywords) > 50:
        raise ToolError(f"keywords accepts at most 50 items, got {len(keywords)}")
    client = get_harly_client()
    try:
        return await client.create_job(
            title=title,
            description=description,
            employment_type=employment_type,
            workplace_type=workplace_type,
            department=department,
            location=location,
            requirements=requirements,
            benefits=benefits,
            keywords=keywords,
            salary_min=salary_min,
            salary_max=salary_max,
            currency=currency,
            salary_period=salary_period,
        )
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def update_job(
    job_id: str,
    confirmation: str,
    title: str | None = None,
    description: str | None = None,
    department: str | None = None,
    location: str | None = None,
    employment_type: str | None = None,
    workplace_type: str | None = None,
    requirements: str | None = None,
    benefits: str | None = None,
    keywords: list[str] | None = None,
    salary_min: int | None = None,
    salary_max: int | None = None,
    currency: str | None = None,
    salary_period: str | None = None,
) -> dict[str, Any]:
    """Edit fields of a Harly job (see tool description). Status can't be changed."""
    _require_confirmation(confirmation, "update_job")
    _require_non_blank(title, "title")
    _require_non_blank(description, "description")
    _require_enum(employment_type, _EMPLOYMENT_TYPES, "employment_type")
    _require_enum(workplace_type, _WORKPLACE_TYPES, "workplace_type")
    _require_enum(salary_period, _SALARY_PERIODS, "salary_period")
    if keywords is not None and len(keywords) > 50:
        raise ToolError(f"keywords accepts at most 50 items, got {len(keywords)}")
    fields = {
        "title": title,
        "description": description,
        "department": department,
        "location": location,
        "employment_type": employment_type,
        "workplace_type": workplace_type,
        "requirements": requirements,
        "benefits": benefits,
        "keywords": keywords,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "currency": currency,
        "salary_period": salary_period,
    }
    provided = {key: value for key, value in fields.items() if value is not None}
    if not provided:
        raise ToolError("update_job needs at least one field to change.")
    client = get_harly_client()
    try:
        return await client.update_job(job_id, **provided)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def publish_job(job_id: str, confirmation: str) -> dict[str, Any]:
    """Publish a draft Harly job (see tool description)."""
    _require_confirmation(confirmation, "publish_job")
    client = get_harly_client()
    try:
        return await client.publish_job(job_id)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def close_job(job_id: str, confirmation: str) -> dict[str, Any]:
    """Close a Harly job (see tool description)."""
    _require_confirmation(confirmation, "close_job")
    client = get_harly_client()
    try:
        return await client.close_job(job_id)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def create_job_stage(
    job_id: str,
    name: str,
    confirmation: str,
    kind: str | None = None,
    color: str | None = None,
    position: int | None = None,
) -> dict[str, Any]:
    """Add a stage to a Harly job's pipeline (see tool description)."""
    _require_confirmation(confirmation, "create_job_stage")
    _require_non_blank(name, "name")
    if len(name.strip()) > 120:
        raise ToolError(f"stage name accepts at most 120 characters, got {len(name.strip())}")
    _require_enum(kind, _STAGE_KINDS, "kind")
    if position is not None and position < 0:
        raise ToolError(f"position must be 0 or more, got {position}")
    kwargs: dict[str, Any] = {"name": name}
    if kind is not None:
        kwargs["kind"] = kind
    if color is not None:
        kwargs["color"] = color
    if position is not None:
        kwargs["position"] = position
    client = get_harly_client()
    try:
        return await client.create_job_stage(job_id, **kwargs)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def update_job_stage(
    job_id: str,
    stage_id: str,
    confirmation: str,
    name: str | None = None,
    color: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """Edit a Harly job's pipeline stage (see tool description)."""
    _require_confirmation(confirmation, "update_job_stage")
    _require_non_blank(name, "name")
    _require_enum(kind, _STAGE_KINDS, "kind")
    provided = {"name": name, "color": color, "kind": kind}
    fields = {key: value for key, value in provided.items() if value is not None}
    if not fields:
        raise ToolError("update_job_stage needs at least one field to change.")
    client = get_harly_client()
    try:
        return await client.update_job_stage(job_id, stage_id, **fields)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def delete_job_stage(job_id: str, stage_id: str, confirmation: str) -> dict[str, Any]:
    """Permanently delete a Harly job's pipeline stage (see tool description)."""
    _require_confirmation(confirmation, "delete_job_stage")
    client = get_harly_client()
    try:
        return await client.delete_job_stage(job_id, stage_id)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def archive_job_stage(
    job_id: str, stage_id: str, confirmation: str, merge_into_stage_id: str | None = None
) -> dict[str, Any]:
    """Archive a Harly job's pipeline stage (see tool description)."""
    _require_confirmation(confirmation, "archive_job_stage")
    kwargs: dict[str, Any] = {}
    if merge_into_stage_id is not None:
        kwargs["merge_into_stage_id"] = merge_into_stage_id
    client = get_harly_client()
    try:
        return await client.archive_job_stage(job_id, stage_id, **kwargs)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def reorder_job_stages(
    job_id: str, stage_ids: list[str], confirmation: str
) -> dict[str, Any]:
    """Reorder a Harly job's pipeline stages (see tool description)."""
    _require_confirmation(confirmation, "reorder_job_stages")
    if not stage_ids:
        raise ToolError("reorder_job_stages needs at least one stage ID.")
    if len(stage_ids) > 100:
        raise ToolError(f"reorder_job_stages accepts at most 100 stage IDs, got {len(stage_ids)}")
    client = get_harly_client()
    try:
        return await client.reorder_job_stages(job_id, stage_ids)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


def register_tools(mcp: Any) -> None:
    """Register job tools on an MCPServer (or compatible stub in tests)."""
    mcp.tool(
        name="list_jobs",
        description=(
            "List jobs in the Harly ATS, optionally filtered by status "
            "(draft, open, closed). Results are cursor-paginated: pass the "
            "returned next_cursor to fetch the next page while has_more is true. "
            "Use to report the hiring pipeline or find a job's ID."
        ),
    )(list_jobs)
    mcp.tool(
        name="get_job",
        description=(
            "Get full details of one Harly job by ID: title, description, "
            "requirements, location, employment/workplace type, salary, keywords, "
            "status, timestamps. Use before describing a role or acting on it."
        ),
    )(get_job)
    mcp.tool(
        name="list_job_stages",
        description=(
            "List the ordered pipeline stages of a Harly job (id, name, order, "
            "kind such as applied/screening/interview/offer/hired). A new job "
            "starts with Harly's default stages — show them to the Hiring Manager "
            "and ask whether to keep, rename, add, remove, or reorder them before "
            "publishing. Also use to resolve the stage ID a later application "
            "move needs."
        ),
    )(list_job_stages)
    mcp.tool(
        name="create_job",
        description=(
            "Create a new job in the Harly ATS as a DRAFT (always draft; "
            "invisible until published). Required: title, description, "
            "employment_type (one of: full_time, part_time, contract, internship), "
            "workplace_type (one of: remote, hybrid, onsite). Optional: department, "
            "location, requirements, benefits, keywords (up to 50 strings), "
            "salary_min and salary_max (integers 0 or more), currency (max 8 chars, "
            "e.g. USD), salary_period (annual or monthly). Use only after the Hiring "
            "Manager approves the draft description. Workflow: right after creating, "
            "call list_job_stages, show the starting pipeline to the Hiring Manager, "
            "ask whether they want to add, rename, remove, or reorder stages, apply "
            "any changes with the stage tools, and only then publish. Also ask for "
            "the interview plan (rounds, date windows, interviewer pools) and save "
            "it with save_interview_config on the DB connection — if the Hiring "
            "Manager defers, ask again at the first move-forward. Returns the "
            "created job with id, slug, and status."
        ),
    )(create_job)
    mcp.tool(
        name="update_job",
        description=(
            "Edit fields of an existing Harly job (partial update; only provided "
            "fields change, at least one required). Editable: title, description, "
            "department, location, employment_type, workplace_type, requirements, "
            "benefits, keywords, salary_min/max, currency, salary_period (same values "
            "as create_job). Cannot change status — publishing and closing have "
            "their own tools. Requires confirmation: quote the Hiring Manager's "
            "instruction to edit."
        ),
    )(update_job)
    mcp.tool(
        name="publish_job",
        description=(
            "Publish a draft Harly job (status becomes open). Requires "
            "confirmation: quote the Hiring Manager's publish instruction. Use "
            "only after explicit approval to publish AND after the Hiring Manager "
            "has confirmed the pipeline stages (offered at creation time via "
            "list_job_stages; customized with the stage tools if asked). Returns "
            "the published job."
        ),
    )(publish_job)
    mcp.tool(
        name="close_job",
        description=(
            "Close a Harly job (status becomes closed). Requires confirmation: "
            "quote the Hiring Manager's instruction. Use when hiring for the role "
            "ends or the role is cancelled. Returns the closed job."
        ),
    )(close_job)
    mcp.tool(
        name="create_job_stage",
        description=(
            "Add a stage to a Harly job's hiring pipeline. Required: job_id, name "
            "(1-120 chars), confirmation quoting the Hiring Manager's instruction. "
            "Optional: kind (one of: applied, screening, interview, offer, hired, "
            "rejected, withdrawn, custom — use custom for anything outside the "
            "standard set), color (short label, e.g. a color name), position "
            "(0-based slot; appended at the end when omitted). Part of the "
            "creation-time workflow: list stages, ask the Hiring Manager, apply "
            "changes, then publish. Returns the created stage with its id."
        ),
    )(create_job_stage)
    mcp.tool(
        name="update_job_stage",
        description=(
            "Rename or reconfigure one stage of a Harly job's pipeline (partial "
            "update; at least one of name, color, kind required). Same kind values "
            "as create_job_stage. Requires confirmation: quote the Hiring Manager's "
            "instruction. Returns the updated stage."
        ),
    )(update_job_stage)
    mcp.tool(
        name="delete_job_stage",
        description=(
            "Permanently delete one stage of a Harly job's pipeline. Prefer "
            "archive_job_stage when applications may already sit in the stage. "
            "Requires confirmation: quote the Hiring Manager's instruction. "
            "Returns the deleted stage."
        ),
    )(delete_job_stage)
    mcp.tool(
        name="archive_job_stage",
        description=(
            "Archive (soft-remove) one stage of a Harly job's pipeline. Optional "
            "merge_into_stage_id moves the archived stage's applications into "
            "another stage instead of leaving them behind. Requires confirmation: "
            "quote the Hiring Manager's instruction. Returns the archived stage."
        ),
    )(archive_job_stage)
    mcp.tool(
        name="reorder_job_stages",
        description=(
            "Reorder a Harly job's pipeline: pass the full ordered list of stage "
            "IDs (1-100, from list_job_stages) in the desired order. Requires "
            "confirmation: quote the Hiring Manager's instruction. Returns the "
            "job's updated pipeline."
        ),
    )(reorder_job_stages)
