
from dotenv import load_dotenv
import os

load_dotenv()
QFNU_USERNAME=os.environ["QFNU_USERNAME"]
QFNU_PASSWORD=os.environ["QFNU_PASSWORD"]
tasks: list[str] = []
tasks.append(f"""打开曲阜师范大学教务系统登录页面。如果页面未登录，请使用提供的账号和密码登录。
             账号：{QFNU_USERNAME}，密码：{QFNU_PASSWORD}。
             登录后，进行成绩查询，并分析本学期的各科成绩，找出最高分和最低分的科目，并计算平均分。""")