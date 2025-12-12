# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NexusSurf is an intelligent browser automation agent that uses Large Language Models (LLMs) to perform web automation tasks through natural language instructions. It implements an OODA (Observe-Orient-Decide-Act) loop architecture for autonomous web interaction.

## Key Technologies

- **Python 3.10+** with async/await patterns
- **Playwright** for browser automation (async mode)
- **LangChain** for LLM orchestration and tool integration
- **PostgreSQL with PGVector** for vector storage and hybrid search
- **Tongyi Qwen** LLM models for reasoning
- **pytest** for testing with async support

## Development Commands

### Running Tests
```bash
# Run all tests
pytest

# Run specific test file
pytest test/rag_test.py -v -s

# Run with VSCode debugger (configured in .vscode/launch.json)
# Use F5 or Debug > Start Debugging while test file is open
```

### Running the Main Application
```bash
# Main entry point - currently configured for university login demo
python main.py
```

### Database Setup
```bash
# Ensure PostgreSQL is running with PGVector extension
# Connection details in .env file:
# DB_HOST=localhost, DB_PORT=5432, DB_NAME=postgres, DB_USER=postgres, DB_PASSWORD=123
```

## Architecture

### Core Components

1. **main.py**: Application entry point, orchestrates LangChain agent with RAG-enhanced processing
2. **context/**: Context engineering module (CURRENT FOCUS) - manages contextual information, dynamic ID system, and state tracking
3. **rag/**: Hybrid search implementation combining vector similarity + keyword search + BGE reranking
4. **tools/**: LangChain tools for browser automation (fill_text, get_elements, screenshots, vision analysis)
5. **entity/**: SQLAlchemy models for agent traces, RAG documents, and state management
6. **database/**: PostgreSQL connection management with PGVector support
7. **loggers/**: Agent execution tracing and screenshot capture

### Context Engineering Focus (Current Development Priority)

The project is currently focused on developing a comprehensive **context module** to centralize and optimize contextual information management for the agent.

#### Key Context Management Components

**1. Dynamic ID System** (design docs: `docs/design_dynamic_id_system.md`)
- Inject stable `data-agent-id` attributes to interactive DOM elements
- Eliminate reliance on fragile CSS Selectors
- Provide LLM-friendly element identifiers like `agent-btn-submit-001`
- Components: `DynamicIdManager`, `InjectDynamicIdsTool`, `GetElementByIdTool`

**2. Context Assembly Engine**
- Refactor hardcoded context assembling from `main.py:58-83` into dedicated module
- Unified interface for RAG retrieval, agent history, and runtime context
- Automatic context formatting and optimization for LLM consumption

**3. State Context Management**
- Maintain agent state across multi-step tasks
- Track page transitions and DOM mutations
- Manage conversation history and task progress

See `docs/design_dynamic_id_system.md` for detailed technical specifications and implementation roadmap.

### Key Design Patterns

- **Async-First**: All browser operations use async_playwright
- **Tool-Based Architecture**: Each browser action is a LangChain tool
- **RAG-Enhanced**: Uses hybrid search for context retrieval before agent execution
- **Screenshot Verification**: Critical operations include screenshot validation
- **Agent Tracing**: All agent interactions are logged to database for analysis

### Current Implementation Focus

The system is currently configured as a demo for automated university system login (曲阜师范大学), including:
- Form field identification and filling
- CAPTCHA recognition using vision models
- Login submission and verification

## Testing Guidelines

- **Async Testing**: Use pytest with asyncio_mode = auto
- **VCR.py Integration**: HTTP interactions are recorded for reproducible tests
- **Test Categories**: RAG functionality, browser automation, database operations
- **Debug Support**: VSCode launch configuration for debugging individual test files

## Environment Configuration

Key environment variables in `.env`:
- Database connection (PostgreSQL with PGVector)
- University credentials (QFNU_USERNAME, QNFNU_PASSWORD)
- API keys for vision models (GEMIN_API_KEY)
- Browser configuration (Edge/Chrome via CDP)

## Code Conventions

- **Type Hints**: Use Python type annotations consistently
- **Async Patterns**: All I/O operations should be async
- **Error Handling**: Capture PlaywrightTimeoutError and ElementHandleError
- **Logging**: Use centralized logger from utils/logger.py
- **Database Models**: Inherit from entity/base.py SQLAlchemy base classes