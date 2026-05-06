# Manual Test Scripts

这个目录放不会参与默认 `pytest` 收集的手工联调脚本。

约定：

- 需要真实浏览器、真实账号、数据库、副作用或人工观察的脚本放这里。
- 目录已被 `pytest.ini` 的 `norecursedirs` 排除，执行 `pytest` 时不会自动跑。
- 运行仓库脚本前先切到 `conda activate langchainenv`。

示例：

```powershell
conda run -n langchainenv python test/manual/epic_login_manual.py
```
