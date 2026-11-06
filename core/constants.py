# 超时时间（秒）
PENDING_QUERY_TIMEOUT = 60
PENDING_ALIAS_TIMEOUT = 300

# 默认题目数量
DEFAULT_QUESTION_COUNT = 15

# LLM 相似度阈值
LLM_SIMILARITY_THRESHOLD = 75

# 字符相似度阈值
STRING_SIMILARITY_THRESHOLD = 60

# 特殊题库名
ALL_BANK = "all"

# 命令前缀（用于判断是否是命令，用于监听器过滤）
COMMAND_SET = {
    # 开始游戏
    "letter", "开始开字母", "letterload", "letterpreset",
    
    # 游戏内操作
    "open", "开", "tip", "提示", "猜", "guess", "end", "结束", "结束开字母",
    
    # 题库管理
    "题库", "禁用", "启用", "全部禁用", "全部启用",
    
    # 自定义题库
    "uploadbank", "上传题库", "mybanks", "我的题库", "delbank", "删除题库",
    "bankrename", "改名", "修改题库名字", "bankinfo", "题库信息",
    "共享题库", "取消共享", "共享列表", 
    
    # 别名系统
    "查曲", "song", "查询", "search", 
    "加别名", "addalias", "删别名", "delalias",
    "导入别名", "导出别名", "导入题库", "导出题库",
    
    # 别名审核
    "通过", "approve", "全部通过", "拒绝", "reject", "全部拒绝", "待审", "pending",
    
    # 预设
    "mypreset", "letterpreset", "上传预设", "我的预设", "加载预设",
    
    # 其他
    "daily", "每日挑战", "比赛模式","查看排行榜",
    
    # 帮助
    "letterhelp", "开字母帮助",
}