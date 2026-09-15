"""
Main FastAPI application for NFT-Gated AI Trading Bot.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
import asyncio
import logging
import time
from contextlib import asynccontextmanager

from config import get_settings
from api.routers import auth, trade, health, admin  # , twitter
from core.execution.engine import trade_engine
from core.execution.adapters import register_default_adapters

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting NFT-Gated AI Trading Bot...")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Real data mode: {settings.real_data_mode}")
    logger.info(f"NFT gate bypass: {settings.bypass_nft_gate}")
    
    # Wire exchange adapters into the execution engine. Construction dials the
    # RPC node, so run it off the event loop; an unreachable node only costs
    # that adapter, not startup.
    await asyncio.to_thread(register_default_adapters, trade_engine)
    
    yield
    
    # Shutdown
    logger.info("Shutting down NFT-Gated AI Trading Bot...")


# Create FastAPI application
app = FastAPI(
    title="NFT-Gated AI Trading Bot",
    description="A decentralized AI-driven trading bot with NFT-based access control",
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan
)
# # app.include_router(twitter.router)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add trusted host middleware for production
if not settings.debug:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"]  # Configure appropriately for production
    )


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add processing time header to responses."""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests."""
    start_time = time.time()
    
    # Log request
    logger.info(f"Request: {request.method} {request.url}")
    
    response = await call_next(request)
    
    # Log response
    process_time = time.time() - start_time
    logger.info(
        f"Response: {response.status_code} - {process_time:.4f}s"
    )
    
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error(f"Global exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.debug else "An unexpected error occurred"
        }
    )


# Include routers
app.include_router(
    health.router,
    prefix="/health",
    tags=["health"]
)

app.include_router(
    auth.router,
    prefix="/auth",
    tags=["authentication"]
)

app.include_router(
    trade.router,
    prefix="/trade",
    tags=["trading"]
)

app.include_router(
    admin.router,
    prefix="/admin",
    tags=["admin"]
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "NFT-Gated AI Trading Bot API",
        "version": "1.0.0",
        "status": "operational",
        "docs": "/docs" if settings.debug else "disabled"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level="info"
    )

