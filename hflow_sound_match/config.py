"""一些配置的约束
# 方便起见，fade_in+fade_out的时间要小于transport_time
#################################################
"""
import json
import os
from loguru import logger

this_file_root = os.path.abspath(__file__)
_config_json_path = os.path.abspath(os.path.join(os.path.abspath(__file__), '..', 'config.json'))
with open(_config_json_path, 'r') as f:
    cfg = json.load(f)

# 配置约束
assert cfg['transport_time'] > cfg['fade_time'], "transport_time必须大于fade_time"
assert cfg['slide_window'] > cfg['transport_time'], "slide_window必须大于transport_time"
# assert os.path.isabs(cfg['sound_folders_root'])
if not os.path.isabs(cfg['sound_folders_root']) :
    cfg['sound_folders_root'] = os.path.abspath(
        os.path.join(this_file_root, '..', cfg['sound_folders_root'])
    )
logger.info('sound folders root: {}'.format(cfg['sound_folders_root']))
