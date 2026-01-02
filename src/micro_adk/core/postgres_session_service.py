"""PostgreSQL Session Service with tool invocation logging.

This module extends the ADK DatabaseSessionService to provide:
- Postgres-optimized storage for sessions and events
- Additional tool_invocations table for tracking tool calls
- Async support with asyncpg driver
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from typing_extensions import override

from google.adk.events.event import Event
from google.adk.sessions.base_session_service import (
    BaseSessionService,
    GetSessionConfig,
    ListSessionsResponse,
)
from google.adk.sessions.session import Session

logger = logging.getLogger(__name__)


# ============================================================================
# SQLAlchemy Models
# ============================================================================

class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


class StorageSession(Base):
    """Sessions table - stores conversation sessions."""
    
    __tablename__ = "sessions"
    
    app_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    
    state: Mapped[dict] = mapped_column(JSONB, default=dict)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    
    # Relationships
    events: Mapped[list["StorageEvent"]] = relationship(
        "StorageEvent",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="StorageEvent.timestamp",
    )
    
    tool_invocations: Mapped[list["StorageToolInvocation"]] = relationship(
        "StorageToolInvocation",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="StorageToolInvocation.created_at",
    )
    
    def to_session(
        self,
        events: Optional[list[Event]] = None,
    ) -> Session:
        """Convert to ADK Session object."""
        return Session(
            app_name=self.app_name,
            user_id=self.user_id,
            id=self.id,
            state=self.state or {},
            events=events or [],
            last_update_time=self.updated_at.timestamp() if self.updated_at else 0.0,
        )


class StorageEvent(Base):
    """Events table - stores conversation events (messages, tool calls, etc.)."""
    
    __tablename__ = "events"
    
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    app_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    
    invocation_id: Mapped[str] = mapped_column(String(255), index=True)
    author: Mapped[str] = mapped_column(String(255))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    
    # Store full event data as JSON
    event_data: Mapped[dict] = mapped_column(JSONB, nullable=True)
    
    # Relationship
    session: Mapped["StorageSession"] = relationship(
        "StorageSession",
        back_populates="events",
    )
    
    __table_args__ = (
        ForeignKeyConstraint(
            ["app_name", "user_id", "session_id"],
            ["sessions.app_name", "sessions.user_id", "sessions.id"],
            ondelete="CASCADE",
        ),
        Index("ix_events_session", "app_name", "user_id", "session_id"),
        Index("ix_events_timestamp", "timestamp"),
    )
    
    @classmethod
    def from_event(cls, session: Session, event: Event) -> "StorageEvent":
        """Create from ADK Event."""
        return cls(
            id=event.id,
            app_name=session.app_name,
            user_id=session.user_id,
            session_id=session.id,
            invocation_id=event.invocation_id,
            author=event.author,
            timestamp=datetime.fromtimestamp(event.timestamp, tz=timezone.utc),
            event_data=event.model_dump(exclude_none=True, mode="json"),
        )
    
    def to_event(self) -> Event:
        """Convert to ADK Event."""
        return Event.model_validate(self.event_data)


class StorageToolInvocation(Base):
    """Tool invocations table - tracks all tool calls for observability."""
    
    __tablename__ = "tool_invocations"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    app_name: Mapped[str] = mapped_column(String(255))
    user_id: Mapped[str] = mapped_column(String(255))
    session_id: Mapped[str] = mapped_column(String(255))
    
    tool_id: Mapped[str] = mapped_column(String(255), index=True)
    tool_name: Mapped[str] = mapped_column(String(255))
    invocation_id: Mapped[str] = mapped_column(String(255), index=True)
    
    # Column names must match the database schema
    args: Mapped[dict] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    status: Mapped[str] = mapped_column(
        String(50),
        default="pending",
    )  # pending, success, error
    
    duration_ms: Mapped[Optional[int]] = mapped_column(nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Relationship
    session: Mapped["StorageSession"] = relationship(
        "StorageSession",
        back_populates="tool_invocations",
    )
    
    __table_args__ = (
        ForeignKeyConstraint(
            ["app_name", "user_id", "session_id"],
            ["sessions.app_name", "sessions.user_id", "sessions.id"],
            ondelete="CASCADE",
        ),
        Index("ix_tool_invocations_session", "app_name", "user_id", "session_id"),
        Index("ix_tool_invocations_created", "created_at"),
    )


# ============================================================================
# Session Service Implementation
# ============================================================================

class PostgresSessionService(BaseSessionService):
    """PostgreSQL-backed session service with tool invocation logging.
    
    This service extends the base ADK session service to:
    - Store sessions and events in PostgreSQL using JSONB
    - Log all tool invocations for observability
    - Support async operations with connection pooling
    
    Example:
        ```python
        service = PostgresSessionService(
            db_url="postgresql+asyncpg://user:pass@localhost:5432/mydb"
        )
        await service.initialize()
        
        session = await service.create_session(
            app_name="my_app",
            user_id="user_123",
        )
        ```
    """
    
    def __init__(
        self,
        db_url: str,
        *,
        pool_size: int = 5,
        max_overflow: int = 10,
        echo: bool = False,
    ):
        """Initialize the PostgreSQL session service.
        
        Args:
            db_url: PostgreSQL connection URL (must use asyncpg driver).
            pool_size: Connection pool size.
            max_overflow: Max overflow connections beyond pool_size.
            echo: Whether to echo SQL statements (for debugging).
        """
        self._db_url = db_url
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._echo = echo
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize the database connection and create tables."""
        if self._initialized:
            return
        
        self._engine = create_async_engine(
            self._db_url,
            pool_size=self._pool_size,
            max_overflow=self._max_overflow,
            echo=self._echo,
        )
        
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            expire_on_commit=False,
        )
        
        # Create tables
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        self._initialized = True
        logger.info("PostgresSessionService initialized successfully")
    
    async def close(self) -> None:
        """Close the database connection."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            self._initialized = False
    
    def _ensure_initialized(self) -> async_sessionmaker[AsyncSession]:
        """Ensure service is initialized and return session factory."""
        if not self._initialized or self._session_factory is None:
            raise RuntimeError(
                "PostgresSessionService not initialized. Call initialize() first."
            )
        return self._session_factory
    
    @override
    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        """Create a new session."""
        factory = self._ensure_initialized()
        
        session_id = session_id or str(uuid.uuid4())
        
        async with factory() as db:
            # Check for existing session
            existing = await db.get(
                StorageSession,
                (app_name, user_id, session_id),
            )
            if existing:
                raise ValueError(f"Session already exists: {session_id}")
            
            # Create new session
            storage_session = StorageSession(
                app_name=app_name,
                user_id=user_id,
                id=session_id,
                state=state or {},
            )
            
            db.add(storage_session)
            await db.commit()
            await db.refresh(storage_session)
            
            logger.info(
                f"Created session {session_id}",
                extra={"app_name": app_name, "user_id": user_id},
            )
            
            return storage_session.to_session()
    
    @override
    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        """Get a session by ID."""
        factory = self._ensure_initialized()
        
        async with factory() as db:
            storage_session = await db.get(
                StorageSession,
                (app_name, user_id, session_id),
            )
            
            if storage_session is None:
                return None
            
            # Build events query
            stmt = (
                select(StorageEvent)
                .where(StorageEvent.app_name == app_name)
                .where(StorageEvent.user_id == user_id)
                .where(StorageEvent.session_id == session_id)
                .order_by(StorageEvent.timestamp.desc())
            )
            
            # Apply config filters
            if config:
                if config.after_timestamp:
                    after_dt = datetime.fromtimestamp(
                        config.after_timestamp,
                        tz=timezone.utc,
                    )
                    stmt = stmt.where(StorageEvent.timestamp >= after_dt)
                
                if config.num_recent_events:
                    stmt = stmt.limit(config.num_recent_events)
            
            result = await db.execute(stmt)
            storage_events = result.scalars().all()
            
            # Convert to ADK events (reverse to chronological order)
            events = [e.to_event() for e in reversed(storage_events)]
            
            return storage_session.to_session(events=events)
    
    @override
    async def list_sessions(
        self,
        *,
        app_name: str,
        user_id: Optional[str] = None,
    ) -> ListSessionsResponse:
        """List sessions for an app."""
        factory = self._ensure_initialized()
        
        async with factory() as db:
            stmt = select(StorageSession).where(
                StorageSession.app_name == app_name
            )
            
            if user_id:
                stmt = stmt.where(StorageSession.user_id == user_id)
            
            result = await db.execute(stmt)
            storage_sessions = result.scalars().all()
            
            sessions = [s.to_session() for s in storage_sessions]
            return ListSessionsResponse(sessions=sessions)
    
    @override
    async def delete_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> None:
        """Delete a session."""
        factory = self._ensure_initialized()
        
        async with factory() as db:
            storage_session = await db.get(
                StorageSession,
                (app_name, user_id, session_id),
            )
            
            if storage_session:
                await db.delete(storage_session)
                await db.commit()
                
                logger.info(
                    f"Deleted session {session_id}",
                    extra={"app_name": app_name, "user_id": user_id},
                )
    
    @override
    async def append_event(self, session: Session, event: Event) -> Event:
        """Append an event to a session."""
        # Call parent to handle state updates
        event = await super().append_event(session, event)
        
        if event.partial:
            return event
        
        factory = self._ensure_initialized()
        
        async with factory() as db:
            # Create storage event
            storage_event = StorageEvent.from_event(session, event)
            db.add(storage_event)
            
            # Update session state and timestamp
            storage_session = await db.get(
                StorageSession,
                (session.app_name, session.user_id, session.id),
            )
            
            if storage_session:
                storage_session.state = session.state
                storage_session.updated_at = datetime.now(timezone.utc)
            
            await db.commit()
        
        return event
    
    # ========================================================================
    # Tool Invocation Logging
    # ========================================================================
    
    async def log_tool_invocation_start(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        tool_id: str,
        tool_name: str,
        invocation_id: str,
        args: dict[str, Any],
    ) -> uuid.UUID:
        """Log the start of a tool invocation.
        
        Returns:
            The ID of the created tool invocation record.
        """
        factory = self._ensure_initialized()
        
        async with factory() as db:
            record = StorageToolInvocation(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
                tool_id=tool_id,
                tool_name=tool_name,
                invocation_id=invocation_id,
                args=args,
                status="pending",
            )
            
            db.add(record)
            await db.commit()
            await db.refresh(record)
            
            logger.debug(
                f"Logged tool invocation start: {record.id}",
                extra={"tool_id": tool_id, "invocation_id": invocation_id},
            )
            
            return record.id
    
    async def log_tool_invocation_end(
        self,
        *,
        record_id: uuid.UUID,
        result: Optional[Any] = None,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        """Log the completion of a tool invocation."""
        factory = self._ensure_initialized()
        
        async with factory() as db:
            record = await db.get(StorageToolInvocation, record_id)
            
            if record:
                record.status = "error" if error else "success"
                record.result = result if isinstance(result, dict) else {"result": result}
                record.error = error
                record.duration_ms = duration_ms
                record.completed_at = datetime.now(timezone.utc)
                
                await db.commit()
                
                logger.debug(
                    f"Logged tool invocation end: {record_id}",
                    extra={"status": record.status, "duration_ms": duration_ms},
                )
    
    async def get_tool_invocations(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get tool invocations for a session."""
        factory = self._ensure_initialized()
        
        async with factory() as db:
            stmt = (
                select(StorageToolInvocation)
                .where(StorageToolInvocation.app_name == app_name)
                .where(StorageToolInvocation.user_id == user_id)
                .where(StorageToolInvocation.session_id == session_id)
                .order_by(StorageToolInvocation.created_at.desc())
                .limit(limit)
            )
            
            result = await db.execute(stmt)
            records = result.scalars().all()
            
            return [
                {
                    "id": str(r.id),
                    "tool_id": r.tool_id,
                    "tool_name": r.tool_name,
                    "invocation_id": r.invocation_id,
                    "args": r.args,
                    "result": r.result,
                    "error": r.error,
                    "status": r.status,
                    "duration_ms": r.duration_ms,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                }
                for r in records
            ]
