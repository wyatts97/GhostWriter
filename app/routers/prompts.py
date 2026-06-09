"""Prompts router — CRUD for LLM system prompts."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.main import templates
from app.models.prompts import Prompt

router = APIRouter(tags=["prompts"])


@router.get("/", response_class=HTMLResponse)
async def list_prompts(request: Request, session: AsyncSession = Depends(get_session)):
    """Show all prompts."""
    result = await session.execute(select(Prompt).order_by(Prompt.name))
    prompts = result.scalars().all()

    return templates.TemplateResponse(
        "prompts/list.html",
        {"request": request, "prompts": prompts, "active_page": "prompts"},
    )


@router.get("/new", response_class=HTMLResponse)
async def new_prompt_form(request: Request):
    """Show the create prompt form."""
    return templates.TemplateResponse(
        "prompts/form.html",
        {
            "request": request,
            "prompt": None,
            "action": "create",
            "active_page": "prompts",
        },
    )


@router.post("/new")
async def create_prompt(
    request: Request,
    name: str = Form(...),
    content: str = Form(...),
    model_override: str = Form(""),
    temperature: float = Form(0.7),
    max_tokens: int = Form(4000),
    session: AsyncSession = Depends(get_session),
):
    """Create a new prompt."""
    prompt = Prompt(
        name=name,
        content=content,
        model_override=model_override if model_override else None,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    session.add(prompt)
    await session.commit()
    return RedirectResponse(url="/prompts", status_code=303)


@router.get("/{prompt_id}", response_class=HTMLResponse)
async def edit_prompt_form(
    prompt_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Show the edit prompt form."""
    result = await session.execute(select(Prompt).where(Prompt.id == prompt_id))
    prompt = result.scalar_one_or_none()

    if not prompt:
        return RedirectResponse(url="/prompts", status_code=303)

    return templates.TemplateResponse(
        "prompts/form.html",
        {
            "request": request,
            "prompt": prompt,
            "action": "edit",
            "active_page": "prompts",
        },
    )


@router.post("/{prompt_id}/edit")
async def update_prompt(
    prompt_id: int,
    request: Request,
    name: str = Form(...),
    content: str = Form(...),
    model_override: str = Form(""),
    temperature: float = Form(0.7),
    max_tokens: int = Form(4000),
    session: AsyncSession = Depends(get_session),
):
    """Update an existing prompt."""
    result = await session.execute(select(Prompt).where(Prompt.id == prompt_id))
    prompt = result.scalar_one_or_none()

    if prompt:
        prompt.name = name
        prompt.content = content
        prompt.model_override = model_override if model_override else None
        prompt.temperature = temperature
        prompt.max_tokens = max_tokens
        await session.commit()

    return RedirectResponse(url="/prompts", status_code=303)


@router.post("/{prompt_id}/delete")
async def delete_prompt(
    prompt_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Delete a prompt."""
    result = await session.execute(select(Prompt).where(Prompt.id == prompt_id))
    prompt = result.scalar_one_or_none()

    if prompt:
        await session.delete(prompt)
        await session.commit()

    return RedirectResponse(url="/prompts", status_code=303)
