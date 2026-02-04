#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
改进版音乐匹配模块 - V2版本

主要改进：
1. 循环时使用淡入淡出，保持自然过渡且长度一致
2. 音乐切换时添加淡入淡出效果
3. 支持可配置的过渡模式

过渡策略说明：
==============

策略1：循环过渡（Loop Transition）
--------------------------------
问题：音乐文件循环播放时，从结尾跳回开头会有突兀感

原始方案（直接跳转）：
    [-----音乐文件-----]
    取片段:  |--10s--|
    循环后:         ↓ 直接跳转
             |--10s--|  <- 可能有突兀感

改进方案（淡入淡出）：
    [-----音乐文件-----]
    取片段:  |--10s--|
             添加淡出3s
    循环后:  |--10s--| (最后3秒淡出)
             ↓
             |--10s--| (前3秒淡入)

优点：
- 保持10秒长度不变
- 过渡自然平滑
- 各层长度一致

缺点：
- 需要额外处理淡入淡出
- 音量在过渡点会稍微降低


策略2：音乐切换过渡（Music Change Transition）
--------------------------------------------
问题：心率变化导致L1/L2音乐切换时，新旧音乐直接切换会突兀

原始方案：
    旧音乐: |----------| (突然停止)
    新音乐:             |----------| (突然开始)

改进方案A（淡入淡出）：
    旧音乐: |----------| (最后3秒淡出)
    新音乐:             |----------| (前3秒淡入)

改进方案B（交叉淡化）：
    旧音乐: |----------淡出--|
    新音乐:       |--淡入----------|
              <-交叉3秒->

本实现使用方案A，因为：
- 保持片段长度一致
- 各层同步更简单
- 性能开销更小


策略3：片段拼接过渡（Segment Concatenation）
------------------------------------------
问题：连续的10秒片段拼接时，拼接点可能有断裂感

方案：由调用者决定
- 实时播放：直接拼接即可（单个片段已有淡入淡出）
- 导出完整音乐：使用crossfade拼接（demo中的做法）

