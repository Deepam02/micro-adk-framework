-- Micro ADK Database Initialization
-- This script runs on first startup of the PostgreSQL container
-- The schema matches the SQLAlchemy models in postgres_session_service.py

-- Create the sessions table for storing agent sessions
CREATE TABLE IF NOT EXISTS sessions (
    app_name VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    id VARCHAR(255) NOT NULL,
    state JSONB NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Composite primary key
    PRIMARY KEY (app_name, user_id, id)
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_sessions_app_user ON sessions(app_name, user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at);

-- Create the events table for storing session events
CREATE TABLE IF NOT EXISTS events (
    id VARCHAR(255) NOT NULL,
    app_name VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    session_id VARCHAR(255) NOT NULL,
    invocation_id VARCHAR(255),
    author VARCHAR(255) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    event_data JSONB,
    
    -- Composite primary key
    PRIMARY KEY (id, app_name, user_id, session_id),
    
    -- Foreign key to sessions
    CONSTRAINT fk_event_session FOREIGN KEY (app_name, user_id, session_id) 
        REFERENCES sessions(app_name, user_id, id) ON DELETE CASCADE
);

-- Create index for event queries
CREATE INDEX IF NOT EXISTS idx_events_session ON events(app_name, user_id, session_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_invocation ON events(invocation_id);

-- Create the tool_invocations table for tracking tool calls
CREATE TABLE IF NOT EXISTS tool_invocations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_name VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    session_id VARCHAR(255) NOT NULL,
    event_id VARCHAR(255),
    tool_id VARCHAR(255) NOT NULL,
    tool_name VARCHAR(255) NOT NULL,
    invocation_id VARCHAR(255),
    args JSONB,
    result JSONB,
    error TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    duration_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    
    -- Constraints
    CONSTRAINT valid_status CHECK (status IN ('pending', 'success', 'error')),
    
    -- Foreign key to sessions
    CONSTRAINT fk_tool_invocation_session FOREIGN KEY (app_name, user_id, session_id) 
        REFERENCES sessions(app_name, user_id, id) ON DELETE CASCADE
);

-- Create indexes for tool invocation queries
CREATE INDEX IF NOT EXISTS idx_tool_invocations_session ON tool_invocations(app_name, user_id, session_id);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_tool ON tool_invocations(tool_id);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_status ON tool_invocations(status);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_event ON tool_invocations(event_id);
