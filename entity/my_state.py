from langchain.agents.middleware import  types

class MyState(types.AgentState):
    start_time: float
    turn_number: int  # 当前对话轮次