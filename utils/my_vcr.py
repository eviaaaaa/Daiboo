import vcr
 
# 创建VCR对象，并过滤敏感信息
MyVcr = vcr.VCR(
    cassette_library_dir='test/vcr_cassettes',
    path_transformer=vcr.VCR.ensure_suffix('.yaml'),
    record_mode='once',
    filter_headers=['authorization'],  # 过滤请求头中的authorization字段
    filter_query_parameters=['api_key'],  # 过滤请求参数中的api_key字段
    ignore_localhost=True
)
