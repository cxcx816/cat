# -*- coding: utf-8 -*-
"""
像素宠物 · Pixel Pal Android —— 像素引擎 + 养成逻辑层
本文件由 make_engine.py 从桌面版 main.py 自动提取生成，请勿手工修改；
桌面版更新后重新运行 make_engine.py 即可同步。
"""
import datetime
import json
import math
import os
import random
import struct
import sys
import threading
import traceback
import urllib.request
import zlib

if getattr(sys, 'frozen', False):      # PyInstaller 打包后：存档放在 exe 旁边
    BASE = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
SAVE_PATH = os.path.join(BASE, 'pet_save.json')

MAGIC = '#ff00fe'          # 透明色键：此颜色的像素完全透明且鼠标穿透

# 安卓版不需要 Windows DPI 感知
DPI = 1.0
def u(v):
    """逻辑像素 -> 物理像素"""
    return int(round(v * DPI))

# ---------------- 精灵栅格 ----------------
GW, GH = 210, 180          # 内部像素栅格（超精细：同尺寸下颗粒再细一倍）


SIZE_MIN, SIZE_MAX, SIZE_STEP = 0.5, 5.0, 0.5
SIZE_LEVELS = [round(SIZE_MIN + i * SIZE_STEP, 2)
               for i in range(int(round((SIZE_MAX - SIZE_MIN) / SIZE_STEP)) + 1)]
SIZE_NAME = {0.5: '特小', 1.0: '很小', 1.5: '偏小', 2.0: '小', 2.5: '中小',
             3.0: '中', 3.5: '中大', 4.0: '大', 4.5: '很大', 5.0: '特大'}


def _saved_size():
    """从存档读取宠物大小（0.5~5.0 连续档位，步长 0.5）"""
    try:
        with open(SAVE_PATH, 'r', encoding='utf-8') as f:
            v = float(json.load(f).get('size') or 0)
        v = round(v / SIZE_STEP) * SIZE_STEP
        return min(SIZE_MAX, max(SIZE_MIN, v))
    except Exception:
        return 2.0


SIZE = _saved_size()
Z = int(math.ceil(SIZE * 2))   # zoom 倍数；subsample(2) 后 = SIZE 倍（支持 0.5 步进）
PX = Z / 2.0                   # 一个栅格像素的物理尺寸（≥0.5，细线条不会被采样丢掉）
SPW, SPH = int(round(GW * PX)), int(round(GH * PX))
FOOT = 156                 # 脚底所在行(阴影另算)
CX = GW // 2               # 水平中心

# ---------------- 窗口 ----------------
# 右侧留白放气泡（透明区域不显示且鼠标穿透）。
# 左边距动态计算：操作条宽度固定，若宠物太靠左，操作条无法以宠物为中心，
# 会被夹到窗口中间 —— 宠物缩小后看起来就"偏左上"。
BAR_TOTAL = 11 * u(40) + 10 * u(6)   # 操作条总宽（与 PixelPal.BTN_* 保持一致）

# ---------------- 每日打卡 ----------------
REMIND_TASKS = ['雅思听了吗', '文献精读了吗', '规划完成了吗']
REMIND_KEEP = 90                    # 打卡历史保留天数
ENCOURAGE_MS = 5 * 60 * 1000        # 鼓励语间隔：5 分钟
MOVE_MS = 40 * 60 * 1000            # 久坐提醒间隔：40 分钟

# ---------------- 跨电脑通信（好友 & 互发消息）----------------
RELAY_URL = 'https://pixel-pal-relay.app.workbuddy.host'   # 通信中转服务
POLL_MS = 5000                      # 拉取新消息的间隔
CHAT_KEEP = 300                     # 本地最多保存的聊天条数
MOVE_MSGS = [
    '已经坐了 40 分钟啦，起来伸个懒腰，活动一下吧～',
    '久坐对身体不好哦，起来走两步再回来～',
    '主人，站起来活动一下吧，我陪着你～',
    '喝口水、站起来转一转，眼睛也要休息一下哦～',
    '腰酸不酸呀？起来扭一扭，我在这儿等你回来～',
]
WEATHER_MS = 3 * 60 * 60 * 1000     # 天气播报刷新间隔：3 小时
WEATHER_SAY_MS = 4000               # 点击天气按钮后，气泡 4 秒消失
WEATHER_URL = ('https://wttr.in/?format=%l:%c+%t+%7C+%e6%b9%bf%e5%ba%a6%h'
               '&lang=zh')

# ---------------- 睡觉 / 晒太阳 ----------------
POSE_MS = 10 * 60 * 1000             # 睡觉 / 晒太阳持续 10 分钟后自动恢复
POSE_SLEEP_MSGS = [
    '好困呀…我先躺下睡一会儿，10 分钟后叫我哦～',
    '呼…这张小床真软，我眯一会儿。',
    '眼皮好重，先睡 10 分钟，醒来再陪你～',
]
POSE_SUN_MSGS = [
    '晒晒太阳，暖洋洋的最舒服啦～我跳一会儿！',
    '太阳真好！我要开心地蹦蹦跳跳～',
    '晒太阳最幸福了，看我跳得多高～',
]

# ---------------- 串门（去好友家一起玩）----------------
VISIT_MS = 30 * 60 * 1000            # 一次串门最长玩 30 分钟，之后自动回家
VISIT_POLL_MS = 2000                 # 串门期间同步更勤快（2 秒一次）
VISIT_KNOCK_MSGS = [
    '咚咚咚～我去找「%s」串门啦，等它开门哟～',
    '咚咚咚！「%s」在家吗？我来找你玩啦～',
]
VISIT_KNOCK_PEER_MSGS = [
    '咚咚咚～「%s」的小猫来敲门啦，点一下门给它开开～',
    '门铃响啦！是「%s」来串门了，点点门就开门～',
]
VISIT_OPEN_MSGS = [
    '「%s」来我家玩啦，我们一起玩～',
    '和「%s」手牵着手，开心！',
]
VISIT_OPEN_VISIT_MSGS = [
    '门开啦！「%s」请多关照，我们一起玩吧～',
    '见到「%s」最开心了，牵着手一起玩～',
]
VISIT_BYE_MSGS = [
    '「%s」回家啦，下次再一起玩～',
    '今天玩得真开心，拜拜「%s」～',
]
VISIT_REFUSE_MSGS = [
    '「%s」的小猫刚吃过啦，摇摇头拒绝了～',
    '「%s」的小猫肚肚还圆圆的，吃不下啦～',
]


def day_key(ts=None):
    d = datetime.date.fromtimestamp((ts or time_now()) / 1000.0)
    return d.isoformat()


def remind_stats(rem, nt=None):
    """rem: {'YYYY-MM-DD': [1,0,1], ...} → 打卡统计"""
    if nt is None:
        nt = len(REMIND_TASKS)
    days = [k for k in rem.keys() if isinstance(rem[k], list) and len(rem[k]) == nt]
    n = len(days)
    full = sum(1 for k in days if sum(rem[k]) == nt)
    per = [sum(1 for k in days if rem[k][i]) for i in range(nt)]
    # 连续全勤天数：今天已全勾从今天数，否则从昨天数
    streak = 0
    d = datetime.date.today()
    t = rem.get(d.isoformat())
    if not (t and sum(t) == nt):
        d -= datetime.timedelta(days=1)
    while rem.get(d.isoformat()) and sum(rem[d.isoformat()]) == nt:
        streak += 1
        d -= datetime.timedelta(days=1)
    # 最近 14 天（含未记录的日期）
    rows = []
    d0 = datetime.date.today()
    for off in range(13, -1, -1):
        dd = d0 - datetime.timedelta(days=off)
        rows.append((dd.strftime('%m-%d'), rem.get(dd.isoformat())))
    return {'n_days': n, 'full': full, 'streak': streak,
            'per': per, 'rows': rows}


