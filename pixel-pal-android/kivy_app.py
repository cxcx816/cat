# -*- coding: utf-8 -*-
"""
像素宠物 · Pixel Pal Android（Kivy 版）
复用桌面版的像素引擎与养成逻辑（pet_engine.py），适配触屏交互。

    python main.py             # 电脑上预览运行
    python main.py --selftest  # 自检：3 秒后自动退出
打包安卓 APK 见 buildozer.spec 与 使用说明-安卓版.txt
"""
import json
import os
import random
import sys
import threading

import pet_engine as E

SELFTEST = '--selftest' in sys.argv
sys.argv = [a for a in sys.argv if a != '--selftest']   # 别让 kivy 误解析

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.clipboard import Clipboard
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput

from kivy.utils import platform

APP_VER = 'android-1.0'
CHAT_KEEP = 30
GRID_BYTES = E.GW * E.GH * 4

C_BG = (0.812, 0.910, 0.969, 1)          # 天空蓝背景
C_BAR = (1, 1, 1, 0.92)
C_BTN = (0.388, 0.741, 0.969, 1)
C_TXT = (0.16, 0.24, 0.31, 1)


def h2rgb(h):
    return E.hex_rgb(h)


# ---------------------------------------------------------------
#  小组件
# ---------------------------------------------------------------
class PetImage(Image):
    """像素猫画布：栅格 -> 纹理（色键透明，nearest 保持像素感）"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._tex = None
        self._last = None

    def show_grid(self, g):
        buf = bytearray(GRID_BYTES)
        i = 0
        for row in g:
            for c in row:
                if c and c != E.MAGIC:
                    r, gg, b = h2rgb(c)
                    buf[i] = r
                    buf[i + 1] = gg
                    buf[i + 2] = b
                    buf[i + 3] = 255
                i += 4
        data = bytes(buf)
        if data == self._last:
            return
        self._last = data
        tex = Texture.create(size=(E.GW, E.GH), colorfmt='rgba')
        tex.blit_buffer(data, colorfmt='rgba', bufferfmt='ubyte')
        tex.mag_filter = 'nearest'
        tex.min_filter = 'nearest'
        self.texture = tex
        self._tex = tex


class Bubble(Label):
    """头顶气泡"""

    def __init__(self, **kw):
        super().__init__(**kw, color=C_TXT, bold=True,
                         halign='center', valign='middle')
        self.bind(size=self._size_text)
        with self.canvas.before:
            Color(1, 1, 1, 0.94)
            self._bg = RoundedRectangle(radius=[dp(12)])
            Color(0.72, 0.82, 0.90, 1)
            self._ol = RoundedRectangle(radius=[dp(12)])
        self._task = None

    def _size_text(self, *a):
        self.text_size = self.size

    def set_bg(self, *a):
        self._bg.pos = self.pos
        self._bg.size = self.size
        self._ol.pos = (self.x - dp(1), self.y - dp(1))
        self._ol.size = (self.width + dp(2), self.height + dp(2))

    def show(self, text, sticky=False):
        self.text = text
        self.opacity = 1
        if self._task:
            self._task.cancel()
            self._task = None
        self.set_bg()
        if not sticky:
            self._task = Clock.schedule_once(self._hide, 4.6)

    def _hide(self, dt):
        self.opacity = 0


class StatBar(BoxLayout):
    """顶部状态条"""

    def __init__(self, **kw):
        super().__init__(**kw, size_hint=(1, None), height=dp(30),
                         padding=[dp(10), dp(2), dp(10), 0], spacing=dp(12))
        self.lb = Label(color=C_TXT, font_size=dp(13), halign='left')
        self.lb.bind(size=lambda o, s: setattr(o, 'text_size', s))
        self.add_widget(self.lb)

    def update(self, S):
        li = E.level_info(float(S.get('exp') or 0))
        self.lb.text = ('%s · Lv.%d · %.1fg · 心情%d · 饱食%d · 水分%d'
                        % (S.get('name'), li['lv'], float(S.get('weight') or 0),
                           S['mood'], S['full'], S['water']))


# ---------------------------------------------------------------
#  主应用
# ---------------------------------------------------------------
class PetPalApp(App):

    def build(self):
        Window.clearcolor = C_BG
        if platform != 'android':
            Window.size = (420, 780)
        self.title = '像素小猫'

        self.first_run = not os.path.exists(E.SAVE_PATH)
        if platform == 'android':
            E.SAVE_PATH = os.path.join(self.user_data_dir, 'pet_save.json')
            self.first_run = not os.path.exists(E.SAVE_PATH)
        self.S = E.load_state()

        root = FloatLayout()
        self.pet = PetImage(allow_stretch=True, keep_ratio=True)
        root.add_widget(self.pet)

        self.bubble = Bubble(size_hint=(None, None), size=(dp(300), dp(44)),
                             opacity=0, font_size=dp(14))
        root.add_widget(self.bubble)

        self.stat = StatBar()
        root.add_widget(self.stat)

        self.bar = GridLayout(cols=4, rows=2, size_hint=(1, None),
                              height=dp(104), padding=dp(6), spacing=dp(6))
        self._btns = {}
        for key, text in [('feed', '喂食'), ('water', '喝水'),
                          ('play', '玩耍'), ('sleep', '睡觉'),
                          ('sun', '晒太阳'), ('visit', '串门'),
                          ('msg', '消息'), ('set', '设置')]:
            b = Button(text=text, background_normal='',
                       background_color=C_BTN, bold=True,
                       font_size=dp(15), color=(1, 1, 1, 1))
            b.bind(on_release=lambda o, k=key: self.on_btn(k))
            self._btns[key] = b
            self.bar.add_widget(b)
        root.add_widget(self.bar)

        # 运行时状态（与桌面版同名语义）
        self.t0 = E.time_now()
        self.particles = []
        self._pose = None
        self._pose_t0 = 0
        self._pose_until = 0
        self._action = None
        self._action_t0 = 0
        self._next_encourage = self.t0 + 60 * 1000
        self._next_move = self.t0 + E.MOVE_MS
        self._next_weather = self.t0 + 8 * 1000
        self._weather = None
        self._weather_manual = False
        self._next_poll = 0
        self._net_busy = False
        self._net_req = None
        self._seen_req = None
        self._last_save = 0
        self._vapply = False
        self._quit_at = None
        if SELFTEST:
            self._quit_at = E.time_now() + 3000

        self.refresh_pet_size()
        Window.bind(on_resize=lambda *a: Clock.schedule_once(
            lambda dt: self.refresh_pet_size(), 0))

        if self.first_run:
            Clock.schedule_once(lambda dt: self.open_adopt(), 0.6)
        else:
            threading.Thread(target=self.net_hello_bg, daemon=True).start()
            self.say(random.choice(E.MSG.get('hi', ['回来啦～'])), 3600)

        Clock.schedule_interval(self.tick, 0.25)
        return root

    # ---------------- 布局辅助 ----------------
    def refresh_pet_size(self):
        sc = min((Window.height - dp(190)) / float(E.GH),
                 (Window.width - dp(24)) / float(E.GW))
        self.pet.size = (E.GW * sc, E.GH * sc)
        self.pet.pos = ((Window.width - self.pet.width) / 2,
                        dp(104) + (Window.height - dp(104) - self.pet.height) * 0.42)
        self.stat.pos = (0, Window.height - dp(34))
        self.bubble.pos = (Window.width / 2 - dp(150), self.pet.top - dp(20))

    # ---------------- 气泡 ----------------
    def say(self, text, ms=3600, sticky=False):
        self.bubble.show(text, sticky)

    # ---------------- 粒子 ----------------
    def spawn(self, kind, count, x, y):
        floaty = kind in ('heart', 'spark')
        for _ in range(count):
            self.particles.append({
                'x': x + random.uniform(-8, 8),
                'y': y + random.uniform(-4, 4),
                'vx': random.uniform(-0.18, 0.18),
                'vy': random.uniform(-0.16, -0.42) if floaty
                      else random.uniform(0.06, 0.22),
                'life': 0,
                'max': random.uniform(22, 34),
                'type': kind,
            })

    def update_particles(self):
        for p in list(self.particles):
            p['life'] += 1
            p['x'] += p['vx']
            p['y'] += p['vy']
            p['vy'] += 0.02
            if p['life'] > p['max']:
                self.particles.remove(p)

    # ---------------- 主循环 ----------------
    def tick(self, dt):
        now = E.time_now()
        t = now - self.t0
        S = self.S

        E.apply_decay(S)

        # 睡觉 / 晒太阳到点自动恢复
        if self._pose and now > self._pose_until:
            self.end_pose()

        # 动作播完自动复位
        if self._action and now - self._action_t0 > \
                E.ACTION_DUR[self._action] + 120:
            self._action = None

        # 鼓励语：5 分钟一句（30 天不重复 + 最多连说两次，见引擎）
        if now > self._next_encourage:
            self._next_encourage = now + E.ENCOURAGE_MS
            if not self._pose:
                self.say(E.pick_encourage(S), 5600)

        # 久坐提醒
        if now > self._next_move:
            self._next_move = now + E.MOVE_MS
            self.say(random.choice(E.MOVE_MSGS), sticky=True)

        # 天气
        if now > self._next_weather:
            self._next_weather = now + E.WEATHER_MS
            threading.Thread(target=self.fetch_weather, daemon=True).start()

        # 网络同步
        if E.RELAY_URL and now > self._next_poll and not self._net_busy:
            self._next_poll = now + (E.VISIT_POLL_MS if self.visit_state()
                                     else E.POLL_MS)
            self._net_busy = True
            threading.Thread(target=self.net_poll_bg, daemon=True).start()

        # 串门 30 分钟自动回家
        vs = self.visit_state()
        if vs:
            v = S.get('visit') or {}
            t0v = float(v.get('t0') or 0)
            if t0v and now - t0v > E.VISIT_MS:
                self.visit_leave()
            elif vs == 'together' and random.random() < 0.006:
                self.spawn('heart', 1, E.CX + random.uniform(-14, 14),
                           E.FOOT - 58)

        self.update_particles()

        act, at = self._action, (now - self._action_t0) if self._action else 0
        if self._pose == 'sun' and not act:
            act = 'jump'
            at = (now - self._pose_t0) % E.ACTION_DUR['jump']
        self.render(t, act, at)

        self.stat.update(S)
        self.update_visit_btn()

        if self._quit_at and now > self._quit_at:
            self.save()
            self.stop()

        if now - self._last_save > 10000:
            self.save()

    def render(self, t, action=None, at=0):
        g = E.new_grid()
        E.apply_coat(float(self.S.get('weight') or E.WEIGHT_START))
        vs = self.visit_state()
        if vs == 'knock':
            E.draw_door(g, t, self._peer_name())
        elif vs == 'together':
            E.draw_together(g, t, self.S, self.S.get('pstat'),
                            action, at, self._pose)
        else:
            sc = (action is None and self._pose is None and not any(
                p.get('type') in ('food', 'drop', 'heart')
                for p in self.particles))
            E.draw_pet(g, t, self.S, action, at, self._pose, scenery=sc)
        E.draw_particles(g, self.particles)
        self.pet.show_grid(g)

    # ---------------- 交互 ----------------
    def on_btn(self, key):
        if key == 'feed':
            self.act_feed()
        elif key == 'water':
            self.act_water()
        elif key == 'play':
            self.act_play()
        elif key == 'sleep':
            self.toggle_pose('sleep')
        elif key == 'sun':
            self.toggle_pose('sun')
        elif key == 'visit':
            self.on_visit_btn()
        elif key == 'msg':
            self.open_chat()
        elif key == 'set':
            self.open_settings()

    def _can_care(self):
        """串门时：客人不能照顾自己这只（猫不在家），主人可以"""
        vs = self.visit_state()
        if not vs:
            return True
        role = (self.S.get('visit') or {}).get('role')
        return role != 'visitor'

    def _feed_cd_text(self):
        rem = E.FEED_CD_MS - (E.time_now() -
                              float(self.S.get('lastFeed') or 0))
        return '还要等 %s 才能喂食/喝水哦' % E.fmt_dur(max(0, rem))

    def act_feed(self):
        S = self.S
        if not self._can_care():
            self.say('「%s」不在家，请它主人安排吧～' % S.get('name'), 4200)
            return
        now = E.time_now()
        if now - float(S.get('lastFeed') or 0) < E.FEED_CD_MS:
            self.say(self._feed_cd_text(), 4200)
            return
        was_lie = E.pet_lied(S)
        S['lastFeed'] = int(now)
        S['full'] = 100.0
        S['growing'] = {'t0': int(now), 'gain': 0.0}    # 慢慢长肉
        S['mood'] = E.clamp(S['mood'] + 4, 0, 100)
        S['exp'] = float(S.get('exp') or 0) + 2
        S['feedCount'] = int(S.get('feedCount') or 0) + 1
        self.spawn('food', 6, E.CX, E.FOOT - 44)
        self.say(random.choice(E.MSG['feed']), 3600)
        if was_lie:
            S['exp'] = float(S.get('exp') or 0) + 3
        if self.visit_state() == 'together':
            self._visit_send('feed')
        self.save()

    def act_water(self):
        S = self.S
        if not self._can_care():
            self.say('「%s」不在家，请它主人安排吧～' % S.get('name'), 4200)
            return
        now = E.time_now()
        if now - float(S.get('lastFeed') or 0) < E.FEED_CD_MS:
            self.say(self._feed_cd_text(), 4200)
            return
        S['lastFeed'] = int(now)
        S['water'] = 100.0
        S['mood'] = E.clamp(S['mood'] + 3, 0, 100)
        S['exp'] = float(S.get('exp') or 0) + 1
        self.spawn('drop', 7, E.CX, E.FOOT - 44)
        self.say(random.choice(E.MSG['water']), 3600)
        if self.visit_state() == 'together':
            self._visit_send('water')
        self.save()

    def act_play(self):
        S = self.S
        if not self._can_care():
            self.say('「%s」不在家，请它主人安排吧～' % S.get('name'), 4200)
            return
        S['mood'] = 100.0
        S['exp'] = float(S.get('exp') or 0) + 2
        kind = random.choice(list(E.ACTION_DUR))
        self._action = kind
        self._action_t0 = E.time_now()
        self.spawn('heart', 4, E.CX, E.FOOT - 50)
        self.say(random.choice(E.ACTION_MSG[kind]), 3200)
        if self.visit_state() == 'together':
            self._visit_send('play')
        self.save()

    def toggle_pose(self, want):
        if not self._can_care():
            self.say('「%s」不在家，请它主人安排吧～' % self.S.get('name'), 4200)
            return
        if self._pose == want:
            self.end_pose(say=True)
            return
        self._pose = want
        self._pose_t0 = E.time_now()
        self._pose_until = E.time_now() + E.POSE_MS
        self.say(random.choice(E.MSG.get('pose_' + want,
                                          ['好舒服呀～'])), 3200)
        if self.visit_state() == 'together':
            self._visit_send('pose:' + want)
        self.save()

    def end_pose(self, say=False):
        self._pose = None
        if say:
            self.say('玩好了，继续干活吧～', 3000)
        if self.visit_state() == 'together':
            self._visit_send('pose:none')

    # ---------------- 串门 ----------------
    def my_pid(self):
        if not self.S.get('pid'):
            self.S['pid'] = E.gen_pid()
        return str(self.S['pid'])

    def _peer_name(self):
        p = self.S.get('pstat') or self.S.get('partner') or {}
        return p.get('name') or '好友的猫'

    def visit_state(self):
        v = self.S.get('visit')
        return v.get('state') if isinstance(v, dict) else None

    def update_visit_btn(self):
        vs = self.visit_state()
        b = self._btns['visit']
        if vs == 'knock':
            b.text = '取消' if (self.S.get('visit') or {}).get('role') \
                == 'visitor' else '开门'
        elif vs == 'together':
            b.text = '回家' if (self.S.get('visit') or {}).get('role') \
                == 'visitor' else '送客'
        else:
            b.text = '串门'

    def on_visit_btn(self):
        vs = self.visit_state()
        if not vs:
            p = self.S.get('partner')
            if not p:
                self.open_add_friend()
            else:
                self.visit_knock()
        elif vs == 'knock':
            if (self.S.get('visit') or {}).get('role') == 'visitor':
                self.visit_leave(quiet=True)          # A 方取消
            else:
                self.visit_open()                     # B 方开门
        elif vs == 'together':
            self.visit_leave()

    def visit_knock(self):
        if not self.S.get('partner'):
            self.say('先加个好友，才能去串门呀～')
            return
        self.S['visit'] = {'state': 'knock', 'role': 'visitor',
                           'peer': self.S['partner'].get('pid'),
                           't0': int(E.time_now())}
        self.say('去「%s」家敲门咯…' % (self.S['partner'].get('name') or '好友'),
                 sticky=True)
        self.save()

        def done(res):
            if res is None or not res.get('ok'):
                self.S['visit'] = None
                self.say('好像敲不到门，网络不太通呢…')
        self._relay_async('/api/visit', {'pid': self.my_pid(),
                                         'action': 'knock'}, done)

    def visit_open(self):
        def done(res):
            if res is None or not res.get('ok'):
                self.say('没能开门，稍后再试试～')
        self._relay_async('/api/visit', {'pid': self.my_pid(),
                                         'action': 'open'}, done)

    def visit_leave(self, quiet=False):
        cur = self.S.get('visit') or {}
        role = cur.get('role')
        state = cur.get('state')
        self.S['visit'] = None
        self.end_pose(quiet=True)
        self.hide_and_bye(state, role, quiet)
        self.save()

        def done(res):
            pass
        self._relay_async('/api/visit', {'pid': self.my_pid(),
                                         'action': 'leave'}, done)

    def hide_and_bye(self, state, role, quiet):
        if not quiet:
            if state == 'knock':
                if role == 'visitor':
                    self.say('先回来吧，下次再去玩～', 4200)
                else:
                    self.say('已谢客，改天再欢迎它来玩～', 4200)
            else:
                if role == 'visitor':
                    self.say('玩好了，我们先回家啦，下次再一起玩～', 4200)
                else:
                    self.say(random.choice(E.VISIT_BYE_MSGS)
                             % self._peer_name(), 4200)

    def _visit_send(self, kind):
        if self._vapply or self.visit_state() != 'together':
            return
        self._relay_async('/api/vevent', {'pid': self.my_pid(), 'kind': kind},
                          lambda r: None)

    def apply_visit_event(self, kind):
        v = self.S.get('visit') or {}
        if v.get('state') != 'together':
            return
        S = self.S
        now = E.time_now()
        self._vapply = True
        try:
            if kind == 'feed':
                S['lastFeed'] = int(now)
                S['full'] = 100.0
                S['growing'] = {'t0': int(now), 'gain': 0.0}
                S['mood'] = E.clamp(S['mood'] + 4, 0, 100)
                S['feedCount'] = int(S.get('feedCount') or 0) + 1
                self.spawn('food', 6, E.CX, E.FOOT - 44)
                self.say(random.choice(E.MSG['feed']), 3600)
            elif kind == 'water':
                S['lastFeed'] = int(now)
                S['water'] = 100.0
                S['mood'] = E.clamp(S['mood'] + 3, 0, 100)
                self.spawn('drop', 7, E.CX, E.FOOT - 44)
                self.say(random.choice(E.MSG['water']), 3600)
            elif kind == 'play':
                S['mood'] = 100.0
                self.spawn('heart', 6, E.CX, E.FOOT - 44)
                self.say(random.choice(E.MSG['play']), 3600)
            elif kind in ('pose:sleep', 'pose:sun', 'pose:none'):
                want = None if kind == 'pose:none' else kind.split(':')[1]
                if self._pose != want:
                    if want:
                        self._pose = want
                        self._pose_t0 = now
                        self._pose_until = now + E.POSE_MS
                    else:
                        self._pose = None
        finally:
            self._vapply = False

    @mainthread
    def apply_visit(self, v, self_act=False):
        cur = self.S.get('visit') or {}
        if not isinstance(v, dict):
            # 对端把串门结束了 / 服务端状态已清空
            if cur and not self._vapply:
                self.S['visit'] = None
                self.end_pose(quiet=True)
                if cur.get('state') == 'knock':
                    if cur.get('role') == 'visitor':
                        self.say('「%s」暂且不欢迎串门，改天再去吧～'
                                 % self._peer_name(), 4600)
                else:
                    if cur.get('role') == 'visitor':
                        self.say('「%s」家里有事，先回家啦，下次再玩～'
                                 % self._peer_name(), 4600)
                    else:
                        self.say('「%s」已经回家啦，下次再一起玩～'
                                 % self._peer_name(), 4600)
            return
        new_state = v.get('state')
        role = v.get('role')
        self.S['visit'] = v
        self.S['t0'] = v.get('t0')
        if new_state == 'knock' and cur.get('state') != 'knock':
            self.end_pose(quiet=True)
            self.hide_and_bye(None, None, True)
            if role == 'host':
                self.say(random.choice(E.VISIT_KNOCK_PEER_MSGS)
                         % self._peer_name(), sticky=True)
            else:
                self.say(random.choice(E.VISIT_KNOCK_MSGS)
                         % (v.get('peer_name') or self._peer_name()),
                         sticky=True)
        elif new_state == 'together' and cur.get('state') != 'together':
            self.end_pose(quiet=True)
            self.spawn('heart', 8, E.CX, E.FOOT - 50)
            self.say('在一起玩啦～', 3600)
        elif cur and not new_state:
            # 对端把串门结束了
            self.S['visit'] = None
            self.end_pose(quiet=True)
            if cur.get('state') == 'knock':
                if self_act:
                    pass                          # 自己点的，已在本地提示
                elif cur.get('role') == 'visitor':
                    self.say('「%s」暂且不欢迎串门，改天再去吧～'
                             % self._peer_name(), 4600)
            else:
                if not self_act:
                    if cur.get('role') == 'visitor':
                        self.say('「%s」家里有事，先回家啦，下次再玩～'
                                 % self._peer_name(), 4600)
                    else:
                        self.say('「%s」已经回家啦，下次再一起玩～'
                                 % self._peer_name(), 4600)

    # ---------------- 网络 ----------------
    def _relay_async(self, path, payload, done):
        def run():
            res = E.relay_call(path, payload)
            if done:
                Clock.schedule_once(lambda dt: done(res), 0)
        threading.Thread(target=run, daemon=True).start()

    def net_hello_bg(self):
        res = E.relay_call('/api/hello', {
            'pid': self.my_pid(), 'name': self.S.get('name'),
            'gender': self.S.get('gender'), 'owner': self.S.get('owner')})
        if res and res.get('ok'):
            Clock.schedule_once(lambda dt: self.apply_net(res), 0)

    def net_poll_bg(self):
        try:
            res = E.relay_call('/api/pull', {
                'pid': self.my_pid(),
                'since': int(self.S.get('net_seen') or 0),
                'vsince': int(self.S.get('vseen') or 0),
                'status': self.my_status()})
        finally:
            self._net_busy = False
        if res and res.get('ok'):
            Clock.schedule_once(lambda dt: self.apply_net(res), 0)

    def my_status(self):
        S = self.S
        return {'weight': round(float(S.get('weight') or E.WEIGHT_START), 1),
                'full': round(float(S.get('full') or 0), 1),
                'water': round(float(S.get('water') or 0), 1),
                'mood': round(float(S.get('mood') or 0), 1),
                'lastfeed': int(S.get('lastFeed') or 0),
                'pose': self._pose or ''}

    def apply_net(self, res):
        S = self.S
        if isinstance(res.get('partner'), dict):
            old = S.get('partner') or {}
            new = res['partner']
            if old.get('pid') != new.get('pid'):
                S['chat'] = []
            S['partner'] = new
        if isinstance(res.get('pstat'), dict):
            S['pstat'] = res['pstat']
        msgs = res.get('msgs') or []
        for m in msgs:
            S.setdefault('chat', []).append(
                {'me': 0, 'text': str(m.get('text') or ''), 'ts': int(m.get('ts') or 0)})
            self.say('「%s」：%s' % ((S.get('partner') or {}).get('name')
                                    or '好友', m.get('text')), 5200)
        if msgs:
            S['chat'] = S['chat'][-CHAT_KEEP:]
            S['net_seen'] = max(int(S.get('net_seen') or 0),
                                max(int(m.get('id') or 0) for m in msgs))
            self.save()
            if getattr(self, '_chat_list', None):
                self.fill_chat()
        req = res.get('req')
        if isinstance(req, dict) and req.get('id'):
            if req.get('id') != self._seen_req:
                self._seen_req = req.get('id')
                self.show_friend_request(req)
        vevents = res.get('vevents') or []
        for ev in vevents:
            eid = int(ev.get('id') or 0)
            if eid > int(S.get('vseen') or 0):
                S['vseen'] = eid
                self.apply_visit_event(str(ev.get('kind') or ''))
        if 'visit' in res:
            self.apply_visit(res.get('visit'))

    # ---------------- 天气 ----------------
    def fetch_weather(self):
        import urllib.request
        try:
            req = urllib.request.Request(
                E.WEATHER_URL, headers={'User-Agent': 'curl/7.64.1'})
            with urllib.request.urlopen(req, timeout=8) as r:
                txt = r.read().decode('utf-8', 'ignore').strip()
            txt = ' '.join(txt.split())
            if txt and len(txt) < 120:
                self._weather = txt
                Clock.schedule_once(lambda dt: self.say(
                    '看看今天的天气：%s' % txt, 6800), 0)
        except Exception:
            pass

    # ---------------- 弹窗 ----------------
    def _popup(self, title, content, size=(0.9, 0.7)):
        p = Popup(title=title, content=content,
                  size_hint=size, auto_dismiss=True,
                  background_color=(1, 1, 1, 0.98),
                  title_color=C_TXT, title_size=dp(16))
        p.open()
        return p

    def open_adopt(self):
        box = BoxLayout(orientation='vertical', spacing=dp(10), padding=dp(8))
        box.add_widget(Label(text='给你的小猫起个名字吧：', color=C_TXT,
                             size_hint=(1, None), height=dp(30)))
        name = TextInput(text=random.choice(E.NAME_POOL),
                         multiline=False, font_size=dp(16))
        box.add_widget(name)
        row = BoxLayout(size_hint=(1, None), height=dp(44), spacing=dp(10))
        box.add_widget(Label(text='性别：', color=C_TXT,
                             size_hint=(None, 1), size_hint_x=0.25))
        gender = {'v': '公'}
        for g in ('公', '母'):
            b = Button(text=g, background_normal='',
                       background_color=C_BTN if g == '公'
                       else (1.0, 0.62, 0.68, 1), bold=True, color=(1, 1, 1, 1))
            b.bind(on_release=lambda o, gg=g: gender.__setitem__('v', gg))
            row.add_widget(b)
        box.add_widget(row)
        ok = Button(text='开始陪伴吧！', background_normal='',
                    background_color=(0.30, 0.69, 0.35, 1), bold=True,
                    color=(1, 1, 1, 1), size_hint=(1, None), height=dp(50))

        def go(o):
            S = self.S
            S['name'] = (name.text or '').strip()[:8] or '咪咪'
            S['gender'] = gender['v']
            S['birth'] = int(E.time_now())
            self.save()
            self._adopt_pop.dismiss()
            self.stat.update(S)
            self.say('%s：以后请多关照啦，主人～' % S['name'], 5200)
            threading.Thread(target=self.net_hello_bg, daemon=True).start()
        ok.bind(on_release=go)
        box.add_widget(ok)
        self._adopt_pop = self._popup('领养小猫', box, (0.9, 0.5))

    def open_settings(self):
        S = self.S
        box = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(8))
        li = E.level_info(float(S.get('exp') or 0))
        info = Label(
            text=('名字 %s · %s宝宝\n主人 %s · 陪伴 %d 天\n'
                  '体重 %.1fg · Lv.%d（exp %d/%d）\n'
                  '编号 %s（点我复制）\n好友 %s')
            % (S.get('name'), S.get('gender'), S.get('owner'),
               E.accompany_days(S), float(S.get('weight') or 0),
               li['lv'], int(li['base'] and (float(S.get('exp') or 0) - li['base'])),
               li['need'], self.my_pid(),
               (S.get('partner') or {}).get('name') or '还没有'),
            color=C_TXT, font_size=dp(14), halign='left', valign='top')
        info.bind(size=lambda o, s: setattr(o, 'text_size', s))
        box.add_widget(info)

        def copy_pid(o):
            Clipboard.copy(self.my_pid())
            self.say('编号已复制：%s' % self.my_pid(), 3000)
        info.bind(on_touch_down=lambda o, t: copy_pid(o)
                  if info.collide_point(*t.pos) else None)

        box.add_widget(Label(text='改名：', color=C_TXT,
                             size_hint=(1, None), height=dp(24)))
        nm = TextInput(text=S.get('name') or '', multiline=False)
        box.add_widget(nm)

        box.add_widget(Label(text='大小（%.1f×）' % float(S.get('size') or 1),
                             color=C_TXT, size_hint=(1, None), height=dp(24),
                             font_size=dp(13)))
        sl = Slider(min=E.SIZE_MIN, max=E.SIZE_MAX, step=E.SIZE_STEP,
                    value=float(S.get('size') or 1))

        def on_sl(o, v):
            S['size'] = round(v, 2)
            self.refresh_pet_size()
        sl.bind(value=on_sl)
        box.add_widget(sl)

        row = BoxLayout(size_hint=(1, None), height=dp(46), spacing=dp(8))
        if S.get('partner'):
            ub = Button(text='解除好友', background_normal='',
                        background_color=(0.85, 0.35, 0.32, 1), color=(1, 1, 1, 1))

            def do_un(o):
                self._relay_async('/api/unmatch', {'pid': self.my_pid()},
                                  lambda r: None)
                S['partner'] = None
                S['pstat'] = None
                self.save()
                self._set_pop.dismiss()
                self.say('已经和对方解除好友关系啦')
            ub.bind(on_release=do_un)
            row.add_widget(ub)
        cl = Button(text='关闭', background_normal='',
                    background_color=(0.55, 0.62, 0.68, 1), color=(1, 1, 1, 1))
        cl.bind(on_release=lambda o: self._set_pop.dismiss())
        row.add_widget(cl)
        box.add_widget(row)

        def save_all(o):
            S['name'] = (nm.text or '').strip()[:8] or S['name']
            self.save()
            threading.Thread(target=self.net_hello_bg, daemon=True).start()
        box.bind(on_pre_enter=save_all)
        self._set_pop = self._popup('宠物设置', box, (0.92, 0.78))
        self._set_pop.bind(on_dismiss=save_all)

    def open_add_friend(self):
        box = BoxLayout(orientation='vertical', spacing=dp(10), padding=dp(8))
        box.add_widget(Label(text='输入对方的 6 位猫编号\n（对方可在「设置」里查看并复制）',
                             color=C_TXT, halign='center'))
        ent = TextInput(multiline=False, input_type='number', font_size=dp(18))
        box.add_widget(ent)
        go = Button(text='发出好友请求', background_normal='',
                    background_color=(0.30, 0.69, 0.35, 1), color=(1, 1, 1, 1),
                    size_hint=(1, None), height=dp(48))

        def send(o):
            target = (ent.text or '').strip()[:12]
            if not target:
                return
            if target == self.my_pid():
                self.say('那是自己的编号呀，换个对方的吧～')
                return
            self._add_pop.dismiss()
            self.say('正在帮你去问问…')

            def done(res):
                if res is None:
                    self.say('网络好像不太通，稍后再试试～')
                elif res.get('ok'):
                    self.say('已向编号 %s 的猫发出好友请求～' % target)
                    self._seen_req = None
                elif res.get('accepted'):
                    self.say('好耶，直接配对成功啦！')
                else:
                    self.say(E.MATCH_ERR.get(res.get('err'),
                                             '好友请求没成功，稍后再试试～'))
            self._relay_async('/api/match', {
                'pid': self.my_pid(), 'target': target,
                'name': self.S.get('name'), 'gender': self.S.get('gender'),
                'owner': self.S.get('owner')}, done)
        go.bind(on_release=send)
        box.add_widget(go)
        self._add_pop = self._popup('加好友', box, (0.88, 0.42))

    def show_friend_request(self, req):
        box = BoxLayout(orientation='vertical', spacing=dp(10), padding=dp(8))
        box.add_widget(Label(text='「%s」的猫（主人 %s）\n想和你的猫交朋友，同意吗？'
                             % (req.get('name') or '???',
                                req.get('owner') or '???'),
                             color=C_TXT, halign='center'))
        row = BoxLayout(size_hint=(1, None), height=dp(48), spacing=dp(10))

        def answer(accept):
            self._req_pop.dismiss()
            self._seen_req = None

            def done(res):
                if res is None:
                    self.say('网络好像不太通，稍后再试试～')
                elif accept and res.get('accepted'):
                    self.say('好耶，加好友成功！')
                elif not accept:
                    self.say('已经帮对方回绝啦～')
                else:
                    self.say(E.MATCH_ERR.get(res.get('err'),
                                             '没能加上好友，稍后再试试～'))
                threading.Thread(target=self.net_hello_bg, daemon=True).start()
            self._relay_async('/api/answer', {
                'pid': self.my_pid(), 'req_id': req.get('id'),
                'accept': 1 if accept else 0}, done)
        yes = Button(text='同意', background_normal='',
                     background_color=(0.30, 0.69, 0.35, 1), color=(1, 1, 1, 1))
        yes.bind(on_release=lambda o: answer(True))
        no = Button(text='婉拒', background_normal='',
                    background_color=(0.85, 0.35, 0.32, 1), color=(1, 1, 1, 1))
        no.bind(on_release=lambda o: answer(False))
        row.add_widget(yes)
        row.add_widget(no)
        box.add_widget(row)
        self._req_pop = self._popup('好友请求', box, (0.88, 0.42))

    def open_chat(self):
        p = self.S.get('partner')
        if not p:
            self.say('还没有好友呢，先点「串门」去加个好友吧～')
            return
        box = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(8))
        self._chat_list = Label(color=C_TXT, font_size=dp(13),
                                halign='left', valign='top', size_hint_y=None)
        self._chat_list.bind(
            width=lambda o, w: setattr(o, 'text_size', (w, None)))
        self._chat_list.bind(texture_size=lambda o, s: setattr(
            o, 'height', max(1, s[1])))
        sv = ScrollView()
        sv.add_widget(self._chat_list)
        box.add_widget(sv)
        row = BoxLayout(size_hint=(1, None), height=dp(46), spacing=dp(8))
        ent = TextInput(multiline=False, font_size=dp(15))
        row.add_widget(ent)

        def send(o):
            text = (ent.text or '').strip()[:200]
            if not text:
                return
            ent.text = ''
            S = self.S
            S.setdefault('chat', []).append(
                {'me': 1, 'text': text, 'ts': int(E.time_now())})
            S['chat'] = S['chat'][-CHAT_KEEP:]
            self.fill_chat()
            self.save()

            def done(res):
                if res is None or not res.get('ok'):
                    self.say('消息没发出去，网络好像不太通呢…')
            self._relay_async('/api/send', {'pid': self.my_pid(),
                                            'text': text}, done)
        sb = Button(text='发送', background_normal='', background_color=C_BTN,
                    color=(1, 1, 1, 1), size_hint=(None, 1), width=dp(80))
        sb.bind(on_release=send)
        ent.bind(on_text_validate=send)
        row.add_widget(sb)
        box.add_widget(row)
        self.fill_chat()
        self._chat_pop = self._popup('和「%s」聊天'
                                     % (p.get('name') or '好友'), box,
                                     (0.92, 0.8))
        self._chat_pop.bind(on_dismiss=lambda o: setattr(self, '_chat_list',
                                                         None))

    def fill_chat(self):
        if not self._chat_list:
            return
        lines = []
        for m in (self.S.get('chat') or [])[-CHAT_KEEP:]:
            who = '我' if m.get('me') else (self.S.get('partner') or {}).get(
                'name') or '好友'
            lines.append('%s：%s' % (who, m.get('text')))
        self._chat_list.text = '\n'.join(lines) or '还没有消息，打个招呼吧～'

    # ---------------- 存档 ----------------
    def save(self):
        self._last_save = E.time_now()
        try:
            with open(E.SAVE_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.S, f, ensure_ascii=False)
        except Exception:
            pass

    def on_pause(self):
        self.save()
        return True

    def on_stop(self):
        self.save()


if __name__ == '__main__':
    PetPalApp().run()
