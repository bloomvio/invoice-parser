from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from invoice_parser.config import settings

_ssl = any(h in settings.database_url for h in ["supabase.co", "amazonaws.com", "rds."])
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    connect_args={"ssl": True} if _ssl else {},
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
