# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NexusSurf is an intelligent browser automation agent that uses Large Language Models (LLMs) to perform web automation tasks through natural language instructions. It implements an OODA (Observe-Orient-Decide-Act) loop architecture for autonomous web interaction.

## Key Technologies

- **Python 3.10+** with async/await patterns
- **Playwright** for browser automation (async mode)
- **LangChain** for LLM orchestration and tool integration
- **PostgreSQL with PGVector** for vector storage and hybrid search
- **Tongyi Qwen** LLM models for reasoning (qwen3-max, qwen3-vl-plus)
- **pytest** for testing with async support
- **FastAPI** for RESTful API and WebSocket support
- **Vue 3 + TailwindCSS** for frontend interface
- **VCR.py** for HTTP interaction recording in tests

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

### Running the API Server (with Frontend)
```bash
# Start FastAPI server with automatic browser launch
python run_server.py

# This will:
# 1. Start the API server on http://localhost:8801
# 2. Automatically open the frontend interface
# 3. Initialize Playwright browser connection
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
2. **api.py**: FastAPI server providing RESTful API and WebSocket endpoints for browser automation
3. **run_server.py**: Server launcher with automatic browser initialization
4. **frontend/index.html**: Vue 3 + TailwindCSS web interface for agent interaction
5. **context/**: Context engineering module (CURRENT FOCUS) - manages contextual information, compression, and state tracking
6. **rag/**: Hybrid search implementation combining vector similarity + keyword search + BGE reranking
7. **tools/**: LangChain tools for browser automation (fill_text, get_elements, screenshots, vision analysis)
8. **entity/**: SQLAlchemy models for agent traces, RAG documents, and state management
9. **database/**: PostgreSQL connection management with PGVector support
10. **loggers/**: Agent execution tracing and screenshot capture
11. **utils/qwen_model.py**: Unified Qwen model configuration (qwen3-max, qwen3-vl-plus)

### Context Engineering Focus (Current Development Priority)

The project is currently focused on developing a comprehensive **context module** to centralize and optimize contextual information management for the agent.

#### Core Context Management Components

**1. Context Assembly Engine** (`context/assembly_engine.py`) - (NOT IMPLEMENTED)
- **Purpose**: Centralize and standardize context building logic from scattered code locations
- **Key Features**:
  - Refactor hardcoded context assembling from `main.py:58-83` into dedicated module
  - Unified interface for RAG retrieval, agent history, and runtime context
  - Automatic context formatting and optimization for LLM consumption
  - Support for context versioning and caching
- **Implementation**: Planned but not yet implemented

**2. Context Compression & Token Management** (`context/context_manager.py`)
- **Purpose**: Intelligent token compression to handle long conversations and large contexts
- **Key Features**:
  - **Dynamic Compression**: Automatic message compression based on token ratio thresholds
  - **Smart Message Removal**: Remove redundant messages while preserving critical context
  - **Token Budget Management**: Configurable max_token_ratio (default 0.8) and single_msg_ratio (0.8)
  - **Conversation History Optimization**: Maintains conversation flow while reducing token usage
- **Implementation**:
  - `ContextManagerMiddleware`: Async context manager with compression logic
  - Integration with `langchain_core.messages` for message processing
  - Support for `HumanMessage`, `AIMessage`, and `SystemMessage` compression
- **Testing**: Comprehensive test coverage in `test/test_context_compression.py`

**3. State Context Manager** (`context/state_manager.py`) - (NOT IMPLEMENTED)
- **Purpose**: Maintain and track agent state across multi-step tasks
- **Key Features**:
  - Track page transitions and DOM mutations
  - Manage conversation history and task progress
  - Store intermediate results and partial completions
  - Support for state persistence and recovery
- **Database Integration**: Store state snapshots in PostgreSQL with timestamps
- **Implementation**: Planned but not yet implemented

**4. Dynamic ID System** (`context/dynamic_id/`) - (NOT IMPLEMENTED)
- **Purpose**: Inject stable identifiers to DOM elements, eliminating CSS Selector dependency
- **Architecture**: Based on `docs/design_dynamic_id_system.md` (detailed technical specifications)
- **Components**:
  - `DynamicIdManager`: Singleton ID generator and mapping cache (memory + PostgreSQL)
  - `InjectDynamicIdsTool`: LangChain tool for automatic ID injection on page load
  - `GetElementByIdTool`: Element locator using `data-agent-id` attributes
  - `DOMObserverTool`: MutationObserver for SPA support (optional Phase 3)
- **ID Format**: `agent-{element_type}-{description}-{number}` (e.g., `agent-btn-submit-001`)
- **Performance Targets**: <200ms injection time for large pages, <10MB memory per 1000 elements

**5. Context Versioning & Caching**
- **Purpose**: Optimize context building performance and support A/B testing
- **Implementation**:
  - Cache frequently used contexts in memory
  - Version context schemas for backward compatibility
  - Track context usage metrics for optimization

**6. Agent KB & Smart Reuse System** (agent_kb/) - 基于《Agent KB》论文 - (NOT IMPLEMENTED)
- **Purpose**: 双闭环系统：离线经验沉淀 + 在线智能推理
- **核心创新**：
  - **离线学习闭环** (Experience Mining Pipeline):
    - `TrajectorySegmenter`: 轨迹分割器（基于人类介入点、状态变更点）
    - `LLMGeneralizer`: LLM泛化器（去除具体变量，提取逻辑模式）
    - `ExperienceUnitBuilder`: 经验单元构建器（结构化JSON）
  - **在线推理闭环** (Cognitive Pipeline):
    - `PlanningRetriever`: 规划检索（检索高层Workflow）
    - `ExecutionRetriever`: 执行检索（检索具体技能和纠错经验）
    - `RelevanceGate`: 分歧门控（防止错误经验误导）
- **结构化经验单元**:
  ```python
  {
    "task_pattern": "抽象任务模式",
    "insight": "核心洞察",
    "thought_chain": "思考链",
    "negative_lesson": "负面教训",
    "source": "human_correction | agent_self_reflection",
    "priority": 0.0-1.0
  }
  ```
- **双阶段检索**:
  - 阶段1：规划检索（检索SOP标准作业程序）
  - 阶段2：执行检索（检索微观技能和纠错经验）
- **认知流水线**: Reason → Retrieve → Refine
- **特殊机制**:
  - 人类反馈高优先级（权重提升50%）
  - 动态上下文窗口（Current_Goal_State跟踪）
  - 分歧门控LLM判别器（准确率>80%）
- **性能目标**: <100ms检索延迟, >30%成功率提升, >40%时间缩短
- **详细设计**: [Agent KB Master Blueprint](docs/agent_kb_master_blueprint.md)
- **Implementation Status**: Only empty `agent_kb/__init__.py` exists

#### Implementation Roadmap

**Phase 1: Foundation (Week 1)**
- ❌ Create `context/assembly_engine.py` with core context building logic - (NOT IMPLEMENTED)
- ❌ Create `context/state_manager.py` with basic state tracking - (NOT IMPLEMENTED)
- ❌ Initialize `context/dynamic_id/` subpackage structure - (NOT IMPLEMENTED)
- ✅ Add context module imports to `context/__init__.py`

**Phase 2: API & Frontend (Week 2)**
- ✅ Implement FastAPI server (`api.py`) with WebSocket support
- ✅ Create Vue 3 frontend interface (`frontend/index.html`)
- ✅ Add server launcher (`run_server.py`) with browser initialization
- ✅ Integrate context compression into API layer

**Phase 3: Context Compression (Week 3)**
- ✅ Implement `ContextManagerMiddleware` for intelligent token compression
- ✅ Add context compression testing framework
- ✅ Optimize memory usage for long conversations
- ✅ Configure Qwen model integration with proper profiles

**Phase 4: Agent KB & Smart Reuse (Week 4-5)** ⭐ NEW PRIORITY - DESIGN COMPLETED
- [x] **Create Agent KB Master Blueprint** (docs/agent_kb_master_blueprint.md)
- [x] **Design Offline Learning Pipeline**:
  - TrajectorySegmenter: Split sessions into (Problem, Solution, Result) triplets
  - LLMGeneralizer: Extract abstract patterns from concrete traces
  - ExperienceUnitBuilder: Build structured knowledge units
- [x] **Design Online Inference Pipeline**:
  - CognitivePipeline: Reason → Retrieve → Refine
  - PlanningRetriever: Retrieve SOP workflows
  - ExecutionRetriever: Retrieve micro-skills and error patterns
  - RelevanceGate: LLM judge to prevent misleading knowledge
- [x] **Design Special Mechanisms**:
  - Human Feedback Priority: 50% weight boost
  - Dynamic Context Window: Current_Goal_State tracking
  - Dual-Phase Retrieval: High-level + low-level
- [ ] **Implementation Phase** (Next):
  - Build agent_kb/ module with all components - (NOT STARTED)
  - Implement vector database with multi-index - (NOT STARTED)
  - Integrate cognitive pipeline into agent_factory - (NOT STARTED)
  - Add performance monitoring and optimization - (NOT STARTED)

**Phase 5: Dynamic ID System (Week 6-7)**
- [ ] Implement `DynamicIdManager` with singleton pattern
- [ ] Implement `InjectDynamicIdsTool` and `GetElementByIdTool`
- [ ] Integrate tools into `agent_factory.py`
- [ ] Update `CaptureElementContextTool` to support agent ID selectors
- [ ] Modify System Prompt to guide LLM on using agent IDs
- [ ] Create database model for ID mapping persistence

**Phase 6: State Management (Week 8)**
- [ ] Enhance `State Context Manager` with full task tracking
- [ ] Implement state persistence to PostgreSQL
- [ ] Add state recovery mechanisms for failed tasks
- [ ] Create state visualization/debugging tools

**Phase 7: Optimization & Production (Week 9)**
- [ ] Implement context caching and versioning
- [ ] Add performance monitoring for context operations
- [ ] DOMObserverTool for SPA applications (optional)
- [ ] Write comprehensive unit, integration, and E2E tests
- [ ] Performance tuning and bug fixes

#### Current Status (Updated: 2025-12-26)

- ✅ **Context module**: Partially implemented with context compression capabilities
- ✅ **Prompt module**: Created (`prompt/system_prompt.py`, `prompt/task_prompt.py`)
- ✅ **Agent factory**: Implemented (`agent_factory.py` with singleton caching)
- ✅ **API Server**: FastAPI server with WebSocket endpoints
- ✅ **Frontend Interface**: Vue 3 + TailwindCSS web UI
- ✅ **Context Compression**: Intelligent token management system (`context_manager.py`)
- ✅ **Model Integration**: Qwen3-max and Qwen3-vl-plus support
- ✅ **Testing Framework**: Comprehensive test suite with VCR.py
- 🔄 **Agent KB System**: Dual-loop architecture designed (see `docs/agent_kb_master_blueprint.md`)
  - Offline learning pipeline designed
  - Online inference cognitive pipeline designed
  - Relevance gating mechanism designed
- ⏳ **Dynamic ID system**: In design phase (see `docs/design_dynamic_id_system.md`)
- ⏳ **Context Assembly Engine**: Not yet implemented
- ⏳ **State Context Manager**: Not yet implemented

#### Expected Benefits

- **Stability**: Reduce script failures due to DOM changes from 15-20% to <5%
- **Performance**: 20-40% improvement in element location time with ID caching
- **Context Efficiency**: 50-70% reduction in token usage through intelligent compression
- **Memory Optimization**: Reduced memory footprint for long-running sessions
- **Maintainability**: Centralized context management reduces code duplication
- **LLM Friendliness**: Human-readable element IDs improve agent comprehension
- **Cross-Session Support**: Persistent ID mappings enable faster repeat executions
- **User Experience**: Web UI enables real-time monitoring and interaction

### Key Design Patterns

- **Async-First**: All browser operations use async_playwright with WindowsProactorEventLoopPolicy
- **Tool-Based Architecture**: Each browser action is a LangChain tool
- **RAG-Enhanced**: Uses hybrid search (vector similarity + keyword search + reranking) - **Note**: RAG is now encapsulated as a tool (`search_knowledge_base`) and only executed when explicitly called by the model
- **Screenshot Verification**: Critical operations include screenshot validation
- **Agent Tracing**: All agent interactions are logged to database for analysis
- **Compression-First**: Intelligent token management to handle long conversations
- **API-Driven**: RESTful API with WebSocket support for real-time communication
- **Frontend-Backend Separation**: Vue 3 frontend communicating with FastAPI backend

### Current Implementation Focus

The system now supports multiple interaction modes:

1. **CLI Mode** (main.py): Direct command-line interface for university system login (曲阜师范大学)
   - Form field identification and filling
   - CAPTCHA recognition using vision models (qwen3-vl-plus)
   - Login submission and verification

2. **Web UI Mode** (run_server.py): Full-featured web interface for browser automation
   - Real-time chat interface for agent interaction
   - Document upload and RAG integration
   - Tool listing and monitoring
   - Browser automation control panel
   - Session management and history

3. **API Mode** (api.py): RESTful API for programmatic access
   - `/chat` endpoint for agent communication
   - `/upload` endpoint for document ingestion
   - `/tools` endpoint for tool listing
   - WebSocket support for real-time updates
   - Browser control endpoints

### Recent Updates (December 2025)

- **Context Compression**: Implemented intelligent token management (2025-12-20)
- **Frontend Interface**: Added Vue 3 web UI with TailwindCSS (2025-12-20)
- **API Server**: Created FastAPI backend with WebSocket support (2025-12-20)
- **Model Upgrade**: Integrated qwen3-max (text) and qwen3-vl-plus (vision) models (2025-12-17)
- **Element Tools**: Enhanced element content extraction and data cleaning (2025-12-26)
- **Agent KB System**: Designed dual-loop system based on "Agent KB" paper (2025-12-26)
  - **Offline Learning Loop**: Trajectory segmentation → LLM generalization → Structured storage
  - **Online Inference Loop**: Reason → Retrieve → Refine cognitive pipeline
  - **Relevance Gating**: LLM judge to prevent misleading knowledge
  - **Human Feedback Priority**: 50% weight boost for human corrections
  - **Dynamic Context Window**: Current_Goal_State tracking for multi-turn dialogues
  - See `docs/agent_kb_master_blueprint.md` for complete design
  - See `docs/agent_kb_optimization_plan.md` for implementation plan

## Testing Guidelines

- **Async Testing**: Use pytest with asyncio_mode = auto
- **VCR.py Integration**: HTTP interactions are recorded for reproducible tests
- **Test Categories**:
  - RAG functionality (`test/rag_test.py`, `test/test_rag_custom.py`, `test/test_rag_distance.py`)
  - Browser automation (`test/playwright_test.py`)
  - Database operations (`test/pgsql_test.py`)
  - Context compression (`test/test_context_compression.py`)
  - Model integration (`test/VL_Analysis_Too_test.py`)
- **Debug Support**: VSCode launch configuration for debugging individual test files
- **Test Notebook**: Interactive testing and experimentation in `test.ipynb`

## Environment Configuration

Key environment variables in `.env`:
- **Database**: PostgreSQL with PGVector (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD)
- **University Login**: QFNU_USERNAME, QFNU_PASSWORD (for 曲阜师范大学 system)
- **AI Models**:
  - DASHSCOPE_API_KEY (for Qwen models)
  - GEMIN_API_KEY (optional, for Gemini vision models)
- **Browser Configuration**: Edge/Chrome via CDP (configured in utils/my_browser.py)
- **Server Configuration**:
  - API_PORT (default: 8801)
  - FRONTEND_URL (auto-detected)

## Code Conventions

- **Type Hints**: Use Python type annotations consistently (Python 3.10+)
- **Async Patterns**: All I/O operations should be async
  - Use `asyncio.WindowsProactorEventLoopPolicy()` on Windows
  - Configure in `run_server.py` and `api.py`
- **Error Handling**:
  - Capture `PlaywrightTimeoutError` and `ElementHandleError`
  - Implement proper error responses in API endpoints
  - Use try-catch blocks for async operations
- **Logging**: Use centralized logger from utils/logger.py
- **Database Models**: Inherit from entity/base.py SQLAlchemy base classes
- **Message Handling**: Use `langchain_core.messages` for standardized message format
- **API Design**: Follow FastAPI best practices with Pydantic models
- **Frontend**: Use Vue 3 Composition API and TailwindCSS for styling
- **Testing**: Record HTTP interactions with VCR.py for reproducibility