"""

import os
import glob
import random
from pydub import AudioSegment
from dataclasses import dataclass
import numpy as np
import time
import math
from .compute import get_index_of_closest_heart_rate
from .memory import HeartMemory
from .utils import Emotion
from .utils import FilesHelper
from loguru import logger
from .config import cfg
from easydict import EasyDict


class RelaxMusicSessionV2:
    """
    改进版音乐会话类 - 支持自然过渡

    新增配置参数：
        transition_mode: 过渡模式
            - 'fade': 使用淡入淡出（推荐，默认）
            - 'direct': 直接切换（原始方式）
            - 'crossfade': 交叉淡化（会改变长度）

        loop_fade_enabled: 是否在循环时启用淡入淡出
        change_fade_enabled: 是否在切换音乐时启用淡入淡出
    """

    def __init__(self,
                 emotion=Emotion.peaceful,
                 args=None,
                 config=cfg,
                 transition_mode='fade'):
        self.config = config
        self.fade_in_time = self.fade_out_time = self.config['fade_time']
        self.transition_mode = transition_mode

        # 初始化L0（环境音）
        self.l0_file = self.init_l0_file()
        self.l0_sound = AudioSegment.from_file(self.l0_file)
        self.l0_faded = self.fade(self.l0_sound)

        # 初始化L1、L2
        self.l1_file = None
        self.l2_file = None
        self.l1_sound, self.l2_sound = None, None

        # 初始化状态
        self.l0_state = EasyDict({"start": None, "end": None, 'next': None, 'should_fade_in': False})
        self.l1_state = EasyDict({"start": None, "end": None, 'next': None, 'should_fade_in': False})
        self.l2_state = EasyDict({"start": None, "end": None, 'next': None, 'should_fade_in': False})

        self.emotion = emotion
        self.hr_memory = HeartMemory(self.config['slide_window'])

    def fade(self, sound):
        """给完整音频添加淡入淡出"""
        assert len(sound) / 1000 >= self.config['fade_time'], 'time of sound <= fade time configured'
        return sound.fade_in(1000 * self.fade_in_time).fade_out(1000 * self.fade_out_time)

    def match_by_layer(self, heart_rate, layer):
        """根据心率匹配指定层级的音乐文件"""
        emotion_folder = FilesHelper.get_emotion_root_by_emotion(self.emotion)
        emotion_fs, emotion_base_fs = FilesHelper.get_files_by_folder_root(emotion_folder)
        emotion_fs, emotion_base_fs = FilesHelper.get_files_by_layer(emotion_fs, emotion_base_fs, layer=layer)
        hrs = [i.split('_')[1] for i in emotion_base_fs]
        closest_inds = get_index_of_closest_heart_rate(heart_rate, hrs)
        closest_ind = random.choice(closest_inds)
        file = emotion_fs[closest_ind]
        return file

    def init_l0_file(self):
        """初始化环境音文件"""
        return random.choice(FilesHelper.environment_files())

    def check_emotion(self, heart_rate, *args):
        return False

    def generate_l0_segment_and_update_l0(self, heart_rate):
        """生成L0（环境音）片段"""
        l0_varied = self.check_emotion(heart_rate)
        if l0_varied:
            ...
        else:
            l0_segment = self.simply_generate_next_sound_segment_and_update_state(0)
        return l0_segment

    def generate_l1_segment_and_update_l1(self, heart_rate):
        """
        生成L1（主旋律）片段

        检查逻辑：
        1. 如果剩余时间充足（>2*transport_time），继续播放
        2. 否则，更新到新音乐
        """
        if self.l1_state['end'] is None:
            segment = self.simply_generate_next_sound_segment_and_update_state(1)
        else:
            rest = len(self.l1_sound) - self.l1_state['end']
            if rest > 2 * 1000 * self.config['transport_time']:
                segment = self.simply_generate_next_sound_segment_and_update_state(1)
            else:
                # 剩余时间不足，更新音乐
                self.update_l1(heart_rate)
                segment = self.simply_generate_next_sound_segment_and_update_state(1)
        return segment

    def generate_l2_segment_and_update_l2(self, heart_rate):
        """
        生成L2（和声）片段

        更新规则：
        1. 心率持续高于平均值3次
        2. 心率波动幅度超过阈值
        """
        if len(self.hr_memory['time']) > 0 and \
           max(self.hr_memory['time']) - min(self.hr_memory['time']) >= self.config['slide_window']:

            # 规则1：心率持续高于平均值
            if heart_rate > self.hr_memory.mean_hr:
                current_rule1_count = self.l2_state.get('larger_than_mean_hr', 0) + 1
                self.l2_state['larger_than_mean_hr'] = current_rule1_count
                if self.l2_state['larger_than_mean_hr'] >= 3:
                    self.update_l2(heart_rate)
                    self.l2_state['larger_than_mean_hr'] = 0

            # 规则2：心率波动幅度
            hrs_temp = self.hr_memory['hr'] + [heart_rate]
            amp = max(hrs_temp) - min(hrs_temp)

            if (65 <= heart_rate < 85 and amp > 4) or \
               (85 <= heart_rate < 105 and amp > 7) or \
               (heart_rate >= 105 and amp > 11):
                self.update_l2(heart_rate)

        segment = self.simply_generate_next_sound_segment_and_update_state(2)
        return segment

    def update_l1(self, heart_rate):
        """
        更新L1音乐

        改进：添加淡入标记，下一个片段会淡入
        """
        logger.info(f"🔄 L1音乐切换：心率={heart_rate} bpm")
        l1_file = self.match_by_layer(heart_rate, 1)
        self.l1_file = l1_file
        self.l1_sound = self.load_and_preprocess_sound(self.l1_file)
        # 重置状态，标记需要淡入
        self.l1_state = EasyDict({
            "start": None,
            "end": None,
            'next': None,
            'should_fade_in': True  # 新增：标记下一个片段需要淡入
        })

    def update_l2(self, heart_rate):
        """更新L2音乐"""
        logger.debug(f"🔄 L2音乐切换：心率={heart_rate} bpm")
        l2_file = self.match_by_layer(heart_rate, 2)
        self.l2_file = l2_file
        self.l2_sound = self.load_and_preprocess_sound(self.l2_file)
        # 重置状态，标记需要淡入
        self.l2_state = EasyDict({
            "start": None,
            "end": None,
            'next': None,
            'should_fade_in': True
        })

    def simply_generate_next_sound_segment_and_update_state(self, layer):
        """
        生成下一个音频片段并更新状态

        改进的循环和过渡逻辑：
        =====================

        1. 正常情况：从当前位置取10秒片段
        2. 循环情况：从头开始，前后都添加淡入淡出
        3. 切换情况：新音乐的第一个片段添加淡入

        关键改进：
        - 所有片段保持10秒长度
        - 使用淡入淡出而不是crossfade
        - 根据状态标记决定是否添加淡入
        """
        sound = {0: self.l0_sound, 1: self.l1_sound, 2: self.l2_sound}[layer]
        state = {0: self.l0_state, 1: self.l1_state, 2: self.l2_state}[layer]

        transport_time_ms = 1000 * self.config['transport_time']
        fade_time_ms = 1000 * self.config['fade_time']

        # ============ 生成当前片段 ============
        if state['end'] is None:
            # 第一次播放
            start = 0
            end = transport_time_ms
            segment = sound[start:end]

            # 如果标记了需要淡入（音乐刚切换），添加淡入效果
            if state.get('should_fade_in', False):
                segment = segment.fade_in(fade_time_ms)
                state['should_fade_in'] = False
                logger.debug(f"  Layer {layer}: 添加淡入效果（音乐切换）")
        else:
            # 使用预先准备好的next segment
            assert state['next'] is not None, "next segment is None!"
            start = state['end']
            end = state['end'] + transport_time_ms
            segment = state['next']

        # ============ 准备下一个片段 ============
        start_next = start + transport_time_ms
        end_next = end + transport_time_ms

        # 检查是否需要循环
        if end_next >= len(sound):
            # 需要循环：从头开始
            logger.debug(f"  Layer {layer}: 循环播放（{self.transition_mode}模式）")

            if self.transition_mode == 'fade':
                # 方案：使用淡入淡出
                # 当前片段添加淡出，下一个片段添加淡入
                segment = segment.fade_out(fade_time_ms)

                # 下一个片段从头开始并添加淡入
                start_next = 0
                end_next = transport_time_ms
                segment_next = sound[start_next:end_next]
                segment_next = segment_next.fade_in(fade_time_ms)

            elif self.transition_mode == 'direct':
                # 方案：直接循环（原始方式）
                start_next = 0
                end_next = transport_time_ms
                segment_next = sound[start_next:end_next]

            else:  # crossfade模式
                # 注意：这会改变segment长度！
                logger.warning(f"  Layer {layer}: crossfade模式会改变片段长度！")
                start_next = 0
                end_next = transport_time_ms + fade_time_ms
                segment_next_temp = sound[start_next:end_next]
                # crossfade会在使用时处理
                segment_next = segment_next_temp
        else:
            # 正常情况：继续播放
            segment_next = sound[start_next:end_next]

        state['next'] = segment_next
        state['start'] = start
        state['end'] = end

        return segment

    def load_and_preprocess_sound(self, sound_file):
        """加载并预处理音频文件"""
        sound = AudioSegment.from_file(sound_file)

        # 音量归一化到-20dBFS（避免过大或过小）
        # -20dBFS是一个合适的目标音量，既不会太大也不会太小
        target_dBFS = -20.0
        change_in_dBFS = target_dBFS - sound.dBFS
        sound = sound.apply_gain(change_in_dBFS)

        # 如果文件太短，循环一次
        if len(sound) < 1000 * self.config['transport_time']:
            sound = sound.append(sound, crossfade=1000 * self.config['fade_time'])
        return sound

    def match_and_generate(self, heart_rate):
        """
        核心方法：根据心率匹配并生成音乐片段

        返回：10秒的混合音频片段（L0 + L1 + L2）
        """
        # 初始化L1、L2（仅第一次）
        if self.hr_memory.is_empty or \
           (max(self.hr_memory['time']) - min(self.hr_memory['time']) < self.config['memory_min_time']):
            if self.l1_file is None:
                self.l1_file = self.match_by_layer(heart_rate, 1)
                self.l1_sound = self.load_and_preprocess_sound(self.l1_file)
            if self.l2_file is None:
                # 优先使用与L1相同BPM的L2文件
                if self.l1_file is not None:
                    potential_l2_file = self.l1_file.replace('_L1.mp3', '_L2.mp3')
                    if os.path.exists(potential_l2_file):
                        self.l2_file = potential_l2_file
                    else:
                        self.l2_file = self.match_by_layer(heart_rate, 2)
                else:
                    self.l2_file = self.match_by_layer(heart_rate, 2)
                self.l2_sound = self.load_and_preprocess_sound(self.l2_file)

        # 生成各层片段
        l0_segment = self.generate_l0_segment_and_update_l0(heart_rate)
        l1_segment = self.generate_l1_segment_and_update_l1(heart_rate)
        l2_segment = self.generate_l2_segment_and_update_l2(heart_rate)

        # 验证长度一致
        assert len(l0_segment) == len(l1_segment) == len(l2_segment), \
            f"segments are different length! L0={len(l0_segment)}, L1={len(l1_segment)}, L2={len(l2_segment)}"

        # 混合三层音频（使用音量控制避免过载）
        # L0: 环境音，降低6dB（音量减半）
        # L1: 主旋律，保持原音量
        # L2: 和声，降低3dB
        segment = l0_segment - 6  # 环境音降低
        segment = segment.overlay(l1_segment)  # 主旋律
        segment = segment.overlay(l2_segment - 3)  # 和声降低

        # 对最终混合结果进行音量归一化，避免削波失真
        # 归一化到-14dBFS（比单轨略响，因为是混合音频）
        target_dBFS = -14.0
        change_in_dBFS = target_dBFS - segment.dBFS
        segment = segment.apply_gain(change_in_dBFS)

        # 更新心率记忆
        self.hr_memory.append(heart_rate)

        return segment


# ============ 使用示例 ============

def example_usage():
    """使用示例"""
    print("""
使用方法：
=========

# 方式1：使用淡入淡出（推荐，默认）
session = RelaxMusicSessionV2(emotion=Emotion.peaceful, transition_mode='fade')

# 方式2：直接切换（原始方式）
session = RelaxMusicSessionV2(emotion=Emotion.peaceful, transition_mode='direct')

# 方式3：crossfade（会改变长度，不推荐）
session = RelaxMusicSessionV2(emotion=Emotion.peaceful, transition_mode='crossfade')

# 生成音乐
segment = session.match_and_generate(75)  # 75 bpm心率

过渡效果对比：
=============
- fade模式：循环点有3秒淡入淡出，音量会稍微降低但很自然
- direct模式：直接跳转，可能有突兀感
- crossfade模式：最自然但会改变片段长度，可能导致同步问题
    """)


if __name__ == "__main__":
    example_usage()
