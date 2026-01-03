"""
经验总结 Prompt 模板
用于子 Agent 分析执行链路并生成可复用的经验知识
"""

EXPERIENCE_SUMMARY_PROMPT = """你是一个浏览器自动化经验提炼专家。请分析以下 Agent 执行记录，判断是否值得作为经验保存到知识库。

## 任务信息
**用户任务**: {user_query}
**使用工具**: {tool_names}
**最终回答**: {final_answer}

## 执行记录摘要
{trace_summary}

## 你的任务
请严格按照以下 JSON Schema 输出结果（不要添加任何额外文本）：

```json
{{
  "is_valuable": boolean,  // 是否值得记录
  "task_type": "login|search|form|navigation|data_extraction|other",
  "success": boolean,
  "experience": "string",  // Markdown 格式的经验描述
  "website_domain": "string or null"  // 网站域名，如 "github.com"
}}
```

## 判断标准

### 值得记录的情况 (is_valuable = true)
1. 涉及复杂的网站交互流程（登录、多步骤表单、导航）
2. 遇到并解决了特定的技术问题（如动态加载、验证码、特殊选择器）
3. 包含可复用的操作模式或最佳实践
4. 失败案例且包含有价值的避坑指南

### 不值得记录的情况 (is_valuable = false)
1. 简单的问答或闲聊（"你好"、"测试"等）
2. 单一的导航或信息查询（仅打开页面）
3. 重复的常见操作（无新信息）
4. **重要**：如果用户消息包含"归档文件"、"archived"等字样，说明上下文已压缩，必须返回 false

### experience 字段格式要求
使用 Markdown 格式，结构清晰，包含：
- **任务目标**：简述任务
- **关键步骤**：编号列出操作步骤
- **选择器/参数**：记录重要的 CSS 选择器或参数
- **注意事项**：记录坑点或特殊处理

示例：
```markdown
### 登录 GitHub
**目标**：使用用户名和密码登录 GitHub

**步骤**：
1. 导航到 https://github.com/login
2. 填写用户名：选择器 `#login_field`
3. 填写密码：选择器 `#password`
4. 点击登录按钮：选择器 `input[type="submit"]`
5. 等待页面跳转到主页

**注意事项**：
- GitHub 可能触发二次验证，需要额外处理
- 登录失败时页面会显示错误提示，需检测
```

## 示例输出

### 示例 1：值得记录
```json
{{
  "is_valuable": true,
  "task_type": "login",
  "success": true,
  "experience": "### 登录 Swag Labs\\n**目标**：使用标准用户登录测试网站\\n\\n**步骤**：\\n1. 导航到 https://www.saucedemo.com/\\n2. 填写用户名：`standard_user`\\n3. 填写密码：`secret_sauce`\\n4. 点击登录按钮\\n\\n**注意事项**：\\n- 该网站用于测试，凭据固定\\n- 登录成功后 URL 变为 `/inventory.html`",
  "website_domain": "saucedemo.com"
}}
```

### 示例 2：不值得记录
```json
{{
  "is_valuable": false,
  "task_type": "other",
  "success": true,
  "experience": "",
  "website_domain": null
}}
```

现在请开始分析。
"""


def format_trace_for_summary(full_trace: list, max_length: int = 15000) -> str:
    """
    将完整的执行记录格式化为适合 LLM 分析的摘要
    
    Args:
        full_trace: 序列化的消息列表
        max_length: 最大字符长度
    
    Returns:
        格式化的摘要文本
    """
    summary_parts = []
    
    for i, msg in enumerate(full_trace, 1):
        msg_type = msg.get('role', 'unknown')
        content = msg.get('content', '')
        
        # 跳过过长的内容（已被压缩的 HTML 等）
        if len(content) > 500:
            content = content[:500] + f"... [内容过长，已截断，共 {len(content)} 字符]"
        
        summary_parts.append(f"**步骤 {i} ({msg_type})**:")
        
        # 如果是 AI 消息，提取工具调用
        if msg_type == 'ai' and 'tool_calls' in msg:
            tool_calls = msg.get('tool_calls', [])
            if tool_calls:
                summary_parts.append("  调用工具:")
                for tc in tool_calls:
                    tool_name = tc.get('name', 'unknown')
                    tool_args = tc.get('args', {})
                    summary_parts.append(f"  - {tool_name}: {tool_args}")
        
        summary_parts.append(f"  内容: {content}")
        summary_parts.append("")
        
        # 控制总长度
        current_text = "\n".join(summary_parts)
        if len(current_text) > max_length:
            summary_parts.append(f"... [后续步骤已省略]")
            break
    
    return "\n".join(summary_parts)
