import vcr
 
# 创建 VCR 对象，并过滤敏感信息
MyVcr = vcr.VCR(
    cassette_library_dir='test/vcr_cassettes',
    path_transformer=vcr.VCR.ensure_suffix('.yaml'),
    record_mode='once',
    filter_headers=['authorization'],  # 过滤请求头中的 authorization 字段
    filter_query_parameters=['api_key'],  # 过滤请求参数中的 api_key 字段
    ignore_localhost=True,
    ignore_hosts=['api.smith.langchain.com'],  # 忽略 LangSmith 的追踪请求
)
