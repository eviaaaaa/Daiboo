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

#### Core Context Management Components

**1. Context Assembly Engine** (`context/assembly_engine.py`)
- **Purpose**: Centralize and standardize context building logic from scattered code locations
- **Key Features**:
  - Refactor hardcoded context assembling from `main.py:58-83` into dedicated module
  - Unified interface for RAG retrieval, agent history, and runtime context
  - Automatic context formatting and optimization for LLM consumption
  - Support for context versioning and caching
- **Implementation**: Async functions with type hints, returning structured context dictionaries

**2. State Context Manager** (`context/state_manager.py`)
- **Purpose**: Maintain and track agent state across multi-step tasks
- **Key Features**:
  - Track page transitions and DOM mutations
  - Manage conversation history and task progress
  - Store intermediate results and partial completions
  - Support for state persistence and recovery
- **Database Integration**: Store state snapshots in PostgreSQL with timestamps
- **Implementation**: Class-based with async methods, integrated with `entity/my_state.py`

**3. Dynamic ID System** (`context/dynamic_id/`)
- **Purpose**: Inject stable identifiers to DOM elements, eliminating CSS Selector dependency
- **Architecture**: Based on `docs/design_dynamic_id_system.md` (detailed technical specifications)
- **Components**:
  - `DynamicIdManager`: Singleton ID generator and mapping cache (memory + PostgreSQL)
  - `InjectDynamicIdsTool`: LangChain tool for automatic ID injection on page load
  - `GetElementByIdTool`: Element locator using `data-agent-id` attributes
  - `DOMObserverTool`: MutationObserver for SPA support (optional Phase 3)
- **ID Format**: `agent-{element_type}-{description}-{number}` (e.g., `agent-btn-submit-001`)
- **Performance Targets**: <200ms injection time for large pages, <10MB memory per 1000 elements

**4. Context Versioning & Caching**
- **Purpose**: Optimize context building performance and support A/B testing
- **Implementation**:
  - Cache frequently used contexts in Redis/Memory
  - Version context schemas for backward compatibility
  - Track context usage metrics for optimization

#### Implementation Roadmap

**Phase 1: Foundation (Week 1)**
- [ ] Create `context/assembly_engine.py` with core context building logic
- [ ] Create `context/state_manager.py` with basic state tracking
- [ ] Initialize `context/dynamic_id/` subpackage structure
- [ ] Add context module imports to `context/__init__.py`

**Phase 2: Dynamic ID System (Week 2-3)**
- [ ] Implement `DynamicIdManager` with singleton pattern
- [ ] Implement `InjectDynamicIdsTool` and `GetElementByIdTool`
- [ ] Integrate tools into `agent_factory.py`
- [ ] Update `CaptureElementContextTool` to support agent ID selectors
- [ ] Modify System Prompt to guide LLM on using agent IDs
- [ ] Create database model for ID mapping persistence

**Phase 3: State Management (Week 4)**
- [ ] Enhance `State Context Manager` with full task tracking
- [ ] Implement state persistence to PostgreSQL
- [ ] Add state recovery mechanisms for failed tasks
- [ ] Create state visualization/debugging tools

**Phase 4: Optimization (Week 5)**
- [ ] Implement context caching and versioning
- [ ] Add performance monitoring for context operations
- [ ] DOMObserverTool for SPA applications (optional)
- [ ] Write comprehensive unit, integration, and E2E tests

**Phase 5: Production Ready (Week 6)**
- [ ] Performance tuning and bug fixes
- [ ] Documentation and examples
- [ ] Load testing and scalability validation

#### Current Status

- ✅ Context module initialized (`context/__init__.py` created)
- ✅ Prompt module created (`prompt/system_prompt.py`, `prompt/task_prompt.py`)
- ✅ Agent creation factory implemented (`agent_factory.py` with singleton caching)
- 🔄 Dynamic ID system: In design phase (see `docs/design_dynamic_id_system.md`)
- ⏳ Context Assembly Engine: Not started
- ⏳ State Context Manager: Not started

#### Expected Benefits

- **Stability**: Reduce script failures due to DOM changes from 15-20% to <5%
- **Performance**: 20-40% improvement in element location time with ID caching
- **Maintainability**: Centralized context management reduces code duplication
- **LLM Friendliness**: Human-readable element IDs improve agent comprehension
- **Cross-Session Support**: Persistent ID mappings enable faster repeat executions

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