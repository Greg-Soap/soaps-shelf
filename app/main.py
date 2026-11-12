from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from library.books import (
    add_book,
    count_by_status,
    delete_book,
    get_book,
    list_books,
    reenrich_book,
    update_book_status,
)
from library.categories import (
    create_category,
    delete_category,
    get_category,
    list_book_categories,
    list_categories,
    set_book_categories,
    update_category,
)
from library.compiler.service import (
    compile_source_url,
    ensure_compile_worker,
    get_job,
    list_adapters,
    list_jobs,
)
from library.db import EPUB_DIR, init_db
from library.llm_enrich import available_llm_provider, load_dotenv

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

app = FastAPI(title="Soap's Shelf", version="0.5.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

STATUS_LABELS = {
    "reading": "Reading",
    "want_to_read": "Want to read",
    "not_finished": "Not finished",
    "read": "Read",
    "dropped": "Dropped",
    "other": "Other",
}


class AddBookBody(BaseModel):
    title: str = Field(min_length=1)
    status: str = "read"
    source: str = "api"
    enrich: bool = True
    use_llm: bool = True


class ReenrichBody(BaseModel):
    title: Optional[str] = None
    use_llm: bool = True


class StatusBody(BaseModel):
    status: str = Field(min_length=1)


class CategoryBody(BaseModel):
    name: str = Field(min_length=1)
    description: Optional[str] = None
    color: Optional[str] = None
    slug: Optional[str] = None


class CategoryUpdateBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    slug: Optional[str] = None


class BookCategoriesBody(BaseModel):
    category_ids: List[int] = Field(default_factory=list)


class CompileBody(BaseModel):
    url: str = Field(min_length=8)
    status: str = "want_to_read"
    chapter_from: int = 0
    chapter_to: Optional[int] = None
    limit: Optional[int] = None
    delay: float = 0.55


@app.on_event("startup")
def on_startup() -> None:
    load_dotenv()
    init_db()
    ensure_compile_worker()


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "service": "soaps-shelf"}


@app.get("/", response_class=HTMLResponse)
def gallery(
    request: Request,
    status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    review: Optional[int] = Query(default=None),
) -> Any:
    status_value = status.strip() if status else None
    if status_value == "":
        status_value = None
    query_value = q.strip() if q else None
    if query_value == "":
        query_value = None
    needs_review = True if review == 1 else None

    books = list_books(
        status=status_value,
        search=query_value,
        needs_review=needs_review,
    )
    counts = count_by_status()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "books": books,
            "counts": counts,
            "current_status": status_value or "",
            "query": query_value or "",
            "review": review,
            "total": sum(counts.values()),
            "status_labels": STATUS_LABELS,
            "llm_ready": available_llm_provider() is not None,
            "llm_provider": available_llm_provider() or "",
        },
    )


@app.get("/compiler", response_class=HTMLResponse)
def compiler_page(request: Request) -> Any:
    return templates.TemplateResponse(
        "compiler.html",
        {
            "request": request,
            "adapters": list_adapters(),
            "jobs": list_jobs(20),
            "status_labels": STATUS_LABELS,
            "message": None,
            "error": None,
        },
    )


@app.post("/compiler", response_class=HTMLResponse)
def compiler_form(
    request: Request,
    url: str = Form(...),
    status: str = Form("want_to_read"),
    limit: int = Form(0),
) -> Any:
    error = None
    message = None
    try:
        result = compile_source_url(
            url.strip(),
            status=status,
            limit=limit if limit > 0 else None,
        )
        job = result.get("job") or {}
        message = (
            f"Queued job #{result.get('job_id') or job.get('id')} · "
            f"{job.get('adapter') or 'webtoepub'} · refresh for status"
        )
    except Exception as err:
        error = str(err)

    return templates.TemplateResponse(
        "compiler.html",
        {
            "request": request,
            "adapters": list_adapters(),
            "jobs": list_jobs(20),
            "status_labels": STATUS_LABELS,
            "message": message,
            "error": error,
            "url": url,
        },
    )


@app.get("/categories", response_class=HTMLResponse)
def categories_page(request: Request) -> Any:
    return templates.TemplateResponse(
        "categories.html",
        {
            "request": request,
            "categories": list_categories(),
            "message": None,
            "error": None,
        },
    )


@app.post("/categories")
def categories_create_form(
    name: str = Form(...),
    description: str = Form(""),
    color: str = Form(""),
) -> RedirectResponse:
    try:
        create_category(name, description=description or None, color=color or None)
    except ValueError:
        pass
    return RedirectResponse(url="/categories", status_code=303)


@app.post("/categories/{category_id}/delete")
def categories_delete_form(category_id: int) -> RedirectResponse:
    delete_category(category_id)
    return RedirectResponse(url="/categories", status_code=303)


