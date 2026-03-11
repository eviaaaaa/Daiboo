import os
import dotenv
from sqlalchemy import (
    create_engine,
    URL, # 引入 URL 对象，更安全地构建连接字符串
)

# --- 1. 加载配置 ---
dotenv.load_dotenv()
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD")
}

print("DB_CONFIG:", {k: v for k, v in DB_CONFIG.items() if k != 'password'})
print("Password length:", len(DB_CONFIG["password"]) if DB_CONFIG["password"] else 0)

# --- 创建全局 Engine (核心步骤) ---

# 构建 SQLAlchemy 连接 URL
# 使用 URL.create() 是更健壮的方式，可以自动处理特殊字符
db_url = URL.create(
    drivername="postgresql+psycopg",  # 使用 psycopg v3
    username=DB_CONFIG["user"],
    password=DB_CONFIG["password"],
    host=DB_CONFIG["host"],
    port=DB_CONFIG["port"],
    database=DB_CONFIG["dbname"],
)
# 创建 Engine。这个 engine 对象应该在你的应用中是单例的。
engine = create_engine(db_url, echo=False)
# 遍历实体类，创建所有表
# 注意：实际的表创建应该在需要的地方调用，而不是在模块导入时
# Base.metadata.create_all(engine)

print("\nSQLAlchemy Engine 创建成功！")