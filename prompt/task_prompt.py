
from dotenv import load_dotenv
import os

load_dotenv()
QFNU_USERNAME=os.environ["QFNU_USERNAME"]
QFNU_PASSWORD=os.environ["QFNU_PASSWORD"]
tasks: list[str] = []
tasks.append(f"""打开曲阜师范大学教务系统登录页面（http://zhjw.qfnu.edu.cn/jsxsd/framework/xsMain.jsp）。如果页面未登录，请使用提供的账号和密码登录。
             账号：{QFNU_USERNAME}，密码：{QFNU_PASSWORD}。
             登录后，进行成绩查询，并分析本学期的各科成绩，找出最高分和最低分的科目，并计算平均分。""")
tasks.append("""
    打开 https://www.saucedemo.com/，账号:standard_user，密码：secret_sauce,登录，之后告诉我页面中有什么？
""")

tasks.append(f"""打开曲阜师范大学教务系统登录页面（http://zhjw.qfnu.edu.cn/jsxsd/framework/xsMain.jsp）。如果页面未登录，请使用提供的账号和密码登录。
             账号：{QFNU_USERNAME}，密码：{QFNU_PASSWORD}。
             登录后，查询本学期的课表，并告诉我周一上午有哪些课。""")

tasks.append(f"""打开曲阜师范大学教务系统登录页面（http://zhjw.qfnu.edu.cn/jsxsd/framework/xsMain.jsp）。如果页面未登录，请使用提供的账号和密码登录。
             账号：{QFNU_USERNAME}，密码：{QFNU_PASSWORD}。
             登录后，查看考试安排，列出所有即将进行的考试科目、时间和地点。""")

tasks.append(f"""打开曲阜师范大学教务系统登录页面（http://zhjw.qfnu.edu.cn/jsxsd/framework/xsMain.jsp）。如果页面未登录，请使用提供的账号和密码登录。
             账号：{QFNU_USERNAME}，密码：{QFNU_PASSWORD}。
             登录后，进入个人信息页面，提取并告诉我学号、姓名、所在学院和专业名称。""")

tasks.append(f"""打开曲阜师范大学教务系统登录页面（http://zhjw.qfnu.edu.cn/jsxsd/framework/xsMain.jsp）。如果页面未登录，请使用提供的账号和密码登录。
             账号：{QFNU_USERNAME}，密码：{QFNU_PASSWORD}。
             登录后，查找培养方案或学业进度，列出毕业所需的总学分以及必修课和选修课的学分要求。""")

tasks.append(f"""打开曲阜师范大学教务系统登录页面（http://zhjw.qfnu.edu.cn/jsxsd/framework/xsMain.jsp）。如果页面未登录，请使用提供的账号和密码登录。
             账号：{QFNU_USERNAME}，密码：{QFNU_PASSWORD}。
             登录后，查询今天的空闲教室情况，帮我找一个下午没课的教室用于自习。""")

tasks.append(f"""打开曲阜师范大学教务系统登录页面（http://zhjw.qfnu.edu.cn/jsxsd/framework/xsMain.jsp）。如果页面未登录，请使用提供的账号和密码登录。
             账号：{QFNU_USERNAME}，密码：{QFNU_PASSWORD}。
             登录后，检查是否有未完成的教学评价（评教），如果有，列出需要评价的课程名称。""")

tasks.append(f"""打开曲阜师范大学教务系统登录页面（http://zhjw.qfnu.edu.cn/jsxsd/framework/xsMain.jsp）。如果页面未登录，请使用提供的账号和密码登录。
             账号：{QFNU_USERNAME}，密码：{QFNU_PASSWORD}。
             登录后，查看等级考试报名信息（如英语四六级、计算机二级等），告诉我当前是否有正在进行的报名以及报名截止时间。""")

tasks.append(f"""打开曲阜师范大学教务系统登录页面（http://zhjw.qfnu.edu.cn/jsxsd/framework/xsMain.jsp）。如果页面未登录，请使用提供的账号和密码登录。
             账号：{QFNU_USERNAME}，密码：{QFNU_PASSWORD}。
             登录后，查看当前的选课结果，列出本学期已成功选择的所有课程名称和学分。""")

tasks.append(f"""打开曲阜师范大学教务系统登录页面（http://zhjw.qfnu.edu.cn/jsxsd/framework/xsMain.jsp）。如果页面未登录，请使用提供的账号和密码登录。
             账号：{QFNU_USERNAME}，密码：{QFNU_PASSWORD}。
             登录后，浏览教务系统首页的通知公告栏，提取最新的3条通知标题和发布日期。""")