@app.get("/books/{book_id}", response_class=HTMLResponse)
def book_detail(request: Request, book_id: int) -> Any:
    book = get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return templates.TemplateResponse(
        "detail.html",
        {
            "request": request,
            "book": book,
            "status_labels": STATUS_LABELS,
            "llm_ready": available_llm_provider() is not None,
            "categories": list_book_categories(book_id),
        },
    )


@app.post("/books/add")
def add_book_form(
    title: str = Form(...),
    status: str = Form("want_to_read"),
    use_llm: Optional[str] = Form(None),
) -> RedirectResponse:
    add_book(
        title,
        status=status,
        source="ui",
        enrich=True,
        use_llm=bool(use_llm),
    )
    return RedirectResponse(url="/", status_code=303)


@app.post("/books/{book_id}/delete")
def delete_book_form(book_id: int) -> RedirectResponse:
    delete_book(book_id)
    return RedirectResponse(url="/", status_code=303)


@app.get("/api/books")
def api_list_books(
    status: Optional[str] = None,
    q: Optional[str] = None,
) -> List[Dict[str, Any]]:
    return list_books(status=status, search=q)


@app.post("/api/books")
def api_add_book(body: AddBookBody) -> Dict[str, Any]:
    try:
        return add_book(
            body.title,
            status=body.status,
            source=body.source,
            enrich=body.enrich,
            use_llm=body.use_llm,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


@app.post("/api/books/{book_id}/reenrich")
def api_reenrich_book(book_id: int, body: ReenrichBody) -> Dict[str, Any]:
    try:
        book = reenrich_book(book_id, title=body.title, use_llm=body.use_llm)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


@app.post("/api/books/{book_id}/status")
def api_update_status(book_id: int, body: StatusBody) -> Dict[str, Any]:
    try:
        book = update_book_status(book_id, body.status)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


@app.post("/api/books/{book_id}/categories")
def api_set_book_categories(book_id: int, body: BookCategoriesBody) -> List[Dict[str, Any]]:
    try:
        return set_book_categories(book_id, body.category_ids)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


@app.get("/api/books/{book_id}/categories")
def api_list_book_categories(book_id: int) -> List[Dict[str, Any]]:
    if not get_book(book_id):
        raise HTTPException(status_code=404, detail="Book not found")
    return list_book_categories(book_id)


@app.delete("/api/books/{book_id}")
def api_delete_book(book_id: int) -> Dict[str, Any]:
    if not delete_book(book_id):
        raise HTTPException(status_code=404, detail="Book not found")
    return {"ok": True, "id": book_id}


@app.get("/api/books/{book_id}")
def api_get_book(book_id: int) -> Dict[str, Any]:
    book = get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    book["categories"] = list_book_categories(book_id)
    return book


@app.get("/api/categories")
def api_list_categories() -> List[Dict[str, Any]]:
    return list_categories()


@app.post("/api/categories")
def api_create_category(body: CategoryBody) -> Dict[str, Any]:
    try:
        return create_category(
            body.name,
            description=body.description,
            color=body.color,
            slug=body.slug,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


@app.get("/api/categories/{category_id}")
def api_get_category(category_id: int) -> Dict[str, Any]:
    category = get_category(category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return category


@app.patch("/api/categories/{category_id}")
def api_update_category(category_id: int, body: CategoryUpdateBody) -> Dict[str, Any]:
    try:
        category = update_category(
            category_id,
            name=body.name,
            description=body.description,
            color=body.color,
            slug=body.slug,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return category


@app.delete("/api/categories/{category_id}")
def api_delete_category(category_id: int) -> Dict[str, Any]:
    if not delete_category(category_id):
        raise HTTPException(status_code=404, detail="Category not found")
    return {"ok": True, "id": category_id}


@app.get("/api/compile/adapters")
def api_compile_adapters() -> List[Dict[str, str]]:
    return list_adapters()


@app.get("/api/compile/jobs")
def api_compile_jobs(limit: int = 30) -> List[Dict[str, Any]]:
    return list_jobs(limit)


@app.get("/api/compile/jobs/{job_id}")
def api_compile_job(job_id: int) -> Dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/compile")
def api_compile(body: CompileBody) -> Dict[str, Any]:
    try:
        return compile_source_url(
            body.url,
            status=body.status,
            chapter_from=body.chapter_from,
            chapter_to=body.chapter_to,
            limit=body.limit,
            delay=body.delay,
            sync=False,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except Exception as err:
        raise HTTPException(status_code=502, detail=str(err)) from err


@app.get("/epubs/{filename}")
def download_epub(filename: str) -> FileResponse:
    safe = Path(filename).name
    path = EPUB_DIR / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="EPUB not found")
    return FileResponse(
        path,
        media_type="application/epub+zip",
        filename=safe,
    )
