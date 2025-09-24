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
from .utils import (
    # TimeArguments,
    FilesHelper
)
from loguru import logger
from .config import cfg
from easydict import EasyDict

music_filename_template = '{no}_{bpm}_{class}_{layer}.mp3'


# ===============================================================


class RelaxMusicSession:
    def __init__(self,
                 # time_args: TimeArguments,
                 emotion=Emotion.peaceful,
                 args=None,
                 config=cfg):
        # self.time_args = time_args
        self.config = config
        self.fade_in_time = self.fade_out_time = self.config['fade']  # / 2
        self.l0_file = self.init_l0_file()
        self.l0_sound = AudioSegment.from_file(self.l0_file)
        self.l0_faded = self.fade(self.l0_sound)
        self.l1_file = None
        self.l2_file = None
        self.l4_file = None
        self.l1_sound, self.l2_sound, self.l4_sound = None, None, None
        self.l1_faded, self.l2_faded, self.l4_faded = None, None, None
        self.l0_state, self.l1_state, self.l2_state = {"start": None, "end": None, 'next': None}, \
                                                      {"start": None, "end": None, 'next': None}, \
                                                      {"start": None, "end": None, 'next': None}
        self.l0_state, self.l1_state, self.l2_state = list(
            map(EasyDict, [self.l0_state, self.l1_state, self.l2_state]))
        self.emotion = emotion
        self.hr_memory = HeartMemory(
            # time_args.slide_window
            self.config['slide_window']
        )

    def fade(self, sound):
        assert len(sound) / 1000 >= self.config['fade_time'], 'time of sound <= fade time configured'
        return sound.fade_in(1000 * self.fade_in_time).fade_out(1000 * self.fade_out_time)

    def match_by_layer(self, heart_rate, layer):
        emotion_folder = FilesHelper.get_emotion_root_by_emotion(self.emotion)
        emotion_fs, emotion_base_fs = FilesHelper.get_files_by_folder_root(emotion_folder)
        emotion_fs, emotion_base_fs = FilesHelper.get_files_by_layer(emotion_fs, emotion_base_fs, layer=layer, )
        hrs = [i.split('_')[1] for i in emotion_base_fs]
        closest_inds = get_index_of_closest_heart_rate(heart_rate, hrs)
        closest_ind = random.choice(closest_inds)
        file = emotion_fs[closest_ind]
        return file

    @property
    def current_emotion(self):
        raise NotImplementedError

    # todo: ...
    def init_l0_file(self):
        """environment sound"""
        return random.choice(FilesHelper.environment_files)

    def check_emotion(self, heart_rate, *args):
        return False

    def generate_l0_segment_and_update_l0(self, heart_rate):
        # l0 & 环境音乐
        l0_varied = self.check_emotion(heart_rate)
        if l0_varied:
            ...
        else:
            l0_segment = self.simply_generate_next_sound_segment_and_update_state(0)
        return l0_segment

    def generate_l1_segment_and_update_l1(self, heart_rate):
        if self.l1_state['end'] is None:
            # 保险用的逻辑, 不用分析
            segment = self.simply_generate_next_sound_segment_and_update_state(1)

        else:
            rest = len(self.l1_sound) - self.l1_state['end']
            if rest > 2 * 1000 * self.config['transport_time']:
                segment = self.simply_generate_next_sound_segment_and_update_state(1)
            # elif rest == 1000 * self.config['transport_time']:
            #     segment = self.l1_sound[self.l1_state['end']:]
            #     # segment = segment.fade_out(1000*self.fade_out_time)
            #     self.update_l1(heart_rate)
            #     self.l1_state['end'] = 0
            else:
                # completion_length = 1000 * self.config['transport_time'] - rest
                # fade_out_segment = self.l1_sound[self.l1_state['end']:]
                self.update_l1(heart_rate)
                # fade_in_segment = self.l1_sound[:completion_length]
                # segment = fade_out_segment + fade_in_segment
                # self.l1_state['end'] = completion_length

                segment = self.simply_generate_next_sound_segment_and_update_state(1)

        return segment

    def generate_l2_segment_and_update_l2(self, heart_rate):
        # rest = len(self.l2_sound) - self.l2_state['end']
        if max(self.hr_memory['time']) - min(self.hr_memory['time']) >= self.config['slide_window']:
            # rule 1
            if heart_rate > self.hr_memory.mean_hr:
                current_rule1_count = self.l2_state.get('larger_than_mean_hr', 0) + 1
                self.l2_state['larger_than_mean_hr'] = current_rule1_count
                if self.l2_state['larger_than_mean_hr'] >= 3:
                    self.update_l2(heart_rate)
                    self.l2_state['larger_than_mean_hr'] = 0
            hrs_temp = self.hr_memory['hr'] + [heart_rate]
            amp = max(hrs_temp) - min(hrs_temp)

            # rule 2
            if (65 <= heart_rate < 85 and amp > 4) or \
                    (85 <= heart_rate < 105 and amp > 7) or \
                    (heart_rate >= 105 and amp > 11):
                self.update_l2(heart_rate)

        segment = self.simply_generate_next_sound_segment_and_update_state(2)
        return segment

    def update_l1(self, heart_rate):
        l1_file = self.match_by_layer(heart_rate, 1)
        self.l1_file = l1_file
        self.l1_sound = self.load_and_preprocess_sound(self.l1_file)
        # self.l1_sound = self.l1_sound  # .fade_in(
        # 1000*self.fade_in_time
        # ).fade_out(
        #     1000*self.fade_out_time
        # )

    def update_l2(self, heart_rate):
        ...

    def simply_generate_next_sound_segment_and_update_state(self, layer):
        sound = {0: self.l0_sound, 1: self.l1_sound, 2: self.l2_sound}[layer]
        state = {0: self.l0_state, 1: self.l1_state, 2: self.l2_state}[layer]
        rest = len(sound) - state['end'] if state['end'] is not None else len(sound)

        start_temp = None
        end_temp = None
        # 当前l0文件临近播放结束，回到开头继续放
        if rest < 1000 * self.config['transport_time']:
            ...  # 几乎不会再触发，新的else逻辑下已处理当前情况
            # completion_length = 1000 * self.config['transport_time'] - rest
            # segment = sound[state['end']:] + sound[:completion_length]
            # # segment = segment.fade_in(1000 * self.fade_in_time).fade_out(1000 * self.fade_out_time)
            # start = 0
            # end = completion_length
        else:
            if state['end'] is None:
                start = 0
                end = 1000 * self.config['transport_time']
                segment = sound[start:end]
            else:
                assert state['next'] is not None, "next segment is None!"
                start = state['end']
                end = state['end'] + 1000 * self.config['transport_time']
                segment = state['next']

            start_next = start + 1000 * self.config['transport_time']
            end_next = end + 1000 * self.config['transport_time']

            # return to beginning and cross fade
            if end_next >= len(sound):
                start_temp = 0
                end_temp = 1000 * self.config['transport_time']
                segment_1 = sound[start_temp:end_temp]
                segment = segment.append(segment_1, crossfade=1000 * self.config['fade_time'])
                start_next = end_temp
                end_next = end_temp + 1000 * self.config['transport_time']

            segment_next = sound[start_next:end_next]
            state['next'] = segment_next

        # start其实并不重要，几乎用不到
        if end == len(sound):
            end = 0
        if start_temp is not None:
            state['start'] = start_temp
            state['end'] = end_temp
        else:
            state['start'] = start
            state['end'] = end

        """
        促使正常情况下，start和end表示当前segment的，而next为下一次使用的。
        若t1时刻结束时状态如下
        |----------------------------|-------|-------|--/
                                            end   
                                     |--seg--|segNext|
                                     
        t2时刻开始时，因为end_t2是最后一个在范围内的end，而end_next_t2将超出范围，故会立马成为如下图的状态，                   
        |-------|-------|--------------------|-------|--/
               end
        |--seg2-|segNext|                    |--seg1-|
              
        """
        return segment

    def load_and_preprocess_sound(self, sound_file):
        sound = AudioSegment.from_file(self.l1_file)
        if len(sound) < 1000 * self.config['transport_time']:
            sound = sound.append(sound, crossfade=1000 * self.config['fade_time'])
        return sound

    def match_and_generate(self, heart_rate):
        if self.hr_memory.is_empty or (
                max(self.hr_memory['time']) - min(self.hr_memory['time']) < self.config['memory_min_time']
        ):
            if self.l1_file is None:
                self.l1_file = self.match_by_layer(heart_rate, 1)
                self.l1_sound = self.load_and_preprocess_sound(self.l1_file)
            if self.l2_file is None:
                # todo: 修改为优先替换字符串，判断是否存在L2文件，不存在再回到此逻辑
                self.l2_file = self.match_by_layer(heart_rate, 2)
                self.l2_sound = self.load_and_preprocess_sound(self.l2_file)
            # l1_segment = self.simply_generate_next_sound_segment_and_update_state(1)
            # l2_segment = self.simply_generate_next_sound_segment_and_update_state(2)
        else:
            #
            ...
        l0_segment = self.generate_l0_segment_and_update_l0(heart_rate)
        l1_segment = self.generate_l1_segment_and_update_l1(heart_rate)
        l2_segment = self.generate_l2_segment_and_update_l2(heart_rate)
        assert len(l0_segment) == len(l1_segment) == len(l2_segment), "segments are different length!"
        segment = l0_segment.overlay(l1_segment).overlay(l2_segment)
        self.hr_memory.append(heart_rate)
        return segment