def spx_for(size):
    """给定宠物大小，返回精灵图左侧需要的窗口边距"""
    px2 = math.ceil(size * 2) / 2.0
    spw2 = int(round(GW * px2))
    return max(u(20), BAR_TOTAL // 2 + u(4) - spw2 // 2)


SPX = spx_for(SIZE)
CARD_W_L, CARD_H_L = 200, 330      # 设置卡逻辑尺寸（窗口高度需为其让位）
# 窗口宽度要同时容纳：宠物 + 右侧信息区/设置卡；以及以宠物为中心的整条操作条
WIN_W = max(SPX + SPW + u(230), SPX + SPW // 2 + BAR_TOTAL // 2 + u(12))
WIN_H = max(SPH + u(238), u(10) + u(CARD_H_L) + u(12))
SPY = WIN_H - SPH - u(8)

# ---------------- 调色板（小猫）----------------
C = {
    'outline':   '#8a5a3b',   # 暖棕描边
    'body':      '#ffcf96',   # 奶橘色
    'bodyLight': '#ffe9cd',
    'bodyDark':  '#f0ac66',
    'eye':       '#3a3f4a',
    'white':     '#ffffff',
    'cheek':     '#ff9eae',   # 腮红/耳内
    'nose':      '#ff8fa3',
    'whisker':   '#b98a63',
    'mouth':     '#8a5a3b',
    'egg':       '#fff4da',
    'eggSpot':   '#f2d9a6',
    'eggShine':  '#ffffff',
    'eggCrack':  '#c9ad78',
    'sprout':    '#82d97e',
    'sproutDark': '#3e8f4b',
    'sproutLight': '#b6ecae',
    'flower':    '#ffa3c4',
    'flowerCore': '#ffd166',
    'crown':     '#ffd166',
    'crownDark': '#e3ac34',
    'heart':     '#ff8fab',
    'drop':      '#79c6ff',
    'dropLight': '#bfe4ff',
    'food':      '#ffb26b',
    'foodDark':  '#e58b41',
    'spark':     '#ffe066',
}

# ---------------- 成长阶段（按体重划分）----------------
# bw/bh: 身体宽高  hrx/hry: 头部椭圆半径  ear: 耳朵高
STAGES = [
    {'name': '蛋',     'w': 0,    'bw': 0,  'bh': 0,  'hrx': 0,  'hry': 0,  'ear': 0,  'acc': 'none'},
    {'name': '幼崽',   'w': 150,  'bw': 42, 'bh': 36, 'hrx': 22, 'hry': 18, 'ear': 16, 'acc': 'sprout1'},
    {'name': '小少年', 'w': 1000, 'bw': 54, 'bh': 46, 'hrx': 28, 'hry': 22, 'ear': 18, 'acc': 'sprout2'},
    {'name': '少年',   'w': 3000, 'bw': 66, 'bh': 54, 'hrx': 34, 'hry': 28, 'ear': 22, 'acc': 'flower'},
    {'name': '成年体', 'w': 5500, 'bw': 78, 'bh': 64, 'hrx': 40, 'hry': 30, 'ear': 24, 'acc': 'crown'},
]

NAME_POOL = ['团团', '糯米', '豆豆', '布丁', '毛球', '阿米', '小满', '奶昔', '泡芙', '咕噜', '果冻', '芝麻']

# 头饰向上占据的行数（用于计算跳跃最大高度）
ACC_H = {'none': 0, 'sprout1': 19, 'sprout2': 30, 'flower': 38, 'crown': 22}

ENCOURAGE = [
    '今天也要加油哦，我一直在这儿。',
    '你已经很棒啦，真的。',
    '慢慢来，不着急，一步一步就好。',
    '记得喝水，别把自己累坏了。',
    '休息一下也没关系的。',
    '我相信你做得到。',
    '遇到难题就深呼吸，一次解决一个。',
    '你的努力，我都看在眼里。',
    '别对自己太严格啦。',
    '今天天气不错，要开心一点。',
    '你值得所有美好的事情。',
    '累了就靠一会儿，我陪着你。',
    '你走的每一步都算数。',
    '你已经比昨天的自己更好啦。',
    '做不好也没关系，我依然很喜欢你。',
    '把烦心事放一放，先喝口水吧。',
    '你身上有很多别人没有的光。',
    '不用向任何人证明什么。',
    '想休息就休息，我替你守着。',
    '今天的你，也很努力了呢。',
    '种一棵树最好的时间是十年前，其次是现在。',
    '星光不问赶路人，时光不负有心人。',
    '你只管努力，剩下的交给时间。',
    '所有的优秀，都是厚积薄发。',
    '生活明朗，万物可爱，你也是。',
    '愿你眼里有光，心中有暖。',
    '每一个不曾起舞的日子，都是对生命的辜负。',
    '山高路远，看世界，也找自己。',
    '心中有丘壑，眉目作山河。',
    '凡是过往，皆为序章。',
    '乾坤未定，你我皆是黑马。',
    '所谓万丈深渊，下去也是前程万里。',
    '熬过无人问津的日子，才有诗和远方。',
    '花会沿路盛开，你以后的路也是。',
    '不要因为走得太远，而忘记为什么出发。',
    '把日子过成诗，简单而精致。',
    '你的好运正在派件，请保持好心情。',
    '慢慢理解世界，慢慢更新自己。',
    '保持热爱，奔赴山海。',
    '遗憾的事情太多了，所以当下要尽力。',
    '生活原本沉闷，但跑起来就有风。',
    '你要悄悄拔尖，然后惊艳所有人。',
    '追风赶月莫停留，平芜尽处是春山。',
    '最深的黑暗，是黎明前的序曲。',
    '与其临渊羡鱼，不如退而结网。',
    '努力的意义，就是当好运来临的时候，你觉得你值得。',
    '弱者才会诉苦，强者永远寻找方法。',
    '永远不要因为一时的挫折，就否定自己的一生。',
    '世界上只有一种英雄主义，就是看清生活的真相之后依然热爱生活。',
    '失去的东西，其实从来未曾真正地属于你，也不必惋惜。',
    '今天比昨天多学一点点，就是胜利。',
    '成功不是将来才有的，而是从决定去做的那一刻起持续累积。',
    '没有人能替你成长，就像没有人能替你吃饭。',
    '别慌，月亮也正在大海某处迷茫。',
    '允许自己偶尔断电，充电之后继续发光。',
    '别让未来的你，讨厌现在的自己。',
    '再小的个子，也能给大地留下影子。',
    '他强任他强，清风拂山岗。',
    '风雨里做个大人，阳光下做个孩子。',
    '认真你就赢了，虽然过程会很累。',
    '今天的辛苦，是明天的谈资。',
    '一旦停下，就要重新出发，所以慢慢走，别停。',
    '迷茫的时候，选择难走的那条路。',
    '把喜欢的事情做好，就是了不起的人生。',
    '好运藏在努力里，惊喜藏在坚持里。',
    '万事开头难，然后中间难，最后结尾难——但总归会结束，然后变好。',
    '清晨的粥比深夜的酒好喝，骗你的人比爱你的人会说。',
    '做一个温暖的人，浅浅笑，轻轻爱。',
    '你现在的气质里，藏着你走过的路、读过的书。',
    '余生很长，何必慌张。',
    '自信一点，你比你想象的更有力量。',
    '生活总会给你答案，但不会马上把一切都告诉你。',
    '所有的惊艳，都来自长久的努力。',
    '既然选择了远方，便只顾风雨兼程。',
    '没有白走的路，每一步都作数。',
    '来得及，考得上，你可以。',
    '勇敢的人，先享受世界。',
    '允许一切发生，然后继续前行。',
    '你走的路，读的书，最终都会照亮你。',
    '别怕路远，走着走着花就开了。',
    '认真生活的人，运气都不会太差。',
    '疲惫的生活里，总要有些温柔的梦想。',
    '此刻的坚持，是未来回望时的骄傲。',
    '每一个优秀的人，都有一段沉默的时光。',
    '不要等待机会，而要创造机会。',
    '所谓成长，就是把哭声调成静音的过程。',
    '与其担心未来，不如现在好好努力。',
    '懂得感恩的人，人生之路会越走越宽。',
    '平静的大海练不出精悍的水手。',
    '你的负担将变成礼物，你受的苦将照亮你的路。',
    '不要轻言放弃，否则对不起自己。',
    '心中有光，慢食三餐，四季皆安。',
    '优秀的人不是不合群，而是他们合群的人里没有你。',
    '行动是治愈恐惧的良药，犹豫拖延将不断滋养恐惧。',
    '生长的过程，就是不断与自己和解。',
    '把每一个平凡的日子过好，就是不平凡。',
    '命运不会亏待每一个努力的人。',
    '愿你以渺小启程，以伟大结尾。',
    '自律的顶端，是享受孤独。',
    '现在流的汗水，都是明天发光的底气。',
    '请一定要有自信，你就是一道风景。',
]


def pick_encourage(S):
    """选一句鼓励语：30 天内不重复（记录每句最近使用日期）；
    若 30 天内的句子全用完，则选最久没用的一句，且同一句最多连续出现两次"""
    today = day_key()
    cutoff = (datetime.date.fromtimestamp(time_now() / 1000.0)
              - datetime.timedelta(days=30)).isoformat()
    rec = S.get('enc')
    if not isinstance(rec, dict):
        rec = {}
    used = rec.get('used')
    if not isinstance(used, dict):
        used = {}
    used = {k: v for k, v in used.items() if str(v) >= cutoff}
    n = len(ENCOURAGE)
    last1 = rec.get('last')        # 上一句
    last2 = rec.get('last2')       # 上上一句
    avail = [i for i in range(n) if str(i) not in used]
    if not avail:                  # 30 天的句子全说完了 → 从最久没用的里挑
        avail = sorted(range(n), key=lambda i: used.get(str(i), ''))
    if last1 is not None and last1 == last2:   # 上一句已连说两次，必须换
        avail = [i for i in avail if i != last1] or avail
    i = random.choice(avail[:max(1, len(avail) // 2)])   # 优先最久没用的前半段，带点随机
    used[str(i)] = today
    rec['used'] = used
    rec['last2'] = last1
    rec['last'] = i
    S['enc'] = rec
    return ENCOURAGE[i]

MSG = {
    'feed': ['好好吃！谢谢你～', '嗯！是最喜欢的味道！', '吃饱饱，才有力气！', '开心开心，还想再来一口。', '嚼嚼嚼…真幸福。'],
    'overfeed': ['呜…肚肚已经圆滚滚了。', '吃不下啦，先歇一会儿～', '再吃就要变成球了！', '等等再吃好不好？'],
    'water': ['咕嘟咕嘟，好清爽！', '你也记得喝水哦～', '水真好喝。', '喉咙舒服多了！'],
    'play': ['好舒服呀～', '再摸摸头嘛！', '嘿嘿，最喜欢你了。', '呼噜呼噜…', '有你在真好。'],
    'poke': ['嗯？怎么啦～', '我在这里哦。', '想我了是不是？', '戳我干嘛啦～'],
}

RATE = {'full': 100 / 3.0, 'water': 100 / 3.0, 'mood': 100 / 1.0}
# 每小时下降：饱食/水分 3 小时从 100 降到 0；心情 1 小时从 100 降到 0
MAX_OFFLINE = 3600 * 24

# ---------------- 自主动作 ----------------
ACTION_DUR = {'jump': 1300, 'kick': 1550, 'pounce': 1150}   # 毫秒
ACTION_MSG = {
    'jump':   ['看我跳跳跳！', '耶——！', '蹦蹦跳跳～', '开心到飞起来！', '嘿咻！跳！'],
    'kick':   ['接球～踢！', '我的球球！', '大力射门！', '踢——飞你！'],
    'pounce': ['发现猎物！咻—', '扑！', '捕猎模式，启动！', '屁股扭扭…扑！'],
}

# ---------------- 养成规则 ----------------
WEIGHT_START = 200.0          # 领养时体重 200g
GROW_PER_FEED = 30.0          # 每次喂食后总共长 30g（3 小时内慢慢长）
GROW_RATE = GROW_PER_FEED / 3.0   # 基础长肉速度 10g/小时（心情 > 60 时翻倍）
GROW_MS = 3 * 3600 * 1000     # 一顿饭慢慢消化长肉的时间：3 小时
MOOD_FAST = 60.0              # 心情高于此值时，长肉速度翻倍
WEIGHT_GOLD = 8000.0          # 8000g 毛色变金
FEED_CD_MS = 3 * 3600 * 1000  # 投喂间隔：3 小时（喂食/喝水共用）
HUNGRY_MS = 6 * 3600 * 1000   # 超过 6 小时没投喂（粮或水）→ 躺倒不开心

# 毛色：灰褐（幼）→ 金色（8000g），按体重在两端色板间插值
COAT_START = {'outline': '#5f5044', 'body': '#a99a89', 'bodyLight': '#cfc3b4',
              'bodyDark': '#8a7a69', 'whisker': '#8d7f70', 'mouth': '#5f5044'}
COAT_GOLD = {'outline': '#9c6b1d', 'body': '#ffce54', 'bodyLight': '#ffe9a8',
             'bodyDark': '#e2a72e', 'whisker': '#c99a3f', 'mouth': '#9c6b1d'}
# 母猫毛色：红色（幼）→ 蓝色（8000g）；公猫：灰褐（幼）→ 金色
COAT_RED = {'outline': '#a34a3c', 'body': '#f58a70', 'bodyLight': '#ffc9b4',
            'bodyDark': '#d9634b', 'whisker': '#e09180', 'mouth': '#a34a3c'}
COAT_BLUE = {'outline': '#3d6ba6', 'body': '#8db9e9', 'bodyLight': '#d3e7fb',
             'bodyDark': '#5f8fc7', 'whisker': '#79a5d2', 'mouth': '#3d6ba6'}

COAT_FEMALE = False         # 当前猫是否为母猫（决定终点毛色）；启动/领养时更新


def coat_t(w):
    return clamp((float(w) - WEIGHT_START) / (WEIGHT_GOLD - WEIGHT_START), 0, 1)


def apply_coat(w, female=None):
    """按体重把毛色写进调色板 C（每次渲染前调用）；母猫红→蓝，公猫灰褐→金"""
    if female is None:
        female = COAT_FEMALE
    t = coat_t(w)
    src = COAT_RED if female else COAT_START
    tgt = COAT_BLUE if female else COAT_GOLD
    for k in COAT_START:
        a = hex_rgb(src[k])
        b = hex_rgb(tgt[k])
        C[k] = '#%02x%02x%02x' % tuple(
            int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def coat_label(w, female=None):
    if female is None:
        female = COAT_FEMALE
    t = coat_t(w)
    if t >= 1:
        return '蓝色' if female else '金色'
    return ('红→蓝 %d%%' if female else '灰褐→金 %d%%') % int(t * 100)


def fmt_dur(ms):
    m = int(math.ceil(ms / 60000.0))
    if m < 60:
        return '%d 分钟' % m
    h, mm = m // 60, m % 60
    return '%d 小时 %d 分钟' % (h, mm) if mm else '%d 小时' % h


def pet_lied(S):
    """超过 HUNGRY_MS 没投喂(粮或水) → 躺倒不开心（蛋不会躺）"""
    lf = S.get('lastFeed')
    if not lf:
        return False
    if stage_index(float(S.get('weight') or WEIGHT_START)) == 0:
        return False
    return (time_now() - float(lf)) > HUNGRY_MS


# =========================================================
#  像素绘制原语（作用于栅格）
# =========================================================
def new_grid():
    return [[None] * GW for _ in range(GH)]


def put(g, x, y, color):
    x, y = int(round(x)), int(round(y))
    if 0 <= x < GW and 0 <= y < GH:
        g[y][x] = color


def rect(g, x, y, w, h, color):
    for j in range(int(round(y)), int(round(y + h))):
        for i in range(int(round(x)), int(round(x + w))):
            put(g, i, j, color)


def disc(g, cx, cy, rx, ry, color):
    xs = range(-rx, rx + 1) if rx > 0 else [0]
    ys = range(-ry, ry + 1) if ry > 0 else [0]
    for j in ys:
        for i in xs:
            if rx > 0 and ry > 0 and (i * i) / (rx * rx) + (j * j) / (ry * ry) > 1:
                continue
            put(g, cx + i, cy + j, color)


def blob(g, cx, ground, bw, bh, color):
    """圆顶方块：底部平、顶部圆"""
    bx = int(round(cx - bw / 2))
    half = (bw - 1) / 2 or 1
    for i in range(bw):
        t = (i - half) / half
        off = int(round(bh * 0.42 * t * t))
        rect(g, bx + i, ground - bh + off, 1, bh - off, color)


def qbez(p0, p1, p2, n=16):
    """二次贝塞尔曲线采样点"""
    pts = []
    for i in range(n + 1):
        t = i / n
        a = (1 - t) ** 2
        b = 2 * (1 - t) * t
        c = t * t
        pts.append((a * p0[0] + b * p1[0] + c * p2[0],
                    a * p0[1] + b * p1[1] + c * p2[1]))
    return pts


def tri(g, cx, bottom, h, w, color):
    """尖朝上的三角（耳朵）"""
    for r in range(h):
        ww = max(1, int(round(w * (r + 1) / h)))
        rect(g, cx - (ww >> 1), bottom - h + r, ww, 1, color)


def crescent_pts(cx, cy, r, n=20):
    """弯弯月亮的轮廓点（外弧 + 内弧拼成月牙）"""
    pts = []
    for i in range(n + 1):
        a = math.radians(74 + 212.0 * i / n)
        pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
    for i in range(n + 1):
        b = math.radians(254 - 148.0 * i / n)
        pts += [cx + 0.55 * r + r * math.cos(b), cy + r * math.sin(b)]
    return pts


def draw_eye(g, cx, cy, s):
    o = (s - 1) >> 1
    rect(g, cx - o, cy - o, s, s, C['eye'])
    if s >= 5:                        # 大眼睛削角更圆润
        put(g, cx - o, cy - o, C['body'])
        put(g, cx + o, cy - o, C['body'])
        put(g, cx - o, cy + o, C['body'])
        put(g, cx + o, cy + o, C['body'])
        put(g, cx - o + 1, cy - o, C['white'])
        put(g, cx - o + 1, cy - o + 1, C['white'])
    else:
        put(g, cx - o, cy - o, C['white'])


# =========================================================
#  宠物绘制
# =========================================================
def draw_accessory(g, acc, x, top):
    """top = 头顶所在行"""
    if acc == 'sprout1':
        # 粗壮的小草：深绿茎 + 两片饱满亮叶
        rect(g, x - 1, top - 14, 3, 14, C['sproutDark'])
        disc(g, x - 4, top - 16, 4, 3, C['sprout'])
        disc(g, x + 4, top - 12, 4, 3, C['sprout'])
        put(g, x - 7, top - 18, C['sprout'])
        put(g, x + 7, top - 10, C['sprout'])
        put(g, x, top - 16, C['sproutLight'])
    elif acc == 'sprout2':
        rect(g, x - 1, top - 22, 3, 22, C['sproutDark'])
        disc(g, x - 7, top - 26, 6, 4, C['sprout'])
        disc(g, x + 7, top - 18, 6, 4, C['sprout'])
        rect(g, x - 4, top - 30, 2, 6, C['sprout'])
        rect(g, x + 2, top - 26, 2, 6, C['sprout'])
        put(g, x, top - 24, C['sproutLight'])
    elif acc == 'flower':
        rect(g, x, top - 24, 2, 24, C['sproutDark'])
        disc(g, x - 6, top - 32, 6, 4, C['flower'])
        disc(g, x + 6, top - 32, 6, 4, C['flower'])
        put(g, x, top - 38, C['flower'])
        put(g, x, top - 26, C['flower'])
        put(g, x, top - 32, C['flowerCore'])
    elif acc == 'crown':
        wy = top - 20
        rect(g, x - 12, wy + 8, 26, 8, C['crown'])
        put(g, x - 12, wy + 6, C['crown'])
        put(g, x, wy + 2, C['crown'])
        put(g, x + 12, wy + 6, C['crown'])
        rect(g, x - 12, wy + 14, 26, 2, C['crownDark'])
        put(g, x, wy + 12, C['flowerCore'])


def draw_egg(g, t, st):
    wob = 1 if math.sin(t / 430.0) > 0.6 else 0
    ox = int(round(math.sin(t / 430.0) * 2.4))
    cy = FOOT - 30 + wob * 2
    disc(g, CX + ox, cy, 28, 34, '#d9b28c')
    disc(g, CX + ox, cy, 26, 32, C['egg'])
    for dx, dy in ((-10, -12), (6, -6), (-6, 6), (10, 10), (4, -18), (-16, 4)):
        put(g, CX + ox + dx, cy + dy, C['eggSpot'])
    put(g, CX + ox - 10, cy - 18, C['eggShine'])
    put(g, CX + ox - 10, cy - 16, C['eggShine'])
    put(g, CX + ox - 8, cy - 22, C['eggShine'])
    # 快孵化（第一顿饭 100→150g）时出现裂纹
    pct = clamp((float(st.get('weight') or WEIGHT_START) - WEIGHT_START)
                / GROW_PER_FEED, 0, 1)
    if pct > 0.6:
        for dx, dy in ((-6, -4), (-4, 0), (-2, -4), (0, 0), (2, -4), (4, 0), (6, -4)):
            put(g, CX + ox + dx, cy + 6 + dy, C['eggCrack'])
    disc(g, CX, FOOT + 6, 20, 4, '#e8ddca')


def draw_fur(g, cx, gy, bw, bh, t):
    """背脊毛：随体重(100g→8000g)从无到浓密变长"""
    if t < 0.04:
        return
    n = 3 + int(t * 5)                    # 3~8 撮
    fh = 2 + int(round(t * 8))            # 毛长 2~10 栅格px
    half = (bw - 1) / 2.0 or 1
    for i in range(n):
        x = int(cx - bw // 2 + 6 + i * (bw - 12) / max(1, n - 1))
        tt = (x - cx) / half
        top = gy - bh + int(round(bh * 0.42 * tt * tt))
        tri(g, x, top, fh, 6, C['body'])


def draw_cat(g, t, st, si, sad, lying=False, action=None, at=0, sleep=False, cx=CX, wl=True, wr=True, scale=1.0):
    """绘制小猫：坐姿/趴姿、尖耳、胡须、ω嘴、上翘的尾巴；action: jump/kick/pounce；
    scale: 整体缩放（串门时等级高的猫会显得更高更大一点）"""
    stage = STAGES[si]
    w = float(st.get('weight') or WEIGHT_START)
    fur_t = coat_t(w)
    bw, bh = stage['bw'], stage['bh']
    hrx, hry = stage['hrx'], stage['hry']
    if scale != 1.0:
        bw = max(24, int(round(bw * scale)))
        bh = max(16, int(round(bh * scale)))
        hrx = max(10, int(round(hrx * scale)))
        hry = max(8, int(round(hry * scale)))

    # ---- 动作姿态：lift(整体抬升) squash(身体压扁系数) ball(球位置) ----
    lift, squash, ball, kick_paw = 0, 1.0, None, False
    if action == 'jump':
        # 两次抛物线小跳：高跳 + 矮跳
        if at < 600:
            u = at / 600.0
            lift = -int(round(30 * 4 * u * (1 - u)))
        elif at < 1250:
            u = (at - 600) / 650.0
            lift = -int(round(18 * 4 * u * (1 - u)))
    elif action == 'pounce':
        # 捕猎：压低屁股左右扭 → 纵身一扑 → 落地缓冲
        if at < 520:
            squash = 0.74 + 0.04 * math.sin(at / 55.0)
        elif at < 880:
            u = (at - 520) / 360.0
            lift = -int(round(26 * 4 * u * (1 - u)))
            squash = 1.06
        else:
            squash = 0.86
    elif action == 'kick':
        # 球从右侧滚入 → 飞出右上角（带速度线）
        kick_paw = 380 <= at < 900
        bx1, bx0 = cx + 54, GW - 18
        if at < 520:
            u = at / 520.0
            u = u * u * (3 - 2 * u)          # smoothstep：滚入减速
            ball = (bx1 + (bx0 - bx1) * u, FOOT + 2, False, u)
        elif at < 1500:
            u = (at - 520) / 980.0
            ball = (bx1 + (GW + 12 - bx1) * u,
                    FOOT + 2 - 68 * 4 * u * (1 - u), True, u)
    if squash != 1.0:
        bh = max(16, int(round(bh * squash)))
        bw = max(24, int(round(bw * (2.0 - squash))))
    # 跳跃高度受头顶空间限制（大猫戴花/冠时栅格上部余量小）
    if lift < 0:
        top_row = min(FOOT - stage['bh'] - 2 * hry + 14 - stage['ear'],
                      FOOT - stage['bh'] - 2 * hry + 8 - ACC_H[stage['acc']])
        lift = max(lift, -(top_row - 1))

    bob = 0 if lying else int(round(math.sin(t / 390.0) * 3.6))
    gy = FOOT + bob + lift

    # 影子（跳起时缩小；躺床上时不需要影子）
    sh_k = 1.0 - min(0.45, -lift / 68.0)
    if not sleep:
        if lying:
            disc(g, cx, FOOT + 6, int((bw + 16) * 0.6), 4, '#ecdcc4')
        else:
            disc(g, cx, FOOT + 6, max(8, int(bw * 0.55 * sh_k)), 4, '#ecdcc4')

    thick = max(1, int(round(bw / 12.0)))
    if lying:
        # 趴姿：尾巴沿地面向身前卷，尾尖轻轻晃
        lsw = math.sin(t / 300.0) * 3
        pts = qbez((cx + bw // 2 - 8, gy - 10), (cx + bw // 2 + 20, gy + 2 + lsw),
                   (cx - 20, gy + 4))
        for (x, y) in pts:
            disc(g, x, y, thick + 1, max(1, thick), C['outline'])
        for (x, y) in pts:
            disc(g, x, y, thick, max(1, thick - 1), C['bodyDark'])
        # 身体压扁成"猫面包"
        bw2, bh2 = bw + 16, max(16, int(bh * 0.52))
        blob(g, cx, gy, bw2 + 4, bh2 + 4, C['outline'])
        blob(g, cx, gy, bw2, bh2, C['body'])
        draw_fur(g, cx, gy, bw2, bh2, fur_t)
        hx = cx
        hy = gy - bh2 - hry + 10
        # 前爪收在下巴下
        fd = int(bw * 0.30)
        disc(g, cx - fd, gy - 2, 6, 4, C['bodyDark'])
        disc(g, cx + fd, gy - 2, 6, 4, C['bodyDark'])
    else:
        # 长尾巴（先画，在身体后面；根部贴身体右缘，主体露在身体外侧）
        # 尾巴会左右摆动：平时慢悠悠，做动作时甩得更快更欢
        if action:
            sw = math.sin(t / 130.0) * 6
        else:
            sw = math.sin(t / 300.0) * 3
        k = bw / 78.0
        tth = max(1, int(round(bw / 24.0)))   # 细尾巴
        p0 = (cx + bw // 2 + 1, gy - 12)
        p1 = (p0[0] + 26 * k, gy - 4)
        p2 = (p0[0] + 26 * k + sw, gy - bh + 4)
        pts = qbez(p0, p1, p2, 40)
        # 尾尖向内勾一个小弯，随摆动同步晃
        p3 = (p2[0] - 5 * k - sw * 0.5, p2[1] - 4)
        p4 = (p2[0] - 11 * k - sw, p2[1] - 1)
        pts += qbez(p2, p3, p4, 16)
        n = len(pts)
        # 根粗尖细连续过渡（比阶梯 taper 更光滑），采样更密避免坑洼
        def _tr(i):
            return max(1, int(round(tth * (1.0 - 0.5 * i / (n - 1)))))
        for i, (x, y) in enumerate(pts):
            r = _tr(i)
            disc(g, x, y, r + 1, r, C['outline'])
        for i, (x, y) in enumerate(pts):
            r = _tr(i)
            disc(g, x, y, r, max(1, r - 1), C['bodyDark'])
        # 白色尾尖，更可爱
        for i in range(int(n * 0.8), n):
            x, y = pts[i]
            r = _tr(i)
            if r >= 2:
                disc(g, x, y, r - 1, max(1, r - 2), C['bodyLight'])

        # 身体（坐姿：圆顶方块）
        blob(g, cx, gy, bw + 4, bh + 4, C['outline'])
        blob(g, cx, gy, bw, bh, C['body'])
        draw_fur(g, cx, gy, bw, bh, fur_t)
        # 肚皮
        disc(g, cx, gy - int(bh * 0.32), max(6, int(bw * 0.24)),
             max(6, int(bh * 0.26)), C['bodyLight'])

        hx = cx
        hy = gy - bh - hry + 8
        # 前爪
        fd = int(bw * 0.30)
        disc(g, cx - fd, gy + 2, 6, 4, C['bodyDark'])
        disc(g, cx + fd, gy + 2, 6, 4, C['bodyDark'])
        put(g, cx - fd, gy, C['body'])
        put(g, cx + fd, gy, C['body'])
        # 踢球：右前爪向前伸出
        if kick_paw:
            disc(g, cx + fd + 8, gy - 6, 6, 4, C['outline'])
            disc(g, cx + fd + 8, gy - 6, 4, 2, C['body'])

    # 头
    disc(g, hx, hy, hrx + 2, hry + 2, C['outline'])
    disc(g, hx, hy, hrx, hry, C['body'])
    disc(g, hx - int(hrx * 0.4), hy - int(hry * 0.45),
         max(6, int(hrx * 0.22)), max(4, int(hry * 0.18)), C['bodyLight'])

    # 耳朵（迷你尖三角 + 粉色内耳）
    ear_h = max(6, int(round(stage['ear'] * 0.42 * scale)))
    ear_w = max(4, int(round(hrx * 0.18)))
    exl = hx - int(hrx * 0.52)
    exr = hx + int(hrx * 0.52)
    base = hy - hry + 6
    tri(g, exl, base + 2, ear_h + 2, ear_w * 2 + 4, C['outline'])
    tri(g, exr, base + 2, ear_h + 2, ear_w * 2 + 4, C['outline'])
    tri(g, exl, base, ear_h, ear_w * 2, C['body'])
    tri(g, exr, base, ear_h, ear_w * 2, C['body'])
    iy = base - max(3, int(round(ear_h * 0.42)))     # 粉色内耳随耳朵大小自适应
    put(g, exl, iy, C['cheek'])
    put(g, exl, iy + 2, C['cheek'])
    put(g, exl + 2, iy + 2, C['cheek'])
    put(g, exr, iy, C['cheek'])
    put(g, exr, iy + 2, C['cheek'])
    put(g, exr - 2, iy + 2, C['cheek'])

    # 脸
    eye_y = hy - 2
    eye_dx = max(6, int(hrx * 0.45))
    eye_s = 10 if hrx >= 26 else 8
    blinking = lying or sleep or (t % 3700) < 140   # 趴着/睡觉时闭着眼
    if blinking:
        rect(g, cx - eye_dx - eye_s // 2, eye_y, eye_s, 2, C['eye'])
        rect(g, cx + eye_dx - eye_s // 2, eye_y, eye_s, 2, C['eye'])
    else:
        draw_eye(g, cx - eye_dx, eye_y, eye_s)
        draw_eye(g, cx + eye_dx, eye_y, eye_s)

    # 鼻子 + 嘴
    disc(g, cx, hy + 2, 2, 2, C['nose'])
    my = hy + 8
    wide = hrx >= 26
    if sad:
        if wide:
            for dx, dy in ((-6, 2), (-4, 0), (-2, 0), (0, 0), (2, 0), (4, 0), (6, 2)):
                put(g, cx + dx, my + dy, C['mouth'])
        else:
            for dx, dy in ((-4, 2), (-2, 0), (0, 0), (2, 0), (4, 2)):
                put(g, cx + dx, my + dy, C['mouth'])
    elif (st['mood'] >= 70 or action) and not lying and not sleep:
        # ω 猫嘴（做动作时永远开心）
        for dx, dy in ((-6, 0), (-4, 2), (-2, 2), (0, 0), (2, 2), (4, 2), (6, 0)):
            put(g, cx + dx, my + dy, C['mouth'])
    else:
        rect(g, cx - 4, my, 9, 2, C['mouth'])

    # 腮红
    if not sad and not sleep:
        chx = int(hrx * 0.72)
        for dx in (-2, -1, 0, 1, 2):
            put(g, cx - chx + dx, my - 2, C['cheek'])
            put(g, cx + chx + dx, my - 2, C['cheek'])

    # 胡须（左右各两根，末端微微下垂）；串门牵手时可关掉朝向对方那一侧
    wx0 = hx + hrx + 2
    for i, dy in enumerate((0, 6)):
        ln = 16 - 4 * i
        for j in range(ln):
            dy2 = 2 if j >= ln - 6 else 0
            if wr:
                put(g, wx0 + j, hy + 2 + dy + dy2, C['whisker'])
            if wl:
                put(g, hx - hrx - 2 - j, hy + 2 + dy + dy2, C['whisker'])

    # 饿倒提醒标记（头顶两个小感叹号；睡觉时不出现）
    if lying and not sleep:
        zx, zy = hx + hrx + 6, hy - hry - 12
        for ox in (0, 8):
            rect(g, zx + ox, zy, 2, 8, '#e26d5a')
            put(g, zx + ox, zy + 10, '#e26d5a')

    # 踢球的小皮球（最后画，盖在猫前面）
    if ball:
        bx, by, flying, roll = ball
        disc(g, bx, by, 8, 6, C['outline'])
        disc(g, bx, by, 6, 4, '#e8595c')
        # 滚动/旋转的花纹块
        if flying:
            put(g, bx - 2, by, '#ffffff')
            put(g, bx, by - 2, '#ffffff')
            for i in range(3):                       # 速度线
                rect(g, bx - 18 - i * 6, by - 2 * i, 4, 2, C['whisker'])
        else:
            px0 = int(round(bx + 4 * math.cos(roll * 9.0)))
            rect(g, px0 - 2, by - 2, 4, 4, '#ffffff')
        put(g, bx - 4, by - 2, '#ffd0d2')

    draw_accessory(g, stage['acc'], cx, hy - hry)


def draw_bed(g, si, cx=CX):
    """一张小床（床头板 + 床尾板 + 床架 + 被褥 + 被子 + 枕头），画在睡觉的小猫下面"""
    st = STAGES[si]
    hw = (st['bw'] + 16) // 2 + 16
    x1, x2 = cx - hw, cx + hw
    y0 = FOOT - 6                              # 被面
    y1 = FOOT + 18                             # 床脚
    # 床头板（左侧，略高出被面）与床尾板
    rect(g, x1 - 8, y0 - 9, 7, (y1 - y0) + 9, '#c08a5a')
    rect(g, x1 - 8, y0 - 9, 7, 3, '#d8a273')
    rect(g, x2 + 1, y0 - 3, 6, (y1 - y0) + 3, '#c08a5a')
    # 床架（木色）
    rect(g, x1 - 3, y0 + 6, x2 - x1 + 6, y1 - y0 - 6, '#c08a5a')
    rect(g, x1 - 3, y1 - 7, x2 - x1 + 6, 7, '#a2714a')
    # 被褥
    rect(g, x1, y0 + 8, x2 - x1, y1 - y0 - 12, '#eaf4ff')
    rect(g, x1, y0 + 8, x2 - x1, 3, '#cfe3f7')
    # 粉色被角（右侧盖一小条）
    bx = cx - hw // 3
    rect(g, bx, y0 + 4, x2 - bx - 1, 11, '#ffd7e0')
    rect(g, bx, y0 + 4, x2 - bx - 1, 3, '#ffc2d1')
    # 枕头（左侧，垫在脑袋下）
    disc(g, x1 + 14, y0 + 5, 12, 6, '#ffffff')
    disc(g, x1 + 14, y0 + 5, 9, 4, '#fff2f5')


def draw_scenery(g):
    """普通待机时的背景：左边三座小房子（高矮错落）+ 右边五棵高低不齐的树
    （画在猫身后，喂食/喝水/抚摸/睡觉/晒太阳/玩耍时不显示）"""
    # ---- 大房子（左后，红瓦+烟囱）----
    rect(g, 24, 76, 4, 20, '#a86a4c')                # 烟囱（先画，屋顶盖住底部）
    rect(g, 24, 76, 4, 2, '#8f573d')
    for i in range(18):                              # 红瓦屋顶（三角）
        hw = 2 + i
        rect(g, 17 - hw, 82 + i, hw * 2, 1, '#c9704d')
    rect(g, 1, 99, 33, 3, '#b45f3f')                 # 屋檐
    rect(g, 4, 102, 26, 54, '#f6e9c9')               # 墙
    rect(g, 4, 102, 26, 2, '#e3d0a8')
    rect(g, 12, 138, 8, 18, '#b98a63')               # 门
    rect(g, 12, 138, 8, 2, '#a3764f')
    put(g, 19, 147, '#ffd166')                       # 门把手
    rect(g, 21, 112, 8, 8, '#9fd8f2')                # 窗户
    rect(g, 21, 112, 8, 1, '#7fb8d4')
    rect(g, 24, 113, 1, 7, '#e8f4fb')
    # ---- 小房子（左前，土黄瓦，矮）----
    for i in range(12):                              # 土黄屋顶
        hw = 2 + int(i * 0.7)
        rect(g, 7 - hw, 106 + i, hw * 2, 1, '#c9a04d')
    rect(g, 0, 117, 15, 2, '#a3822f')                # 屋檐
    rect(g, 1, 119, 13, 37, '#f0ded4')               # 墙
    rect(g, 4, 126, 6, 6, '#9fd8f2')                 # 小窗
    rect(g, 4, 126, 6, 1, '#7fb8d4')
    # ---- 小房子（右前，蓝屋顶）----
    for i in range(15):                              # 蓝瓦屋顶
        hw = 2 + int(i * 0.85)
        rect(g, 41 - hw, 98 + i, hw * 2, 1, '#7f9fc4')
    rect(g, 28, 112, 26, 2, '#5f7d9c')               # 屋檐
    rect(g, 30, 114, 22, 42, '#f3dccc')              # 墙
    rect(g, 30, 114, 22, 2, '#dcc0b2')
    rect(g, 44, 140, 7, 16, '#b98a63')               # 门
    put(g, 50, 148, '#ffd166')
    rect(g, 33, 122, 8, 7, '#9fd8f2')                # 窗户
    rect(g, 33, 122, 8, 1, '#7fb8d4')
    rect(g, 36, 123, 1, 6, '#e8f4fb')
    # ---- 五棵高低不齐的树（右）----
    rect(g, 158, 144, 4, 12, '#a07a52')              # 小树1（最矮）
    disc(g, 160, 138, 6, 5, '#a5d98f')
    disc(g, 160, 132, 4, 4, '#b4e39d')
    rect(g, 169, 120, 6, 36, '#9a6b45')              # 高树（最高）
    rect(g, 169, 120, 2, 36, '#855a39')
    disc(g, 172, 108, 12, 11, '#6fb85f')
    disc(g, 163, 116, 8, 7, '#7ec26e')
    disc(g, 181, 116, 8, 7, '#7ec26e')
    disc(g, 172, 95, 8, 7, '#8fcd7c')
    rect(g, 182, 128, 5, 28, '#9a6b45')              # 中树
    rect(g, 182, 128, 2, 28, '#855a39')
    disc(g, 184, 116, 10, 9, '#7ec26e')
    disc(g, 184, 106, 6, 5, '#8fcd7c')
    rect(g, 192, 138, 5, 18, '#a07a52')              # 小树2
    disc(g, 194, 131, 7, 6, '#8fcd7c')
    disc(g, 194, 124, 4, 4, '#a5d98f')
    rect(g, 201, 146, 4, 10, '#a07a52')              # 小树3（贴右边）
    disc(g, 203, 140, 6, 5, '#a5d98f')


def draw_pet(g, t, st, action=None, at=0, pose=None, scenery=False):
    """st: state dict；pose: None / 'sleep'(睡觉) / 'sun'(晒太阳)；
    scenery: True 时在猫身后画小房子和小树（仅普通待机状态）"""
    w = float(st.get('weight') or WEIGHT_START)
    apply_coat(w)
    si = stage_index(w)
    if si == 0:
        draw_egg(g, t, st)
        return
    if scenery:
        draw_scenery(g)              # 先画背景，猫叠在上面
    sleep = (pose == 'sleep')
    lying = pet_lied(st) or sleep
    sad = (not sleep) and (st['mood'] < 35 or st['full'] < 18
                           or st['water'] < 18 or pet_lied(st))
    if sleep:
        draw_bed(g, si)              # 先铺床，猫再躺上去
    draw_cat(g, t, st, si, sad, lying,
             action=None if lying else action, at=at, sleep=sleep)


# =========================================================
#  串门：门（敲门） / 两只猫牵手
# =========================================================
def draw_heart(g, x, y, col, r=2):
    """小爱心"""
    if r >= 2:
        put(g, x - 2, y - 2, col)
        put(g, x - 1, y - 3, col)
        put(g, x, y - 3, col)
        put(g, x + 1, y - 2, col)
        rect(g, x - 2, y - 1, 5, 2, col)
        put(g, x - 1, y + 1, col)
        put(g, x, y + 1, col)
        put(g, x, y + 2, col)


def draw_door(g, t, peer='好友'):
    """好友来敲门：小猫变成一扇木门，咚咚咚地敲"""
    x1, x2 = CX - 32, CX + 32
    w = x2 - x1 + 1
    yt, yb = FOOT - 84, FOOT + 10
    hit = math.sin(t / 260.0)
    knocked = hit > 0.72                       # 敲到门上的一瞬间
    dx = 1 if knocked else 0                   # 门被敲得轻轻一颤
    # 地面影子 + 门口地垫
    disc(g, CX, FOOT + 12, 40, 5, '#ecdcc4')
    rect(g, x1 - 8, yb - 2, w + 16, 6, '#b98a63')
    rect(g, x1 - 8, yb - 2, w + 16, 2, '#cfa274')
    # 门框
    rect(g, x1 - 6, yt - 8, w + 12, yb - yt + 8, C['outline'])
    rect(g, x1 - 3, yt - 5, w + 6, yb - yt + 3, '#b9814a')
    # 门板
    rect(g, x1 + dx, yt, w, yb - yt, '#d9a066')
    rect(g, x1 + dx, yt, w, 3, '#e8b87f')
    rect(g, x1 + dx, yt, 2, yb - yt, '#e8b87f')
    rect(g, x1 + w - 2 + dx, yt, 2, yb - yt, '#c0834a')
    # 两块门芯板
    for py, ph in ((yt + 9, 26), (yt + 42, 29)):
        rect(g, x1 + 7 + dx, py, w - 14, ph, '#c8905c')
        rect(g, x1 + 7 + dx, py, w - 14, 2, '#b57c48')
    # 门把手
    disc(g, x2 - 9, (yt + yb) // 2, 3, 3, '#ffd166')
    put(g, x2 - 10, (yt + yb) // 2 - 1, '#fff0c2')
    # 门上的小爱心门牌
    draw_heart(g, CX, yt - 16, C['heart'])
    # 敲门的小爪子（在门右侧来回敲）
    fx = x2 + 3 + int(round(9 * (1 - abs(hit))))
    fy = yb - 34
    disc(g, fx, fy, 7, 6, C['outline'])
    disc(g, fx, fy, 5, 4, C['body'])
    put(g, fx - 2, fy - 2, C['bodyLight'])
    for ox in (-3, 0, 3):                      # 三根小指头
        put(g, fx + ox, fy + 4, C['outline'])
    if knocked:                                # 敲击的波纹与星星
        for r, col in ((6, '#ffe27a'), (10, '#f7d488')):
            for a in (-38, 0, 38):
                aa = math.radians(a)
                put(g, fx - 4 + math.cos(aa) * r * 0.6,
                    fy - math.sin(aa) * r * 0.7, col)
        rect(g, x2 + 2, fy - 20, 2, 5, '#ffd166')
        rect(g, x2 + 8, fy - 24, 2, 5, '#ffd166')
        put(g, x2 + 12, fy - 14, '#ffd166')


def draw_together(g, t, S, pst, action=None, at=0, pose=None):
    """串门中：两只猫并排牵手一起玩（左边是我，右边是好友的猫）"""
    wm = float(S.get('weight') or WEIGHT_START)
    si_m = stage_index(wm)
    if si_m == 0:                       # 蛋不能出门（上层已拦，这里兜底）
        draw_pet(g, t, S, action, at, pose)
        return
    pst = pst or {}
    pw = float(pst.get('weight') or wm)
    si_p = stage_index(pw)
    if si_p == 0:
        si_p = si_m
    # 等级高的猫要比另一只更高更大一点（每高 1 级 +6%，最多 +18%）
    sc_m = visit_scale(wm, pw)
    sc_p = visit_scale(pw, wm)
    bwm = STAGES[si_m]['bw'] * sc_m
    bwp = STAGES[si_p]['bw'] * sc_p
    off = max(26.0, (bwm + bwp) / 4.0 + 4.0)
    cxm, cxp = CX - off, CX + off
    sleep = (pose == 'sleep')
    act = None if sleep else action

    if sleep:                                   # 两张小床拼在一起
        draw_bed(g, si_m, cxm)
        draw_bed(g, si_p, cxp)

    # ---- 我的猫（左）----
    apply_coat(wm)
    out_m, body_m = C['outline'], C['body']
    dark_m, light_m = C['bodyDark'], C['bodyLight']
    sad_m = (S['mood'] < 35 or S['full'] < 18 or S['water'] < 18 or pet_lied(S))
    draw_cat(g, t, S, si_m, sad_m, sleep, act, at=at, sleep=sleep,
             cx=int(round(cxm)), wl=True, wr=False, scale=sc_m)

    # ---- 好友的猫（右）----
    # 好友的猫按它自己的性别定毛色（母猫 → 蓝色）
    apply_coat(pw, female=str((S.get('partner') or {}).get('gender')
                              or '公') == '母')
    out_p, body_p = C['outline'], C['body']
    dark_p = C['bodyDark']
    pS = {'weight': pw, 'mood': float(pst.get('mood') or 80),
          'full': float(pst.get('full') or 80), 'water': float(pst.get('water') or 80),
          'lastFeed': pst.get('lastfeed') or time_now()}
    sad_p = (pS['mood'] < 35 or pS['full'] < 18 or pS['water'] < 18)
    draw_cat(g, t, pS, si_p, sad_p, sleep, act, at=at, sleep=sleep,
             cx=int(round(cxp)), wl=False, wr=True, scale=sc_p)
    apply_coat(wm)                       # 还原自己的毛色（粒子等后续绘制用）

    if sleep:
        return
    # ---- 牵在一起的小爪 + 中间的小爱心 ----
    sway = int(round(math.sin(t / 430.0) * 2))
    hand_y = FOOT - 22 + sway
    for (c, sgn, out, body, dark) in ((cxm, 1, out_m, body_m, dark_m),
                                      (cxp, -1, out_p, body_p, dark_p)):
        sx = c + sgn * int(round(STAGES[si_m if sgn > 0 else si_p]['bw'] * 0.30))
        pts = qbez((sx, FOOT - 6), (sx + sgn * 12, hand_y + 10),
                   (CX - sgn * 5, hand_y), 14)
        for (x, y) in pts:
            disc(g, x, y, 3, 3, out)
        for (x, y) in pts:
            disc(g, x, y, 2, 2, body if (x + y + sgn) % 2 else dark)
        disc(g, sx, FOOT - 4, 5, 4, out)
        disc(g, sx, FOOT - 4, 4, 3, dark)
    # 牵着的手
    disc(g, CX, hand_y, 7, 6, out_m)
    disc(g, CX, hand_y, 5, 4, body_m)
    disc(g, CX - 2, hand_y, 3, 3, body_p)
    put(g, CX, hand_y - 2, light_m)
    # 头顶飘一颗恋爱（友情）的小心心
    pulse = 1 + (1 if math.sin(t / 520.0) > 0.4 else 0)
    draw_heart(g, CX, hand_y - 16 - pulse, C['heart'], r=pulse + 1)


def draw_particles(g, parts):
    for p in parts:
        a = 1.0 - p['life'] / p['max']
        if a <= 0:
            continue
        # 通过向底色混合模拟淡出（像素画无 alpha）
        X, Y = int(round(p['x'])), int(round(p['y']))
        k = p['type']
        if k == 'heart':
            put(g, X - 2, Y - 2, C['heart'])
            put(g, X + 2, Y - 2, C['heart'])
            rect(g, X - 2, Y - 1, 5, 2, C['heart'])
            rect(g, X - 1, Y + 1, 3, 1, C['heart'])
            put(g, X, Y + 2, C['heart'])
        elif k == 'drop':
            put(g, X, Y - 2, C['drop'])
            rect(g, X - 1, Y - 1, 3, 2, C['drop'])
        elif k == 'food':
            rect(g, X - 2, Y - 2, 4, 4, C['food'])
            put(g, X, Y, C['foodDark'])
        elif k == 'spark':
            rect(g, X - 2, Y, 5, 1, C['spark'])
            rect(g, X, Y - 2, 1, 5, C['spark'])
        elif k == 'sweat':
            put(g, X, Y, C['drop'])
            rect(g, X, Y - 2, 1, 2, C['dropLight'])


# =========================================================
#  养成数值
# =========================================================
def clamp(v, a, b):
    return a if v < a else (b if v > b else v)


def level_info(exp):
    lv, need, base = 1, 40, 0
    while exp >= base + need:
        base += need
        lv += 1
        need = int(round(need * 1.35))
    return {'lv': lv, 'base': base, 'need': need, 'pct': clamp((exp - base) / need, 0, 1)}


def stage_index(w):
    """按体重返回成长阶段下标"""
    idx = 0
    for i, s in enumerate(STAGES):
        if w >= s['w']:
            idx = i
    return idx


def level_of(w):
    """等级：领养 200g 为 Lv.1，每增加 100g 升一级"""
    return int((float(w) - WEIGHT_START) // 100) + 1


def visit_scale(hi_w, lo_w):
    """串门时等级高的猫的缩放系数：每高 1 级 +6%，最多 +18%（显得更高更大）"""
    d = level_of(hi_w) - level_of(lo_w)
    if d <= 0:
        return 1.0
    return 1.0 + min(0.18, 0.06 * d)


def accompany_days(S):
    """陪伴主人的天数（按日历日：领养当天算第 1 天）"""
    birth = float(S.get('birth') or time_now())
    b = datetime.date.fromtimestamp(birth / 1000.0)
    return max(1, (datetime.date.today() - b).days + 1)


def default_state():
    return {
        'name': random.choice(NAME_POOL),
        'gender': random.choice(['公', '母']),
        'owner': '主人',
        'birth': int(time_now()),
        'exp': 0,
        'weight': WEIGHT_START,
        'full': 72.0,
        'water': 72.0,
        'mood': 82.0,
        'feedCount': 0,
        'growing': None,           # 喂食后的慢慢长肉：{'t0':开始,'gain':已长}
        'last': int(time_now()),
        'lastFeed': int(time_now()),
        'growthMig': 1,
        'win_x': None,
        'win_y': None,
        'size': SIZE,
        # ---- 跨电脑好友 & 消息 ----
        'pid': gen_pid(),          # 我的 6 位编号
        'partner': None,           # 好友：{'pid','name','gender','owner'}
        'chat': [],                # 聊天记录：[{'me':0/1,'text':..,'ts':..}]
        'net_seen': 0,             # 已拉取到的最大消息 id
        # ---- 串门 ----
        'visit': None,             # {'state':'knock'/'together','role':..,'peer':..,'t0':..}
        'pstat': None,             # 好友小猫的实时状态（画对方那只猫用）
        'vseen': 0,                # 已处理的串门动作事件 id
    }


def time_now():
    import time
    return time.time() * 1000.0


# ---------------- 跨电脑通信：网络层 ----------------
def gen_pid():
    """给每只猫生成一个 6 位编号（对外唯一身份）"""
    return '%06d' % random.randint(0, 999999)


def relay_call(path, payload=None, timeout=10):
    """调用中转服务；未配置地址或网络不通时返回 None（后台线程里用）"""
    if not RELAY_URL:
        return None
    url = RELAY_URL.rstrip('/') + path
    try:
        if payload is None:
            req = urllib.request.Request(url)
        else:
            body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            req = urllib.request.Request(
                url, data=body, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode('utf-8', 'ignore'))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


MATCH_ERR = {
    'self': '那是自己的编号呀，换个对方的吧～',
    'notfound': '没找到这个编号的猫，让对方确认一下编号哦',
    'busy_me': '你已经有好友啦，一只猫只能交一个朋友哦',
    'busy_target': '对方已经有别的好友了，换一只吧～',
    'pending': '已经向对方发出过请求啦，等对方同意就好～',
}


def load_state():
    S = default_state()
    data = {}
    try:
        with open(SAVE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        S.update(data)
    except Exception:
        pass
    for k in ('full', 'water', 'mood'):
        S[k] = clamp(float(S.get(k) or 0), 0, 100)
    S['exp'] = max(0.0, float(S.get('exp') or 0))
    S['weight'] = max(WEIGHT_START, float(S.get('weight') or WEIGHT_START))
    # 旧存档迁移：补投喂时间戳；体重按投喂次数折算（每次 +50g，领养 200g 起步）
    if 'gender' not in data:
        S['gender'] = '公'
    S['owner'] = str(S.get('owner') or '').strip()[:12] or '主人'
    # 跨电脑通信字段（旧存档迁移：补编号）
    if not str(S.get('pid') or '').strip():
        S['pid'] = gen_pid()
    S['pid'] = str(S['pid'])[:12]
    if not isinstance(S.get('partner'), dict):
        S['partner'] = None
    if not isinstance(S.get('chat'), list):
        S['chat'] = []
    try:
        S['net_seen'] = int(S.get('net_seen') or 0)
    except Exception:
        S['net_seen'] = 0
    # 串门字段迁移
    if not isinstance(S.get('visit'), dict):
        S['visit'] = None            # 启动时不接着上次的串门（两边状态对不上）
    if not isinstance(S.get('pstat'), dict):
        S['pstat'] = None
    try:
        S['vseen'] = int(S.get('vseen') or 0)
    except Exception:
        S['vseen'] = 0
    if 'lastFeed' not in data:
        S['lastFeed'] = int(S.get('last') or time_now())
    if not isinstance(S.get('growing'), dict):
        S['growing'] = None
    if not data.get('growthMig'):
        S['weight'] = max(WEIGHT_START,
                          100.0 + 50.0 * int(S.get('feedCount') or 0))
        S['growthMig'] = 1
    # 旧存档的窗口坐标是逻辑像素，迁移为物理像素
    if 'dpi' not in data:
        for k in ('win_x', 'win_y'):
            if S.get(k):
                S[k] = int(S[k] * DPI)
        S['dpi'] = DPI
    return S


def apply_decay(S):
    now = time_now()
    sec = (now - float(S.get('last') or now)) / 1000.0
    if not (sec > 0):                     # 主循环每秒调用一次，任何正间隔都要结算
        return
    sec = min(sec, MAX_OFFLINE)
    h = sec / 3600.0
    # 饱食/水分直接跟随投喂冷却：刚喂=100，3 小时冷却走完=0
    # 这样进度条永远和「还剩多久才能喂食/喝水」一致（剩 1.5 小时 = 50）
    rem = FEED_CD_MS - (now - float(S.get('lastFeed') or 0))
    v = clamp(100.0 * rem / FEED_CD_MS, 0, 100)
    S['full'] = v
    S['water'] = v
    S['mood'] = clamp(S['mood'] - RATE['mood'] * h, 0, 100)
    # 喂食后 3 小时内慢慢长肉：基础 30g/3h（10g/小时），心情 > 60 时速度翻倍
    g = S.get('growing')
    if isinstance(g, dict):
        t0 = float(g.get('t0') or 0)
        gain = float(g.get('gain') or 0)
        if now - t0 >= GROW_MS or gain >= GROW_PER_FEED * 2 - 0.01:
            S['growing'] = None               # 这顿饭消化完了 / 长满了
        else:
            speed = GROW_RATE * (2.0 if float(S.get('mood') or 0) > MOOD_FAST
                                 else 1.0)
            add = min(speed * h, GROW_PER_FEED * 2 - gain)
            S['weight'] = float(S.get('weight') or WEIGHT_START) + add
            g['gain'] = gain + add
    # 体重只通过喂食后慢慢长（见上），不随时间自动变化
    if S['full'] < 20 or S['water'] < 20:
        S['mood'] = clamp(S['mood'] - h * 6, 0, 100)
    S['last'] = int(now)


def age_text(ms):
    mins = int(ms / 60000)
    if mins < 1:
        return '刚刚出生'
    if mins < 60:
        return '%d 分钟' % mins
    hours = mins // 60
    if hours < 24:
        return '%d 小时' % hours
    return '%d 天 %d 小时' % (hours // 24, hours % 24)



def hex_rgb(h):
    """'#rrggbb' -> (r, g, b)"""
    h = h.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
